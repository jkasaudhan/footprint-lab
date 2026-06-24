---
title: Footprint Lab
emoji: 🛡️
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Footprint Lab

An **educational, self-assessment** footprint tool by Deepfake Finance. A person
enters their own email, verifies they control it, and sees what an attacker could
harvest about that address — where it's registered (via the open-source tool
Holehe) and whether it's turned up in known breaches (Have I Been Pwned). After
verifying, operators running it locally also get a username **research** page
(Maigret).

It is deliberately **not** a people-search engine:

- **Email-first** — the home page asks only for an email and verifies it.
- **Email ownership** — a one-time code is sent to the address; scans only run
  after it's confirmed, so you can only scan an email you control.
- **Stores nothing** — no query logs, no results on disk.
- **Rate limited** — throttled per IP.

---

## Run locally with Docker (recommended)

A ready-to-run `.env` is included (console email mode, generated secret).

```bash
docker compose up --build
```

Open **http://localhost:7860**. Verification codes print to the container log
(`docker compose logs -f app`) — look for `[verify] code for ...`.

## Run locally without Docker

```bash
cp .env.example .env        # set SECRET_KEY
pip install -r requirements.txt
# the research page also needs Maigret on PATH:  pip install maigret
uvicorn app.main:app --reload --port 7860
```

---

## Deploy to Hugging Face (Docker Space)

This repo is a ready-made **Docker Space**. The front matter at the top of this
README tells Hugging Face to build the Dockerfile and serve on port 7860.

1. Create a new Space → **SDK: Docker** → push this repo (or upload the files).
2. In **Settings → Variables and secrets**, add:
   - `SECRET_KEY` — a long random string
     (`python -c "import secrets; print(secrets.token_hex(32))"`).
   - `HIBP_API_KEY` *(optional)* — enables the breach module.
   - SMTP settings *(optional, see below)* — to actually email verification codes.
3. **Do not set `ENABLE_RESEARCH`.** It defaults off, which is what you want on a
   public Space (see "The research page" below).

The Dockerfile runs as a non-root user and listens on `$PORT` (7860), which is
exactly what Spaces expect — no extra config needed.

---

## How email verification works (and do you need an external service?)

The flow is simple and self-contained:

1. The user submits the form. The app generates a **random 6-digit code**, stores
   it **in memory** keyed to their session with a **10-minute expiry** (nothing is
   written to disk), and "sends" it to the email they entered.
2. The user types the code back in. The app compares it (constant-time) to the
   stored code. On a match, the session is marked **verified** — which both runs
   the breach check against that address and unlocks the research page.
3. Codes are single-purpose and capped at 5 attempts, then they're discarded.

**Do you need an external service? It depends on the mode (`EMAIL_MODE`):**

- **`console` (default — no external service):** the code is printed to the server
  log instead of emailed. Perfect for local development and testing — you read the
  code from `docker compose logs`. Zero setup, zero cost. The catch: on a *public*
  deployment your visitors can't see your logs, so console mode can't verify real
  users.
- **`smtp` (real emails — needs an SMTP sender):** the app sends the code over SMTP
  using `SMTP_HOST/PORT/USER/PASSWORD`. You point this at any SMTP service:
  - your own mail server, or
  - Gmail SMTP with an app password (fine for low volume), or
  - a transactional provider — Brevo, Mailgun, SendGrid, Amazon SES, Postmark
    (recommended for anything public; better deliverability and free tiers).

So: **local/testing → no external service** (console mode). **Public Space that
verifies real users → yes, set SMTP secrets** pointing at a provider. The app
code doesn't change — you only flip `EMAIL_MODE` and fill in the SMTP variables.

---

## The research page (advanced OSINT via Maigret)

There's a second page at **`/research`** that runs [Maigret](https://github.com/soxoj/maigret)
across thousands of sites for a username and extracts profile details (names,
locations, avatars, linked accounts) into one view, with a **Download PDF** export.

It has **two gates**: the `ENABLE_RESEARCH` flag **and** a verified-email session.
After you verify your email, a **Research** link appears in the header and the page
is unlocked.

**Keep `ENABLE_RESEARCH` off on any public deployment (including Hugging Face).**
Verifying your own inbox is *not* authorization to research other people — so this
stays a local / self-hosted, operator-controlled tool. The production compose
forces it off; on a Space, simply don't set the variable. Maigret is installed in
an isolated venv inside the image, so it never collides with the app's deps.

---

## Guardrails & GDPR

You operate in the EU, so GDPR applies. The self-lookup design keeps you on the
safe side: the person querying is the data subject, and nothing is stored. If you
ever let users query *other* people, you become a data controller without a lawful
basis — don't, at least not on a public tool. Keep the consent gate and email
verification (they're load-bearing), respect the Have I Been Pwned API terms, and
host in the EU where possible.

---

## Project layout

```
app/
  main.py            routes: email -> verify -> research (local) / email-scan
  config.py          settings from env / .env
  verify.py          in-memory one-time email codes (TTL)
  scoring.py         email findings -> severity + educational annotations
  pdf_report.py      branded, structured PDF export (fpdf2)
  modules/
    hibp_mod.py      Have I Been Pwned breach lookup
    holehe_mod.py    Holehe email-account discovery (email scan)
    maigret_mod.py   Maigret subprocess + parser (research page, streamed)
  templates/         index, verify, email_scan, research (+ spinner in base.html)
  static/css/        styles.css — all brand tokens in the :root block
Dockerfile           non-root, port 7860; bundles Maigret + Holehe venvs
docker-compose.yml   local run on :7860
docker-compose.prod.yml   app + Caddy (HTTPS), research forced off
```
