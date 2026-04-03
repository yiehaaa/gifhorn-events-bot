"""
Auto-Flyer (HTML/Playwright oder Pillow) — gemeinsam für Formular und Refresh vor Telegram.
"""

from __future__ import annotations

import logging
import tempfile
import textwrap
import uuid
from html import escape
from pathlib import Path

from config import EMAIL_ATTACHMENT_STORAGE_PATH, FLYER_RENDER_PROVIDER

logger = logging.getLogger(__name__)

_flyer_palette_index = 0


def _next_flyer_palette() -> dict:
    """Rotate palettes to avoid repeated colors in sequence."""
    global _flyer_palette_index
    palettes = [
        {
            "name": "blue",
            "bg_top": "#1a2443",
            "bg_bottom": "#0d1326",
            "orb1": "#4a67ff",
            "orb2": "#2a3f8e",
            "label": "#9aabff",
        },
        {
            "name": "green",
            "bg_top": "#213528",
            "bg_bottom": "#101c14",
            "orb1": "#35c46a",
            "orb2": "#1f7c45",
            "label": "#97f0b7",
        },
        {
            "name": "orange",
            "bg_top": "#3b2620",
            "bg_bottom": "#1b120f",
            "orb1": "#ff8a52",
            "orb2": "#a6522f",
            "label": "#ffc5a5",
        },
        {
            "name": "violet",
            "bg_top": "#2d2340",
            "bg_bottom": "#141021",
            "orb1": "#b07cff",
            "orb2": "#6942b6",
            "label": "#d3b8ff",
        },
        {
            "name": "teal",
            "bg_top": "#14333a",
            "bg_bottom": "#0a1a1d",
            "orb1": "#2cb9c9",
            "orb2": "#1d6d7a",
            "label": "#9debf2",
        },
        {
            "name": "rose",
            "bg_top": "#3b1f2d",
            "bg_bottom": "#1a0f15",
            "orb1": "#e067a6",
            "orb2": "#8a3d67",
            "label": "#ffc2e3",
        },
        {
            "name": "amber",
            "bg_top": "#3d2d15",
            "bg_bottom": "#1c140a",
            "orb1": "#f2aa3b",
            "orb2": "#a96d22",
            "label": "#ffd99c",
        },
        {
            "name": "cyan",
            "bg_top": "#193746",
            "bg_bottom": "#0b1820",
            "orb1": "#46bfff",
            "orb2": "#2a6f96",
            "label": "#afe3ff",
        },
        {
            "name": "mint",
            "bg_top": "#1b3a32",
            "bg_bottom": "#0d1c18",
            "orb1": "#52d69c",
            "orb2": "#2b8f66",
            "label": "#bdf3db",
        },
        {
            "name": "berry",
            "bg_top": "#3a1d3a",
            "bg_bottom": "#190d19",
            "orb1": "#cc6ae2",
            "orb2": "#7a3f8b",
            "label": "#efc0fa",
        },
        {
            "name": "coral",
            "bg_top": "#3d2626",
            "bg_bottom": "#1d1212",
            "orb1": "#ff7a6e",
            "orb2": "#a74c45",
            "label": "#ffc0b8",
        },
        {
            "name": "indigo",
            "bg_top": "#20295a",
            "bg_bottom": "#0f1330",
            "orb1": "#7286ff",
            "orb2": "#4555aa",
            "label": "#c0c9ff",
        },
        {
            "name": "lime",
            "bg_top": "#2d3a1b",
            "bg_bottom": "#151c0d",
            "orb1": "#b4d93f",
            "orb2": "#6f8829",
            "label": "#e3f6a8",
        },
        {
            "name": "slate",
            "bg_top": "#2a313d",
            "bg_bottom": "#12161c",
            "orb1": "#8ca0b8",
            "orb2": "#59697a",
            "label": "#d0d9e3",
        },
        {
            "name": "magenta",
            "bg_top": "#3e1f45",
            "bg_bottom": "#1d1020",
            "orb1": "#e071f0",
            "orb2": "#8b4796",
            "label": "#f3c2fb",
        },
    ]
    palette = palettes[_flyer_palette_index % len(palettes)]
    _flyer_palette_index += 1
    return palette


