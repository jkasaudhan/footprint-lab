"""One-time-code email verification.

This is the consent mechanism: a deep scan only runs against an email address
the user can prove they control. Codes live in memory with a short TTL and are
never written to disk (privacy by design). For multi-process / production use,
swap the in-memory dict for Redis.
"""
import secrets
import smtplib
import time
from email.mime.text import MIMEText

from .config import settings

_CODE_TTL_SECONDS = 600  # 10 minutes
_MAX_ATTEMPTS = 5

# session_id -> {"email": str, "code": str, "expires": float, "attempts": int}
_pending: dict[str, dict] = {}


def issue_code(session_id: str, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    _pending[session_id] = {
        "email": email,
        "code": code,
        "expires": time.time() + _CODE_TTL_SECONDS,
        "attempts": 0,
    }
    _send(email, code)
    return code


def verify_code(session_id: str, submitted: str) -> tuple[bool, str]:
    rec = _pending.get(session_id)
    if not rec:
        return False, "No code was requested, or it has expired. Start again."
    if time.time() > rec["expires"]:
        _pending.pop(session_id, None)
        return False, "That code expired. Request a new one."
    if rec["attempts"] >= _MAX_ATTEMPTS:
        _pending.pop(session_id, None)
        return False, "Too many attempts. Start again."

    rec["attempts"] += 1
    if secrets.compare_digest(submitted.strip(), rec["code"]):
        return True, rec["email"]
    return False, "That code didn't match. Check the email and try again."


def clear(session_id: str) -> None:
    _pending.pop(session_id, None)


def _send(email: str, code: str) -> None:
    body = (
        f"Your {settings.app_name} verification code is: {code}\n\n"
        "It expires in 10 minutes. If you didn't request this, ignore it."
    )
    if settings.email_mode != "smtp" or not settings.smtp_host:
        # Dev mode: print so you can test without configuring SMTP.
        print(f"[verify] code for {email}: {code}", flush=True)
        return

    msg = MIMEText(body)
    msg["Subject"] = f"{settings.app_name} verification code"
    msg["From"] = settings.smtp_from
    msg["To"] = email
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
