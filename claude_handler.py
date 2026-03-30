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

from config import CLAUDE_API_KEY, CLAUDE_MODEL, CLAUDE_POST_TEMPLATE, MOCK_MODE, INSTAGRAM_HASHTAGS, FACEBOOK_HASHTAGS
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
                            event_details=event_details
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
