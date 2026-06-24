"""Turn email-OSINT findings into an educational report.

Each finding carries a severity, an "attacker_note" (why someone targeting
you cares) and a "mitigation" (what to do).
"""

SEVERITY_ORDER = {"critical": 0, "notable": 1, "info": 2}


def build_email_report(email: str, holehe_result: dict, breach_result: dict) -> dict:
    """Email-only assessment: breach exposure (HIBP) + account discovery (Holehe).

    No username/handle findings here -- this report is purely about the email
    address the user verified.
    """
    findings: list[dict] = []

    # 1. Breaches (Have I Been Pwned)
    if breach_result.get("enabled"):
        breaches = breach_result.get("breaches", [])
        if breaches:
            findings.append({
                "title": f"Email appears in {len(breaches)} known breach(es)",
                "detail": ", ".join(f"{b['name']} ({b['date']})" for b in breaches),
                "severity": "critical",
                "attacker_note": (
                    "Leaked credentials fuel credential-stuffing and context-rich "
                    "phishing -- breach data is often the opening move."
                ),
                "mitigation": (
                    "Change reused passwords, use a password manager, and turn on "
                    "MFA everywhere -- ideally an authenticator app or hardware key."
                ),
            })
        else:
            findings.append({
                "title": "No breaches found for this email",
                "detail": "Have I Been Pwned returned no records.",
                "severity": "info",
                "attacker_note": "Lower exposure -- but absence isn't a guarantee.",
                "mitigation": "Keep MFA on and keep monitoring.",
            })
    else:
        findings.append({
            "title": "Breach check needs an API key",
            "detail": (breach_result.get("note") or
                       "Set HIBP_API_KEY to enable Have I Been Pwned breach checks."),
            "severity": "info",
            "attacker_note": "",
            "mitigation": "Get a key at haveibeenpwned.com/API/Key and set HIBP_API_KEY.",
        })

    # 2. Account discovery (Holehe)
    if holehe_result.get("available"):
        used = holehe_result.get("used", [])
        if used:
            findings.append({
                "title": f"Email is registered on {len(used)} site(s)",
                "detail": ", ".join(used),
                "severity": "critical" if len(used) >= 8 else "notable",
                "attacker_note": (
                    "Each linked account widens the attack surface and helps an "
                    "attacker map your online life, recovery paths, and habits."
                ),
                "mitigation": (
                    "Close accounts you no longer use, and avoid reusing this email "
                    "as the recovery address for high-value accounts."
                ),
            })
        elif not holehe_result.get("error"):
            findings.append({
                "title": "No registered accounts surfaced for this email",
                "detail": "Holehe found no sites where this email is registered.",
                "severity": "info",
                "attacker_note": "Lower discoverable surface.",
                "mitigation": "Keep using distinct emails for sensitive accounts.",
            })
        else:
            findings.append({
                "title": "Account discovery incomplete",
                "detail": holehe_result["error"],
                "severity": "info",
                "attacker_note": "",
                "mitigation": "Re-run, or check that Holehe is installed.",
            })
    else:
        findings.append({
            "title": "Account discovery tool unavailable",
            "detail": holehe_result.get("error", "Holehe is not installed."),
            "severity": "info",
            "attacker_note": "",
            "mitigation": "Install Holehe (pip install holehe) to enable this check.",
        })

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    counts = {"critical": 0, "notable": 0, "info": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"findings": findings, "counts": counts}
