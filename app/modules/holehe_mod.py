"""Holehe integration — open-source email account discovery.

Holehe checks ~120 sites to see whether an email address has an account, using
password-reset / signup responses (so it generally doesn't alert the owner).

We run the real CLI as a subprocess (installed in its own venv in Docker so its
deps don't touch the app's) and parse stdout for the "[+] domain" lines that mark
a site where the email is registered.
"""
import asyncio
import os
import re

HOLEHE_BIN = os.environ.get("HOLEHE_BIN", "holehe")

# "[+] domain.com" => used. The trailing legend line ("[+] Email used, ...") is
# excluded by requiring a dot in the captured token.
_USED = re.compile(r"^\[\+\]\s+(\S+)")


async def check_email_accounts(email: str, *, overall_timeout: int = 150) -> dict:
    email = email.strip()
    if not email:
        return {"available": True, "used": [], "error": "Empty email."}

    cmd = [HOLEHE_BIN, email, "--only-used", "--no-color", "--no-clear"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return {"available": False, "used": [],
                "error": "Holehe is not installed (pip install holehe)."}

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=overall_timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"available": True, "used": [], "error": "Holehe timed out."}

    used = []
    for line in out.decode("utf-8", "replace").splitlines():
        m = _USED.match(line.strip())
        if m and "." in m.group(1):
            used.append(m.group(1))
    return {"available": True, "used": sorted(set(used))}
