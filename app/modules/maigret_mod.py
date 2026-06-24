"""Maigret integration (localhost research page only).

Runs the real `maigret` CLI as a subprocess and parses its "simple" JSON report.
Maigret is installed in an isolated virtualenv inside the Docker image, so its
dependencies never touch the FastAPI app's. We talk to it purely over the CLI.

The simple report is a dict keyed by site name; each found entry looks like:
    {
      "url_user": "https://site/uname",
      "status": {"status": "Claimed", "ids": {...extracted...}, "tags": [...]},
      ...
    }
The `ids` dict is where the genuinely useful intelligence lives -- real names,
locations, avatars, linked usernames pulled from the profile pages.
"""
import asyncio
import glob
import json
import os
import shutil
import tempfile

MAIGRET_BIN = os.environ.get("MAIGRET_BIN", "maigret")

# Keys we surface prominently in the aggregated profile panel.
_PROFILE_KEYS_PRIORITY = [
    "fullname", "name", "first_name", "last_name", "gender", "location",
    "country", "city", "bio", "about", "email", "phone", "birthday",
    "age", "username", "url",
]


import re
import time
from typing import Callable

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


async def run_maigret_streaming(
    username: str,
    on_line: Callable[[str], None],
    *,
    top_sites: int = 300,
    all_sites: bool = False,
    per_site_timeout: int = 10,
    overall_timeout: int = 300,
    echo: bool = True,
) -> dict:
    """Run Maigret, calling on_line() for each output line as it appears.

    Also echoes lines to stdout (visible in `docker compose logs -f app`) when
    echo is True. Returns the parsed result dict (or an {"error": ...} dict).
    """
    username = username.strip().lstrip("@")
    if not username:
        return {"error": "Empty username.", "username": username}

    outdir = tempfile.mkdtemp(prefix="maigret_")
    cmd = [
        MAIGRET_BIN, username,
        "-J", "simple",
        "-fo", outdir,
        "--timeout", str(per_site_timeout),
        "--retries", "1",
        "--no-progressbar",
    ]
    cmd += ["-a"] if all_sites else ["--top-sites", str(top_sites)]

    deadline = time.monotonic() + overall_timeout
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                on_line("[!] Scan timed out.")
                return {"error": "Scan timed out. Try a smaller site count.",
                        "username": username}
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                proc.kill()
                on_line("[!] Scan timed out.")
                return {"error": "Scan timed out. Try a smaller site count.",
                        "username": username}
            if not line:
                break
            text = _ANSI.sub("", line.decode("utf-8", "replace")).rstrip()
            if text:
                on_line(text)
                if echo:
                    print(f"[maigret] {text}", flush=True)
        await proc.wait()

        files = glob.glob(os.path.join(outdir, "*_simple.json"))
        if not files:
            return {"error": "Maigret produced no report (it may have failed to "
                             "reach sites or update its database).",
                    "username": username}
        with open(files[0], encoding="utf-8") as f:
            raw = json.load(f)
        return _parse(username, raw)
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


async def run_maigret(
    username: str,
    *,
    top_sites: int = 300,
    all_sites: bool = False,
    per_site_timeout: int = 10,
    overall_timeout: int = 300,
) -> dict:
    """Non-streaming wrapper (used by the no-JS fallback POST /research)."""
    return await run_maigret_streaming(
        username, lambda _l: None,
        top_sites=top_sites, all_sites=all_sites,
        per_site_timeout=per_site_timeout, overall_timeout=overall_timeout,
    )


def _parse(username: str, raw: dict) -> dict:
    accounts = []
    profile: dict[str, list[str]] = {}

    for sitename, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status") or {}
        url = entry.get("url_user") or status.get("url") or ""
        ids = status.get("ids") or {}
        tags = status.get("tags") or []

        accounts.append({
            "site": sitename,
            "url": url,
            "tags": [t for t in tags if t],
            "ids": ids,
        })
        for k, v in ids.items():
            if v in (None, "", []):
                continue
            vals = profile.setdefault(k, [])
            sval = str(v)
            if sval not in vals:
                vals.append(sval)

    accounts.sort(key=lambda a: a["site"].lower())
    profile = _order_profile(profile)
    return {
        "username": username,
        "found_count": len(accounts),
        "accounts": accounts,
        "profile": profile,
    }


def _order_profile(profile: dict[str, list[str]]) -> dict[str, list[str]]:
    ordered = {}
    for key in _PROFILE_KEYS_PRIORITY:
        if key in profile:
            ordered[key] = profile.pop(key)
    for key in sorted(profile):
        ordered[key] = profile[key]
    return ordered
