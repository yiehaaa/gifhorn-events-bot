"""
Instagram & Facebook DM Handler (Webhook).
Siehe Vault-Doku 02e-DM-HANDLER.

Hinweis:
- Phase2-DM ist Webhook-basiert; das Modul ist fail-soft und soll keinen Import/Start blockieren.
- Router ist als FastAPI-Komponente gebaut, damit es später einfach montiert werden kann.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from config import META_ACCESS_TOKEN
from database import db

logger = logging.getLogger(__name__)


class DMHandler:
    def __init__(self, access_token: Optional[str] = None) -> None:
        self.access_token = access_token or META_ACCESS_TOKEN
        self.verify_token = os.getenv("DM_WEBHOOK_VERIFY_TOKEN", "secret_verify_token")

    def parse_event_from_text(self, text: str) -> Dict[str, Any]:
        """Extrahiere Event-Daten aus Text (Stub; später mit Claude verbessern)."""
        return {
            "title": "Event aus DM",
            "description": text,
            "city": "Gifhorn",
        }

    def send_reply(self, recipient_id: str, message: str) -> None:
        """Antwort senden (fail-soft)."""
        if not self.access_token:
            return
        url = "https://graph.facebook.com/v18.0/me/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message},
            "access_token": self.access_token,
        }
        try:
            requests.post(url, json=payload, timeout=20).raise_for_status()
        except Exception as e:
            logger.warning("DM reply fehlgeschlagen: %s", e)

    def handle_message(self, message: Dict[str, Any], platform: str) -> None:
        sender = message.get("sender") or {}
        sender_id = sender.get("id")
        text = (message.get("message") or {}).get("text") or ""
        timestamp = message.get("timestamp") or datetime.now(timezone.utc).isoformat()

        if not sender_id or not text:
            return

        event_data = self.parse_event_from_text(text)
        if not event_data:
            self.send_reply(sender_id, "❌ Event konnte nicht geparst werden")
            return

        try:
            db.connect()
            db.create_tables()
            db.add_event(
                source=f"dm_{platform}",
                source_id=f"{sender_id}_{timestamp}",
                title=str(event_data.get("title") or "Event aus DM"),
                description=str(event_data.get("description") or ""),
                image_url=str(event_data.get("image_url") or ""),
                event_date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                location=str(event_data.get("location") or ""),
                city=str(event_data.get("city") or "Gifhorn"),
                price_min=event_data.get("price_min"),
                price_max=event_data.get("price_max"),
                url=str(event_data.get("url") or ""),
                post_text=None,
            )
            self.send_reply(sender_id, f"✅ Event erhalten (via {platform}). Danke!")
            logger.info("✅ DM Event eingereicht (%s)", platform)
        except Exception as e:
            logger.warning("DM handle fehlgeschlagen: %s", e)
            self.send_reply(sender_id, "❌ Interner Fehler beim Speichern. Bitte später erneut.")
        finally:
            try:
                db.close()
            except Exception:
                pass


def create_dm_router(handler: Optional[DMHandler] = None) -> APIRouter:
    """FastAPI Router für Instagram/Facebook Webhooks."""
    h = handler or DMHandler()
    router = APIRouter()

    @router.get("/webhook/instagram")
    async def instagram_webhook_get(request: Request) -> PlainTextResponse:
        params = dict(request.query_params)
        if params.get("hub.verify_token") == h.verify_token:
            return PlainTextResponse(params.get("hub.challenge") or "")
        return PlainTextResponse("Unauthorized", status_code=401)

    @router.post("/webhook/instagram")
    async def instagram_webhook_post(request: Request) -> PlainTextResponse:
        data = await request.json()
        for entry in data.get("entry", []) or []:
            for message in entry.get("messaging", []) or []:
                # Sync (DB + requests) darf den ASGI-Event-Loop nicht blockieren —
                # sonst hängen /health und das ganze Dashboard.
                await asyncio.to_thread(h.handle_message, message, "instagram")
        return PlainTextResponse("OK")

    @router.get("/webhook/facebook")
    async def facebook_webhook_get(request: Request) -> PlainTextResponse:
        params = dict(request.query_params)
        if params.get("hub.verify_token") == h.verify_token:
            return PlainTextResponse(params.get("hub.challenge") or "")
        return PlainTextResponse("Unauthorized", status_code=401)

    @router.post("/webhook/facebook")
    async def facebook_webhook_post(request: Request) -> PlainTextResponse:
        data = await request.json()
        for entry in data.get("entry", []) or []:
            for message in entry.get("messaging", []) or []:
                await asyncio.to_thread(h.handle_message, message, "facebook")
        return PlainTextResponse("OK")

    return router


dm_handler = DMHandler()

