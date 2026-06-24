"""Footprint Lab -- educational self-assessment OSINT tool.

Design stance baked into the routes:
  * A deep scan only runs against an email the user has *verified they control*.
  * Consent must be given explicitly before anything runs.
  * Nothing about a query is persisted to disk.
  * Requests are rate-limited to discourage bulk/abusive use.
"""
import asyncio
import json
import re
import secrets

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .modules.hibp_mod import check_breaches
from .modules.holehe_mod import check_email_accounts
from .modules.maigret_mod import run_maigret, run_maigret_streaming
from .pdf_report import build_pdf
from .scoring import build_email_report
from . import verify

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title=settings.app_name)
app.state.limiter = limiter
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["research_enabled"] = settings.enable_research


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return templates.TemplateResponse(
        request,
        "base.html",
        {"request": request, "app_name": settings.app_name,
         "flash": "Rate limit reached. This tool is throttled on purpose -- try later."},
        status_code=429,
    )


def _sid(request: Request) -> str:
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(16)
        request.session["sid"] = sid
    return sid


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"app_name": settings.app_name}
    )


@app.post("/start", response_class=HTMLResponse)
@limiter.limit(settings.rate_limit)
async def start(
    request: Request,
    email: str = Form(...),
    consent: str = Form(None),
):
    if not consent:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "app_name": settings.app_name,
             "flash": "You must confirm you're checking your own email."},
            status_code=400,
        )

    sid = _sid(request)
    verify.issue_code(sid, email.strip())
    request.session["pending_email"] = email.strip()
    return RedirectResponse("/verify", status_code=303)


@app.get("/verify", response_class=HTMLResponse)
async def verify_get(request: Request):
    if not request.session.get("pending_email"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "verify.html",
        {"request": request, "app_name": settings.app_name,
         "email": request.session["pending_email"]},
    )


@app.post("/verify", response_class=HTMLResponse)
async def verify_post(request: Request, code: str = Form(...)):
    sid = _sid(request)
    ok, payload = verify.verify_code(sid, code)
    if not ok:
        return templates.TemplateResponse(
            request,
            "verify.html",
            {"request": request, "app_name": settings.app_name,
             "email": request.session.get("pending_email"), "flash": payload},
            status_code=400,
        )
    request.session["verified_email"] = payload
    request.session["verified"] = True  # persists -> unlocks the research page
    request.session.pop("pending_email", None)
    verify.clear(sid)
    # Land on the research hub when it's enabled (local/operator); otherwise the
    # public self-assessment is the email scan of the address you just verified.
    target = "/research" if settings.enable_research else "/email-scan"
    return RedirectResponse(target, status_code=303)


@app.get("/email-scan", response_class=HTMLResponse)
@limiter.limit(settings.rate_limit)
async def email_scan(request: Request):
    email = request.session.get("verified_email")
    if not email or not request.session.get("verified"):
        return RedirectResponse("/", status_code=303)

    # Email-only OSINT: account discovery (Holehe) + breach exposure (HIBP).
    holehe_result = await check_email_accounts(email)
    breach_result = await check_breaches(email)
    report = build_email_report(email, holehe_result, breach_result)

    return templates.TemplateResponse(
        request,
        "email_scan.html",
        {"request": request, "app_name": settings.app_name,
         "email_masked": _mask(email), "report": report},
    )


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    shown = name[:2] if len(name) > 2 else name[:1]
    return f"{shown}{'*' * max(1, len(name) - len(shown))}@{domain}"


# ---------------------------------------------------------------------------
# Research page (advanced OSINT via Maigret).
# Two gates: the feature flag (ENABLE_RESEARCH) AND a verified email session.
# Keep ENABLE_RESEARCH OFF on any public deployment -- verifying your own inbox
# is not authorization to research other people, so this stays a local/self-
# hosted, operator-controlled tool.
# ---------------------------------------------------------------------------
def _require_research_enabled():
    if not settings.enable_research:
        raise HTTPException(status_code=404)


def _unverified_redirect(request: Request):
    """Render the entry page with a prompt to verify first."""
    return templates.TemplateResponse(
        request, "index.html",
        {"app_name": settings.app_name,
         "flash": "Verify your email first to unlock the research page."},
        status_code=403,
    )


@app.get("/research", response_class=HTMLResponse)
async def research_get(request: Request):
    _require_research_enabled()
    if not request.session.get("verified"):
        return _unverified_redirect(request)
    return templates.TemplateResponse(
        request, "research.html",
        {"app_name": settings.app_name, "default_top": settings.research_top_sites},
    )