async def render_auto_flyer_png(
    *,
    title: str,
    description: str,
    flyer_date_text: str,
    times_str: str,
    location_line: str,
) -> str:
    """
    Erzeugt ein 1080x1350 PNG unter EMAIL_ATTACHMENT_STORAGE_PATH.
    Gibt relativen Pfad zurück, z. B. /flyers/{uuid}.png
    """
    flyer_url = ""

    if FLYER_RENDER_PROVIDER == "html":
        try:
            from playwright.async_api import async_playwright

            flyers_dir = Path(EMAIL_ATTACHMENT_STORAGE_PATH)
            flyers_dir.mkdir(parents=True, exist_ok=True)
            generated_name = f"{uuid.uuid4().hex}.png"
            generated_path = flyers_dir / generated_name

            safe_title = escape((title or "").strip())[:120]
            safe_date = escape(flyer_date_text)[:160]
            safe_time = escape((times_str or "Uhrzeit folgt"))[:120]
            safe_location = escape((location_line or "").strip())[:160]
            safe_description = escape((description or "").strip())[:220]

            palette = _next_flyer_palette()

            html = f"""
                    <!doctype html>
                    <html>
                    <head>
                      <meta charset="utf-8">
                      <style>
                        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                        body {{
                          width: 1080px; height: 1350px; overflow: hidden;
                          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                          background: linear-gradient(180deg, {palette["bg_top"]} 0%, {palette["bg_bottom"]} 100%);
                          color: #f4f7ff;
                        }}
                        .orb1 {{
                          position: absolute; left: -180px; top: -180px;
                          width: 560px; height: 560px; border-radius: 50%;
                          background: {palette["orb1"]};
                        }}
                        .orb2 {{
                          position: absolute; right: -220px; bottom: -260px;
                          width: 700px; height: 700px; border-radius: 50%;
                          background: {palette["orb2"]};
                        }}
                        .card {{
                          position: absolute; inset: 48px 42px 56px;
                          border-radius: 42px; background: #12182b;
                          padding: 52px 56px;
                        }}
                        .title {{
                          font-size: 90px; line-height: 0.98; font-weight: 800;
                          letter-spacing: -0.02em; margin-bottom: 34px;
                          display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
                        }}
                        .item {{ margin-bottom: 24px; }}
                        .label {{
                          color: {palette["label"]}; font-size: 28px; font-weight: 700;
                          text-transform: uppercase; margin-bottom: 6px;
                        }}
                        .value {{
                          color: #e5ecff; font-size: 46px; font-weight: 650; line-height: 1.06;
                          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                        }}
                        .desc .value {{
                          white-space: normal; overflow: hidden; text-overflow: unset;
                          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                          font-size: 34px; line-height: 1.15; color: #d6dff9;
                        }}
                        .footer {{
                          position: absolute; left: 56px; bottom: 46px;
                          color: #98a9e7; font-size: 32px; font-weight: 600;
                        }}
                      </style>
                    </head>
                    <body>
                      <div class="orb1"></div>
                      <div class="orb2"></div>
                      <div class="card">
                        <div class="title">{safe_title}</div>
                        <div class="item"><div class="label">Datum</div><div class="value">{safe_date}</div></div>
                        <div class="item"><div class="label">Uhrzeit</div><div class="value">{safe_time}</div></div>
                        <div class="item"><div class="label">Ort</div><div class="value">{safe_location or "Ort folgt"}</div></div>
                        <div class="item desc"><div class="label">Info</div><div class="value">{safe_description or "Weitere Infos folgen."}</div></div>
                        <div class="footer">@suedheide.veranstaltungen</div>
                      </div>
                    </body>
                    </html>
                    """

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(html)
                tmp_path = Path(tmp.name)

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(args=["--no-sandbox"])
                    try:
                        page = await browser.new_page(
                            viewport={"width": 1080, "height": 1350}
                        )
                        # file:// + networkidle haengt oft / timeout → stiller Fallback auf Pillow
                        await page.goto(
                            tmp_path.resolve().as_uri(),
                            wait_until="domcontentloaded",
                            timeout=90_000,
                        )
                        await page.screenshot(path=str(generated_path), full_page=False)
                    finally:
                        await browser.close()
                flyer_url = f"/flyers/{generated_name}"
                logger.info(
                    "HTML-Flyer generiert: %s (palette=%s)",
                    generated_name,
                    palette["name"],
                )
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("HTML-Flyer fehlgeschlagen, fallback lokal: %s", e)

    if not flyer_url:
        try:
            from PIL import Image, ImageDraw, ImageFont

            flyers_dir = Path(EMAIL_ATTACHMENT_STORAGE_PATH)
            flyers_dir.mkdir(parents=True, exist_ok=True)

            generated_name = f"{uuid.uuid4().hex}.png"
            generated_path = flyers_dir / generated_name

            width, height = 1080, 1350
            img = Image.new("RGB", (width, height), color=(14, 18, 30))
            draw = ImageDraw.Draw(img)

            def _font(size: int):
                candidates = [
                    "DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                ]
                for candidate in candidates:
                    try:
                        return ImageFont.truetype(candidate, size)
                    except Exception:
                        continue
                return ImageFont.load_default()

            title_font = _font(88)
            body_font = _font(46)
            small_font = _font(34)
            tag_font = _font(30)

            top = (24, 31, 55)
            bottom = (12, 15, 24)
            for y in range(height):
                ratio = y / float(height - 1)
                r = int(top[0] * (1 - ratio) + bottom[0] * ratio)
                g = int(top[1] * (1 - ratio) + bottom[1] * ratio)
                b = int(top[2] * (1 - ratio) + bottom[2] * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            draw.ellipse((-220, -180, 460, 500), fill=(66, 92, 245))
            draw.ellipse((580, 920, 1320, 1620), fill=(38, 52, 112))

            card = (42, 64, 1038, 1290)
            draw.rounded_rectangle(card, radius=42, fill=(19, 24, 39))

            y = 180
            max_width_chars = 18
            for line in textwrap.wrap((title or "").strip(), width=max_width_chars)[:3]:
                draw.text((96, y), line, fill=(248, 250, 255), font=title_font)
                y += 102

            y += 12
            date_line = flyer_date_text
            times_preview = times_str if times_str else "Uhrzeit folgt"
            place_line = (location_line or "").strip()

            for info in [
                ("DATUM", date_line),
                ("UHRZEIT", times_preview[:72]),
                ("ORT", place_line[:80] if place_line else "Ort folgt"),
            ]:
                label, value = info
                draw.text((96, y), label, fill=(124, 146, 250), font=tag_font)
                y += 40
                for line in textwrap.wrap(value, width=30)[:1]:
                    draw.text((96, y), line, fill=(221, 228, 255), font=body_font)
                    y += 58
                y += 10

            if description:
                draw.text((96, y), "INFO", fill=(124, 146, 250), font=tag_font)
                y += 40
                for line in textwrap.wrap(description.strip(), width=34)[:2]:
                    draw.text((96, y), line, fill=(205, 214, 245), font=small_font)
                    y += 46

            footer_y = min(max(y + 36, 1160), 1240)
            draw.text(
                (96, footer_y),
                "@suedheide.veranstaltungen",
                fill=(145, 162, 240),
                font=small_font,
            )

            img.save(generated_path, format="PNG")
            flyer_url = f"/flyers/{generated_name}"
            logger.info("Auto-Flyer generiert (Pillow): %s", generated_name)
        except Exception as e:
            logger.error("Auto-Flyer konnte nicht erzeugt werden: %s", e)
            raise ValueError(
                "Kein Flyer hochgeladen und Auto-Bild konnte nicht erzeugt werden. "
                "Bitte Flyer-Datei hochladen oder erneut versuchen."
            ) from e

    return flyer_url
