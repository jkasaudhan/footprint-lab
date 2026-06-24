"""Breach lookup via Have I Been Pwned (v3).

Requires an API key (HIBP_API_KEY). The endpoint is rate-limited per the key's
tier, so the app's own rate limiting should stay well under it. If no key is
configured the module returns a "disabled" marker rather than failing.
"""
import httpx

from ..config import settings

_API = "https://haveibeenpwned.com/api/v3/breachedaccount/{email}"


async def check_breaches(email: str) -> dict:
    if not settings.hibp_api_key:
        return {"enabled": False, "breaches": [], "note": "HIBP_API_KEY not set."}

    headers = {
        "hibp-api-key": settings.hibp_api_key,
        "User-Agent": "FootprintLab-educational",
    }
    params = {"truncateResponse": "false"}
    url = _API.format(email=email)

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params, timeout=15.0)

    if resp.status_code == 404:
        return {"enabled": True, "breaches": []}  # clean
    if resp.status_code == 200:
        breaches = [
            {
                "name": b.get("Title", b.get("Name")),
                "date": b.get("BreachDate"),
                "data": b.get("DataClasses", []),
            }
            for b in resp.json()
        ]
        return {"enabled": True, "breaches": breaches}

    return {
        "enabled": True,
        "breaches": [],
        "note": f"HIBP returned HTTP {resp.status_code}.",
    }