@app.post("/research", response_class=HTMLResponse)
async def research_post(
    request: Request,
    username: str = Form(...),
    depth: str = Form("top"),
    acknowledge: str = Form(None),
):
    _require_research_enabled()
    if not request.session.get("verified"):
        return _unverified_redirect(request)
    if not acknowledge:
        return templates.TemplateResponse(
            request, "research.html",
            {"app_name": settings.app_name, "default_top": settings.research_top_sites,
             "flash": "Confirm this is authorized research before running."},
            status_code=400,
        )

    all_sites = depth == "all"
    result = await run_maigret(
        username,
        top_sites=settings.research_top_sites,
        all_sites=all_sites,
        per_site_timeout=settings.research_per_site_timeout,
    )
    return templates.TemplateResponse(
        request, "research.html",
        {"app_name": settings.app_name, "default_top": settings.research_top_sites,
         "result": result, "submitted": username.strip(),
         "depth_label": "all sites" if all_sites else f"top {settings.research_top_sites}"},
    )


@app.post("/research/pdf")
async def research_pdf(
    request: Request,
    payload: str = Form(...),
    depth_label: str = Form(""),
):
    _require_research_enabled()
    if not request.session.get("verified"):
        raise HTTPException(status_code=403, detail="Verify your email first.")
    try:
        result = json.loads(payload)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed report payload.")

    pdf_bytes = build_pdf(result, depth_label)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(result.get("username", "report")))[:60]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="footprint-{safe}.pdf"'},
    )


# ---- Live-progress scan (streamed) --------------------------------------
# Single-process, in-memory job store -> fine for a local/self-hosted tool.
_JOBS: dict[str, dict] = {}


async def _run_job(token: str):
    job = _JOBS.get(token)
    if not job:
        return

    def on_line(line: str):
        j = _JOBS.get(token)
        if j is not None:
            j["lines"].append(line)

    try:
        result = await run_maigret_streaming(
            job["submitted"], on_line,
            top_sites=settings.research_top_sites,
            all_sites=job["all_sites"],
            per_site_timeout=settings.research_per_site_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        result = {"error": f"Scan failed: {type(exc).__name__}",
                  "username": job["submitted"]}
    j = _JOBS.get(token)
    if j is not None:
        j["result"] = result
        j["done"] = True


@app.post("/research/start")
async def research_start(
    request: Request,
    username: str = Form(...),
    depth: str = Form("top"),
    acknowledge: str = Form(None),
):
    _require_research_enabled()
    if not request.session.get("verified"):
        raise HTTPException(status_code=403, detail="Verify your email first.")
    if not acknowledge:
        raise HTTPException(status_code=400, detail="Authorized-research confirmation required.")

    # prune abandoned finished jobs
    for t in [t for t, j in _JOBS.items() if j.get("done")]:
        _JOBS.pop(t, None)

    token = secrets.token_urlsafe(8)
    _JOBS[token] = {"lines": [], "done": False, "result": None,
                    "submitted": username.strip(), "all_sites": depth == "all"}
    asyncio.create_task(_run_job(token))
    return JSONResponse({"token": token})


@app.get("/research/events/{token}")
async def research_events(request: Request, token: str):
    _require_research_enabled()
    if not request.session.get("verified"):
        raise HTTPException(status_code=403)

    async def gen():
        idx = 0
        while True:
            job = _JOBS.get(token)
            if job is None:
                yield "event: failed\ndata: expired\n\n"
                return
            while idx < len(job["lines"]):
                line = job["lines"][idx].replace("\r", " ")
                idx += 1
                yield f"data: {line}\n\n"
            if job["done"]:
                yield "event: done\ndata: ok\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/research/result/{token}", response_class=HTMLResponse)
async def research_result(request: Request, token: str):
    _require_research_enabled()
    if not request.session.get("verified"):
        return _unverified_redirect(request)
    job = _JOBS.pop(token, None)
    if not job or job.get("result") is None:
        return RedirectResponse("/research", status_code=303)
    return templates.TemplateResponse(
        request, "research.html",
        {"app_name": settings.app_name, "default_top": settings.research_top_sites,
         "result": job["result"], "submitted": job["submitted"],
         "depth_label": "all sites" if job["all_sites"]
                        else f"top {settings.research_top_sites}"},
    )
