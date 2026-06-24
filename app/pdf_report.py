"""Structured, branded PDF export of a research result.

Pure-Python via fpdf2 (no system deps required). If a Unicode TTF is available
(the Docker image installs DejaVu), it's used so international names render
correctly; otherwise we fall back to a core font and sanitise to latin-1 so the
export never crashes on an exotic character.
"""
import os
from datetime import datetime, timezone

from fpdf import FPDF

_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_DEJAVU_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Deepfake Finance brand
TEAL = (3, 128, 149)
YELLOW = (251, 216, 132)
TEXT = (19, 18, 18)
MUTED = (94, 92, 92)
HAIR = (225, 224, 226)
WHITE = (255, 255, 255)

MARGIN = 16


def build_pdf(result: dict, depth_label: str = "") -> bytes:
    unicode_ok = os.path.exists(_DEJAVU) and os.path.exists(_DEJAVU_B)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.add_page()

    if unicode_ok:
        pdf.add_font("Brand", "", _DEJAVU)
        pdf.add_font("Brand", "B", _DEJAVU_B)
        font = "Brand"
    else:
        font = "Helvetica"

    def s(value) -> str:
        v = str(value)
        return v if unicode_ok else v.encode("latin-1", "replace").decode("latin-1")

    epw = pdf.epw  # effective page width

    # ---- header band ----
    pdf.set_fill_color(*TEAL)
    pdf.rect(0, 0, 210, 26, "F")
    pdf.set_xy(MARGIN, 7)
    pdf.set_font(font, "B", 18)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 9, s("Footprint Lab — Research report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(MARGIN)
    pdf.set_font(font, "", 9)
    pdf.cell(0, 5, s("Deepfake Finance · authorized research use only"))
    pdf.ln(20)

    # ---- meta ----
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf.set_text_color(*TEXT)
    _kv(pdf, font, s, "Username", result.get("username", "—"))
    _kv(pdf, font, s, "Accounts found", str(result.get("found_count", 0)))
    if depth_label:
        _kv(pdf, font, s, "Scan depth", depth_label)
    _kv(pdf, font, s, "Generated", generated)

    # yellow accent rule
    pdf.ln(2)
    pdf.set_draw_color(*YELLOW)
    pdf.set_line_width(1.2)
    y = pdf.get_y()
    pdf.line(MARGIN, y, MARGIN + 40, y)
    pdf.set_line_width(0.2)
    pdf.ln(6)

    # ---- aggregated profile ----
    profile = result.get("profile") or {}
    if profile:
        _section(pdf, font, s, "Aggregated profile", epw)
        for field, values in profile.items():
            label = str(field).replace("_", " ").title()
            value = "  ·  ".join(str(v) for v in values)
            _kv(pdf, font, s, label, value)
        pdf.ln(4)

    # ---- accounts ----
    accounts = result.get("accounts") or []
    if accounts:
        _section(pdf, font, s, f"Accounts found ({len(accounts)})", epw)
        for acc in accounts:
            pdf.set_font(font, "B", 11)
            pdf.set_text_color(*TEAL)
            pdf.cell(0, 6, s(acc.get("site", "")), new_x="LMARGIN", new_y="NEXT")

            url = acc.get("url") or ""
            if url:
                pdf.set_font(font, "", 9)
                pdf.set_text_color(*MUTED)
                pdf.set_x(MARGIN)
                pdf.multi_cell(0, 5, s(url), link=url)

            tags = acc.get("tags") or []
            if tags:
                pdf.set_font(font, "", 8)
                pdf.set_text_color(*MUTED)
                pdf.set_x(MARGIN)
                pdf.multi_cell(0, 5, s("tags: " + ", ".join(tags)))

            ids = acc.get("ids") or {}
            if ids:
                pdf.set_font(font, "", 9)
                pdf.set_text_color(*TEXT)
                for k, v in ids.items():
                    pdf.set_x(MARGIN + 3)
                    pdf.multi_cell(0, 5, s(f"{k}: {v}"))

            # hairline divider
            pdf.ln(1)
            pdf.set_draw_color(*HAIR)
            yy = pdf.get_y()
            pdf.line(MARGIN, yy, MARGIN + epw, yy)
            pdf.ln(3)

    out = pdf.output()
    return bytes(out)


def _section(pdf, font, s, title, epw):
    pdf.set_font(font, "B", 12)
    pdf.set_text_color(*TEAL)
    pdf.set_x(MARGIN)
    pdf.cell(0, 7, s(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*HAIR)
    y = pdf.get_y()
    pdf.line(MARGIN, y, MARGIN + epw, y)
    pdf.ln(3)


def _kv(pdf, font, s, label, value):
    pdf.set_x(MARGIN)
    pdf.set_font(font, "B", 10)
    pdf.set_text_color(*TEXT)
    pdf.cell(42, 6, s(label), new_x="RIGHT", new_y="TOP")
    pdf.set_font(font, "", 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 6, s(value))
