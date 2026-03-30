"""
Tägliche Orchestrierung: Sammeln → Telegram-Freigabe; später Meta-Posting.
Railway/Cron: typischerweise nur `collect_and_approve_flow` (z. B. 19:00).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List

from claude_handler import claude_handler
from config import GOOGLE_CREDENTIALS_FILE, MOCK_MODE, SCRAPERS_ENABLED
from database import db
from deduplication import deduplicator
from email_handler import email_handler
from meta_poster import meta_poster
from scrapers import collect_all_events
from gcal_sync import gcal_sync
from telegram_bot import telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_and_approve_flow() -> None:
    """Neue Events sammeln, deduplizieren, speichern, Telegram-Batch senden."""
    logger.info("Starte Event-Sammlung …")
    try:
        db.connect()
        db.create_tables()

        all_events: List[Dict[str, Any]] = []
        if SCRAPERS_ENABLED and not MOCK_MODE:
            all_events = collect_all_events()

        if os.path.exists(GOOGLE_CREDENTIALS_FILE):
            try:
                email_handler.authenticate()
                for msg in email_handler.search_event_submissions():
                    content = email_handler.get_message_content(msg["id"])
                    if content.get("body"):
                        logger.info(
                            "Mail-Stub: %s — Inhalt in Phase 2 parsen",
                            content.get("subject"),
                        )
            except Exception as e:
                logger.warning("Gmail nicht verfügbar: %s", e)

        unique_events = deduplicator.deduplicate_list(all_events)
        events_with_posts = claude_handler.batch_generate_posts(unique_events)

        for event in events_with_posts:
            eid = db.add_event(
                source=event.get("source") or "manual",
                source_id=event.get("source_id") or f"tmp-{uuid.uuid4().hex[:16]}",
                title=event.get("title") or "Untitled",
                description=event.get("description") or "",
                image_url=event.get("image_url") or "",
                event_date=event.get("event_date") or "1970-01-01",
                location=event.get("location") or "",
                city=event.get("city") or "",
                price_min=event.get("price_min"),
                price_max=event.get("price_max"),
                url=event.get("url"),
                post_text=event.get("post_text"),
            )
            if eid is not None:
                event["id"] = eid

        pending = db.get_events_awaiting_telegram()
        if not MOCK_MODE and not getattr(telegram_bot, "disabled", False):
            await telegram_bot.send_events_for_approval(pending)
        logger.info("Event-Sammlung abgeschlossen")

    except Exception as e:
        logger.exception("Sammlung-Fehler: %s", e)
        try:
            db.log_message("ERROR", str(e), {"flow": "collect_and_approve_flow"})
        except Exception:
            pass
    finally:
        db.close()


async def post_approved_events() -> None:
    """Freigegebene Events auf Instagram/Facebook posten."""
    logger.info("Starte Meta-Posting …")
    try:
        db.connect()
        approved = db.get_events_ready_for_meta()
        if not approved:
            logger.info("Keine freigegebenen Events zum Posten")
            return

        meta_poster.batch_post(approved, platforms=["instagram", "facebook"])
        logger.info("Meta-Posting abgeschlossen")

        # Google Calendar Sync (fail-soft) nur im Realbetrieb
        if not MOCK_MODE:
            try:
                gcal_sync.sync_events()
            except Exception as e:
                logger.warning("GCal Sync fehlgeschlagen: %s", e)

    except Exception as e:
        logger.exception("Posting-Fehler: %s", e)
        try:
            db.log_message("ERROR", str(e), {"flow": "post_approved_events"})
        except Exception:
            pass
    finally:
        db.close()


async def main() -> None:
    await collect_and_approve_flow()


if __name__ == "__main__":
    asyncio.run(main())
