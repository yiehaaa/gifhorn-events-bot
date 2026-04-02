"""
Claude API: Post-Text-Generierung und Bild-Sicherheitscheck (Vision).
Siehe 01d-CLAUDE-HANDLER.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from typing import Any, Dict, List, Tuple

import anthropic
import requests

from config import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_POST_TEMPLATE,
    EMAIL_FLYER_USE_CLAUDE_CAPTION,
    MOCK_MODE,
    INSTAGRAM_HASHTAGS,
)
from weather import weather_handler

logger = logging.getLogger(__name__)


def _first_text_block(message: Any) -> str:
    """Extrahiert Text aus Anthropic message.content (TextBlock / dict-ähnlich)."""
    for block in getattr(message, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text") or ""
    return ""


def _guess_media_type(url: str, content_type: str | None) -> str:
    """image/jpeg | image/png | image/webp | image/gif für Vision-API."""
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            return ct
    path = url.split("?")[0].lower()
    guessed, _ = mimetypes.guess_type(path)
    if guessed in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        return guessed
    return "image/jpeg"


class ClaudeHandler:
    def __init__(self) -> None:
        self.client = (
            anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None
        )
        self.model = CLAUDE_MODEL

    def generate_post_text(self, event: Dict[str, Any]) -> str:
        """Generiert Instagram-Post-Text für ein Event-Dict."""
        event_details = f"""
        Titel: {event.get('title', 'N/A')}
        Datum: {event.get('event_date', 'N/A')}
        Ort: {event.get('location', 'N/A')} ({event.get('city', 'N/A')})
        Preis: {event.get('price_min', '?')}–{event.get('price_max', '?')} €
        URL: {event.get('url', 'N/A')}
        Beschreibung: {event.get('description', '')}
        """

        # Wetter anreichern (fail-soft) und in den Claude-Prompt einbauen.
        try:
            weather = weather_handler.get_weather_for_date(str(event.get("event_date", "")))
            weather_text = weather_handler.format_weather_text(weather)
            if weather_text:
                event_details += f"\nWetter: {weather_text}\n"
        except Exception:
            pass

        # Mock-/Fallback: keinen externen API-Call machen.
        if self.client is None or MOCK_MODE:
            title = str(event.get("title") or "Event")
            dt = str(event.get("event_date") or "")
            loc = str(event.get("location") or "")
            city = str(event.get("city") or "")
            url = str(event.get("url") or "")
            hashtags = INSTAGRAM_HASHTAGS
            parts = [f"{title}"]
            if dt:
                parts.append(f"📅 {dt}")
            place = (loc + (f" ({city})" if city and city not in loc else "")).strip()
            if place:
                parts.append(f"📍 {place}")
            if url:
                parts.append(f"🔗 {url}")
            # 200-500 Zeichen grob einhalten
            text = "\n".join(parts) + f"\n\n{hashtags}"
            return text[:480]

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": CLAUDE_POST_TEMPLATE.format(
                            event_details=event_details,
                            hashtags=INSTAGRAM_HASHTAGS,
                        ),
                    }
                ],
            )
            post_text = _first_text_block(message).strip()
            if not post_text:
                raise ValueError("Leere Antwort von Claude")
            logger.info("Post-Text generiert für: %s", event.get("title", ""))
            return post_text

        except Exception as e:
            logger.error("Claude-Fehler: %s", e)
            title = event.get("title", "Event")
            loc = event.get("location", "")
            url = event.get("url", "")
            return f"{title}\n📍 {loc}\n🎫 {url}"

    def check_image_safety(self, image_url: str) -> Tuple[bool, str]:
        """Vision: (is_safe, reason)."""
        if self.client is None or MOCK_MODE:
            return (True, "Mock mode: Bild-Check übersprungen")
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code != 200:
                logger.warning("Bild nicht erreichbar: %s", image_url)
                return (True, "Bild nicht erreichbar, aber erlaubt")

            image_data = base64.standard_b64encode(response.content).decode("utf-8")
            media_type = _guess_media_type(
                image_url, response.headers.get("Content-Type")
            )

            message = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Prüfe dieses Bild: Ist es für Instagram/Facebook geeignet? "
                                    "Kurze Antwort nur 'JA' oder 'NEIN' + Grund."
                                ),
                            },
                        ],
                    }
                ],
            )

            response_text = _first_text_block(message).upper()
            is_safe = "JA" in response_text or "SAFE" in response_text

            logger.info(
                "Bild-Check: %s → %s",
                image_url,
                (response_text[:80] + "…") if len(response_text) > 80 else response_text,
            )
            return (is_safe, response_text or "KEINE ANTWORT")

        except Exception as e:
            logger.error("Vision-Check-Fehler: %s", e)
            return (True, "Fehler, aber erlaubt (Fallback)")

    def generate_caption_from_email(
        self, body_text: str, subject: str = "", image_path: str | None = None
    ) -> str:
        """
        Schreibt eine Instagram/Facebook Caption für einen Email-Flyer.
        Das Bild wird 1:1 als Post genutzt — Claude schreibt nur die Caption.

        Returns: Fertiger Caption-Text mit Hashtags
        """
        fallback = (
            f"📢 {subject or 'Neues Event'}\n\n"
            f"{body_text[:300] if body_text else ''}\n\n"
            f"{INSTAGRAM_HASHTAGS}"
        )

        # Standard: nur Flyer posten, Caption aus Mail — ohne Claude (nächster Schritt: API).
        if (
            not EMAIL_FLYER_USE_CLAUDE_CAPTION
            or self.client is None
            or MOCK_MODE
        ):
            return fallback

        content = []

        # Plakat-Bild mitschicken falls vorhanden (Claude liest Datum/Ort vom Bild)
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    image_data = base64.standard_b64encode(f.read()).decode("utf-8")
                media_type, _ = mimetypes.guess_type(image_path)
                if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                    media_type = "image/jpeg"
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                })
            except Exception as e:
                logger.warning("Bild konnte nicht geladen werden: %s", e)

        content.append({
            "type": "text",
            "text": f"""Du bist Social-Media-Manager für den Veranstaltungskanal Gifhorn & Umgebung.

Wichtig: Es gibt genau EIN Bild — der Flyer/ das Plakat aus der Email. Dieses Bild wird
1:1 als einziger Post auf Instagram/Facebook veröffentlicht. Du lieferst NUR den Begleittext
(Caption). Keine Vorschläge für weitere Bilder, Collagen oder KI-generierte Grafiken.

Schreibe die Instagram/Facebook-Caption für diesen Flyer.

Email-Betreff: {subject or '(kein Betreff)'}
Email-Inhalt: {body_text or '(kein Text)'}

Anforderungen:
- 150–400 Zeichen
- Lockerer, einladender Ton
- Datum, Uhrzeit und Ort prominent (aus Bild oder Email entnehmen)
- Hashtags am Ende: {INSTAGRAM_HASHTAGS}
- Nur die Caption, kein Kommentar drumherum"""
        })

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{"role": "user", "content": content}],
            )
            caption = _first_text_block(message).strip()
            if caption:
                return caption
        except Exception as e:
            logger.error("Claude Caption-Fehler: %s", e)

        return fallback

    def batch_generate_posts(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generiert post_text pro Event; optional Bild-Check."""
        results: List[Dict[str, Any]] = []
        for event in events:
            post_text = self.generate_post_text(event)
            event["post_text"] = post_text

            if event.get("image_url"):
                is_safe, reason = self.check_image_safety(event["image_url"])
                event["image_safe"] = is_safe
                event["image_reason"] = reason

            results.append(event)

        return results


claude_handler = ClaudeHandler()
