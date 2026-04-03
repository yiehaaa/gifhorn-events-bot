"""
Tägliche Orchestrierung: Sammeln → Telegram-Freigabe; später Meta-Posting.
Railway/Cron: typischerweise nur `collect_and_approve_flow` (z. B. 19:00).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from claude_handler import claude_handler
from config import (
    AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS,
    AUTO_POST_AFTER_EMAIL_CONVERSION,
    EMAIL_KEYWORDS,
    EMAIL_MAX_ATTACHMENT_SIZE,
    EMAIL_MIN_ATTACHMENT_SIZE,
    EMAIL_REQUIRE_ATTACHMENTS,
    EMAIL_SCREENING_ENABLED,
    EMAIL_SENDER_PATTERNS,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_FORM_SPREADSHEET_ID,
    GOOGLE_TOKEN_FILE,
    MOCK_MODE,
    REJECTED_RETENTION_DAYS,
    SCRAPERS_ENABLED,
    email_screener,
    public_image_url,
)
from database import db
from deduplication import deduplicator
from email_handler import email_handler, gmail_oauth_configured
from google_form_handler import google_form_handler
from meta_poster import meta_poster
from scrapers import collect_all_events
from gcal_sync import gcal_sync
from scrapers.email_screener import EmailScreener
from telegram_bot import telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _run_email_screening_digest_to_telegram(flow_name: str) -> int:
    """
    Gmail (unbearbeitet) → Screening → DB-Zeilen → Telegram-Digest.
    Voraussetzung: db ist verbunden.
    Rückgabe: Anzahl Mails, die in den Digest aufgenommen wurden (0 = keiner gesendet).
    """
    if not EMAIL_SCREENING_ENABLED:
        return 0
    if not gmail_oauth_configured():
        logger.info(
            "📧 Email-Screening übersprungen: kein Gmail-OAuth "
            "(token.json / GOOGLE_TOKEN_JSON / client_secret / GOOGLE_OAUTH_CLIENT_SECRET_JSON)"
        )
        return 0

    logger.info("📧 Starte Email-Screening…")
    digest_count = 0
    try:
        email_handler.authenticate()

        pending_emails = email_handler.get_pending_email_submissions()
        logger.info("📧 %s unbearbeitete Emails aus Gmail", len(pending_emails))

        if not pending_emails or not email_screener:
            return 0

        db_patterns = db.get_email_sender_whitelist_patterns()
        merged = list(dict.fromkeys(EMAIL_SENDER_PATTERNS + db_patterns))
        active_screener = EmailScreener(
            sender_patterns=merged,
            keywords=EMAIL_KEYWORDS,
            require_attachments=EMAIL_REQUIRE_ATTACHMENTS,
            min_attachment_size=EMAIL_MIN_ATTACHMENT_SIZE,
            max_attachment_size=EMAIL_MAX_ATTACHMENT_SIZE,
        )
        screened_emails = active_screener.filter_submissions(pending_emails)
        logger.info("📧 Nach Screening: %s relevante Emails", len(screened_emails))

        if not screened_emails:
            return 0

        ingest_batch_hex = uuid.uuid4().hex
        emails_for_telegram: List[Dict[str, Any]] = []
        for email in screened_emails:
            row_id = db.add_email_submission(
                gmail_message_id=email.get("id"),
                sender_email=email.get("sender", "unknown"),
                subject=email.get("subject", ""),
                body_text=email.get("body", ""),
                attachment_urls={},
                screening_score=email.get("screening_score", 0),
                matched_filters=email.get("matched_filters", {}),
                ingest_batch_id=ingest_batch_hex,
            )
            if row_id is not None:
                payload = dict(email)
                payload["db_submission_id"] = row_id
                emails_for_telegram.append(payload)

        if emails_for_telegram and not getattr(telegram_bot, "disabled", False):
            await telegram_bot.send_daily_email_digest(
                emails_for_telegram, ingest_batch_hex
            )
        digest_count = len(emails_for_telegram)
        logger.info(
            "📧 %s Mails im Digest (von %s gescreent, batch=%s…)",
            digest_count,
            len(screened_emails),
            ingest_batch_hex[:8],
        )

    except Exception as e:
        logger.warning("❌ Email-Screening Fehler: %s", e)
        try:
            db.log_message(
                "WARNING",
                f"Email-Screening Fehler: {e}",
                {"flow": flow_name},
            )
        except Exception:
            pass

    return digest_count


async def notify_telegram_first_round_for_new_events(event_ids: List[int]) -> int:
    """
    Nach Mail→Event: dieselbe Telegram-Runde wie beim Portal-Collect
    (Menü „Events zur Revision“ / send_events_for_approval).
    """
    if not event_ids or getattr(telegram_bot, "disabled", False):
        return 0
    to_send: List[Dict[str, Any]] = []
    for eid in event_ids:
        row = db.get_event_by_id(eid)
        if not row or row.get("posted_at"):
            continue
        if row.get("telegram_rejected") in (True, 1):
            continue
        if row.get("approved_for_social") in (True, 1):
            continue
        to_send.append(row)
    if not to_send:
        return 0
    await telegram_bot.send_events_for_approval(to_send)
    return len(to_send)


async def run_manual_email_flyer_collect() -> str:
    """
    Nur E-Mail-/Flyer-Pipeline wie im 19-Uhr-Collect (ohne Portal-Scraper, ohne neue Portal-Events).
    Verarbeitet danach wie üblich bereits freigegebene Mails (KI → Event).
    """
    if not EMAIL_SCREENING_ENABLED:
        return "E-Mail-Screening ist aus (EMAIL_SCREENING_ENABLED=0)."
    if not gmail_oauth_configured():
        return (
            "Gmail nicht konfiguriert. Railway: Secrets setzen — "
            "GOOGLE_TOKEN_JSON (Inhalt von token.json) und optional "
            "GOOGLE_OAUTH_CLIENT_SECRET_JSON (Inhalt von client_secret.json) "
            "oder beide Dateien mounten. Siehe .env.example."
        )
    try:
        db.connect()
        db.create_tables()

        try:
            purged = db.purge_rejected_stale(days=REJECTED_RETENTION_DAYS)
            if purged["events_deleted"] or purged["email_submissions_deleted"]:
                logger.info(
                    "Alte abgelehnte Einträge gelöscht (≥%s Tage): %s",
                    REJECTED_RETENTION_DAYS,
                    purged,
                )
        except Exception as e:
            logger.warning("purge_rejected_stale: %s", e)

        n = await _run_email_screening_digest_to_telegram(
            flow_name="run_manual_email_flyer_collect"
        )
        converted = await process_approved_email_submissions(
            manual_revision_after_convert=True
        )
        sent_rev = await notify_telegram_first_round_for_new_events(converted)

        lines: List[str] = ["✅ E-Mail-/Flyer-Abruf fertig."]
        if n > 0:
            lines.append(
                f"📬 Digest: {n} Mail(s) — Spam pro Zeile ❌, dann „Alle übrigen freigeben“."
            )
        if converted:
            lines.append(
                f"📧 {len(converted)} freigegebene Mail(s) → Event(s) in der DB (ohne Auto-Post)."
            )
        if sent_rev > 0:
            lines.append(
                f"🎪 {sent_rev} Event(s) als „Neue Events zur Freigabe“ geschickt (gleiche Runde wie Portal/Menü)."
            )
        elif converted and getattr(telegram_bot, "disabled", False):
            lines.append("ℹ️ Telegram aus — Freigabe nur im Dashboard.")
        if n == 0 and not converted:
            lines.append(
                "Kein neuer Digest (keine passenden ungelesenen Mails). "
                "Freigegebene Mails wurden ggf. zu Events + Revision verarbeitet."
            )
        return "\n".join(lines)
    except Exception as e:
        logger.exception("run_manual_email_flyer_collect")
        return f"❌ Fehler: {e}"
    finally:
        db.close()


async def collect_and_approve_flow() -> None:
    """Neue Events sammeln, deduplizieren, speichern, Telegram-Batch senden."""
    logger.info("🚀 Starte Event-Sammlung …")
    logger.info(
        "Konfig: SCRAPERS_ENABLED=%s MOCK_MODE=%s EMAIL_SCREENING_ENABLED=%s",
        SCRAPERS_ENABLED,
        MOCK_MODE,
        EMAIL_SCREENING_ENABLED,
    )
    if not SCRAPERS_ENABLED:
        logger.info(
            "SCRAPERS_ENABLED=0 — keine Web-Portale; nur Formular/Mail/Dashboard-Pipeline."
        )
    try:
        db.connect()
        db.create_tables()

        try:
            purged = db.purge_rejected_stale(days=REJECTED_RETENTION_DAYS)
            if purged["events_deleted"] or purged["email_submissions_deleted"]:
                logger.info(
                    "Alte abgelehnte Einträge gelöscht (≥%s Tage): %s",
                    REJECTED_RETENTION_DAYS,
                    purged,
                )
        except Exception as e:
            logger.warning("purge_rejected_stale: %s", e)

        all_events: List[Dict[str, Any]] = []
        # MOCK_MODE mockt Claude/Meta, blockiert aber nicht die Netzwerk-Scraper.
        if SCRAPERS_ENABLED:
            all_events = collect_all_events()

        await _run_email_screening_digest_to_telegram(
            flow_name="collect_and_approve_flow"
        )

        # ==================== STANDARD EVENT-SAMMLUNG ====================
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
        # Wie Mail-Digest: Freigabe-Nachricht auch bei MOCK_MODE (Meta bleibt gemockt).
        if not getattr(telegram_bot, "disabled", False):
            await telegram_bot.send_events_for_approval(pending)
        logger.info("✅ Event-Sammlung abgeschlossen")

    except Exception as e:
        logger.exception(f"❌ Sammlung-Fehler: {e}")
        try:
            db.log_message("ERROR", str(e), {"flow": "collect_and_approve_flow"})
        except Exception:
            pass
    finally:
        db.close()

    # Approved Emails → Claude → Events (separater Schritt nach dem try/finally)
    await process_approved_email_submissions()


async def process_approved_email_submissions(
    *, manual_revision_after_convert: bool = False
) -> List[int]:
    """
    Verarbeitet freigegebene Email-Submissions:
    1. Anhänge zu Railway Storage speichern
    2. Claude: Post-Text + Bild-Analyse
    3. Als Event in DB speichern
    4. Optional: Auto-Freigabe / Meta (Cron)

    Bei manual_revision_after_convert=True (manueller Telegram-Mail-Abruf): keine
    Auto-Freigabe/Meta — Events bleiben für „Events zur Freigabe“ wie Portal-Events.

    Returns:
        Neu angelegte Event-IDs (Reihenfolge der Verarbeitung).
    """
    logger.info("📧 Verarbeite freigegebene Email-Submissions…")
    converted_event_ids: List[int] = []
    own_connection = False
    try:
        if db.conn is None:
            db.connect()
            own_connection = True
        approved_emails = db.get_approved_emails_pending_conversion()

        if not approved_emails:
            logger.info("📧 Keine freigegebenen Emails zur Verarbeitung")
            return converted_event_ids

        logger.info(f"📧 {len(approved_emails)} freigegebene Emails → Claude")

        if gmail_oauth_configured():
            email_handler.authenticate()

        did_auto_post = False
        for email in approved_emails:
            try:
                fresh = db.get_email_submission_by_id(int(email["id"]))
                if (
                    not fresh
                    or fresh.get("approval_status") != "approved"
                    or fresh.get("converted_to_event_id")
                ):
                    continue
                email = fresh

                # 1. Anhang herunterladen (erstes valides Bild)
                image_path = None
                attachment_urls = email.get("attachment_urls") or {}
                if isinstance(attachment_urls, str):
                    import json
                    attachment_urls = json.loads(attachment_urls)

                # Falls noch nicht gespeichert: aus Gmail laden
                if not attachment_urls:
                    msg_id = email.get("gmail_message_id")
                    attachments = email_handler._get_attachments_info(msg_id)
                    for att in attachments:
                        if att.get("attachment_id"):
                            path = email_handler.save_attachment_to_storage(
                                msg_id,
                                att["attachment_id"],
                                att["filename"]
                            )
                            if path:
                                attachment_urls[att["filename"]] = path
                                if not image_path and att.get("mime_type", "").startswith("image/"):
                                    image_path = path

                    # Speichere Attachment-URLs in DB
                    if attachment_urls:
                        import json as json_mod
                        if db.mode == "pg":
                            from psycopg2.extras import Json
                            with db.conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE email_submissions SET attachment_urls = %s WHERE id = %s",
                                    (Json(attachment_urls), email["id"])
                                )
                            db.conn.commit()
                        else:
                            with db.conn:
                                db.conn.execute(
                                    "UPDATE email_submissions SET attachment_urls = ? WHERE id = ?",
                                    (json_mod.dumps(attachment_urls), email["id"])
                                )
                else:
                    # Pfad aus gespeicherten URLs holen
                    for fname, path in attachment_urls.items():
                        if any(fname.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                            image_path = path
                            break

                # 2. Claude: Caption schreiben (Bild wird 1:1 als Flyer gepostet)
                caption = claude_handler.generate_caption_from_email(
                    body_text=email.get("body_text", ""),
                    subject=email.get("subject", ""),
                    image_path=image_path,
                )

                raw_image = image_path or (
                    list(attachment_urls.values())[0] if attachment_urls else ""
                )
                image_url = public_image_url(raw_image)

                # 3. In DB speichern
                event_id = db.add_event(
                    source="email_submission",
                    source_id=f"email-{email['id']}-{uuid.uuid4().hex[:8]}",
                    title=email.get("subject") or "Event",
                    description=email.get("body_text") or "",
                    image_url=image_url,
                    event_date="1970-01-01",
                    location="Gifhorn",
                    city="Gifhorn",
                    post_text=caption,
                )

                if event_id:
                    db.link_email_to_event(email["id"], event_id)
                    logger.info(f"📧 Email {email['id']} → Event {event_id} konvertiert")
                    converted_event_ids.append(int(event_id))

                    auto_approve = (
                        AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS
                        or AUTO_POST_AFTER_EMAIL_CONVERSION
                    )
                    if manual_revision_after_convert:
                        auto_approve = False

                    if auto_approve:
                        db.set_telegram_approval(event_id, approved=True)
                        logger.info(
                            "📧 Event %s automatisch für Social freigegeben (Email-Pipeline)",
                            event_id,
                        )

                    if (
                        not manual_revision_after_convert
                        and AUTO_POST_AFTER_EMAIL_CONVERSION
                        and image_url
                        and not str(image_url).startswith("http")
                    ):
                        logger.warning(
                            "AUTO_POST_AFTER_EMAIL_CONVERSION: image_url ist nicht öffentlich "
                            "(https). Setze PUBLIC_IMAGE_BASE_URL und /flyers im Dashboard — "
                            "Meta-Posting schlägt sonst fehl. Aktuell: %s",
                            image_url[:80],
                        )

                    # Standard: kein Telegram nach Mail→Event — Abend-Preview (--evening-preview).

                    if (
                        not manual_revision_after_convert
                        and AUTO_POST_AFTER_EMAIL_CONVERSION
                    ):
                        ev = db.get_event_by_id(event_id)
                        if ev:
                            meta_poster.batch_post(
                                [ev], platforms=["instagram", "facebook"]
                            )
                            did_auto_post = True

            except Exception as e:
                logger.error(f"❌ Fehler bei Email {email.get('id')}: {e}")

        logger.info("✅ Email-Verarbeitung abgeschlossen")

        if did_auto_post and not MOCK_MODE:
            try:
                gcal_sync.sync_events()
            except Exception as e:
                logger.warning("GCal Sync fehlgeschlagen: %s", e)

        return converted_event_ids

    except Exception as e:
        logger.exception(f"❌ process_approved_email_submissions Fehler: {e}")
        return converted_event_ids
    finally:
        if own_connection:
            db.close()


async def process_google_form_submissions() -> None:
    """
    Verarbeitet neue Google Form Responses:
    1. Sheets API polling → neue Responses lesen
    2. Parsen → Event-Dict
    3. Claude: Post-Text generieren
    4. DB: Event speichern
    5. Telegram: "Neue Form-Einreichung"
    """
    if not GOOGLE_FORM_SPREADSHEET_ID:
        logger.debug("GOOGLE_FORM_SPREADSHEET_ID nicht gesetzt; Google Forms deaktiviert")
        return

    logger.info("📋 Verarbeite Google Form Responses…")
    own_connection = False
    try:
        if db.conn is None:
            db.connect()
            own_connection = True

        # Authentifiziere Google Sheets
        if os.path.exists(GOOGLE_CREDENTIALS_FILE):
            google_form_handler.authenticate()

        # Lese neue Responses
        form_events = google_form_handler.get_new_responses()
        if not form_events:
            logger.info("📋 Keine neuen Google Form Responses")
            return

        logger.info(f"📋 {len(form_events)} neue Form-Responses → Claude")

        for event in form_events:
            try:
                # Deduplizierung
                if deduplicator.is_duplicate(event):
                    logger.info(f"⏭️ Event '{event['title']}' ist Duplikat; übersprungen")
                    continue

                # Claude: Post-Text
                post_text = claude_handler.generate_post_text(event)

                # DB: Event speichern
                event_id = db.add_event(
                    source=event["source"],
                    source_id=event["source_id"],
                    title=event["title"],
                    description=event["description"],
                    image_url=event.get("image_url", ""),
                    event_date=event["event_date"],
                    location=event["location"],
                    city=event["city"],
                    price_min=event.get("price_min"),
                    price_max=event.get("price_max"),
                    url=event.get("url", ""),
                    post_text=post_text,
                    contact_email=event.get("contact_email"),
                )

                if event_id:
                    logger.info(
                        f"✅ Form-Event gespeichert: '{event['title']}' "
                        f"(ID: {event_id}, Contact: {event.get('contact_email')})"
                    )

                    # Telegram: Benachrichtigung
                    await telegram_bot.send_message(
                        f"📋 *Neue Form-Einreichung*\n\n"
                        f"*{event['title']}*\n"
                        f"📅 {event['event_date']}\n"
                        f"📍 {event['location']}, {event['city']}\n"
                        f"👤 Kontakt: {event.get('contact_email', 'keine')}\n\n"
                        f"Überprüfe im Dashboard: /action/{event_id}/approve"
                    )
                else:
                    logger.warning(
                        f"⚠️ Form-Event konnte nicht gespeichert werden: "
                        f"'{event['title']}' (möglicherweise Duplikat)"
                    )

            except Exception as e:
                logger.error(f"❌ Fehler bei Form-Event '{event.get('title')}': {e}")

        logger.info("✅ Google Form-Verarbeitung abgeschlossen")

    except Exception as e:
        logger.exception(f"❌ process_google_form_submissions Fehler: {e}")
    finally:
        if own_connection:
            db.close()


async def evening_email_post_previews_flow() -> None:
    """
    Einmal täglich (abends, separater Cron): alle aus freigegebenen Mails erzeugten
    KI-Beiträge in einer (oder wenigen) Telegram-Nachrichten zur finalen Freigabe.
    """
    logger.info("🌆 Abend-Preview (Mail-Beiträge) …")
    own_connection = False
    try:
        if db.conn is None:
            db.connect()
            own_connection = True
        db.create_tables()
        berlin_day = datetime.now(ZoneInfo("Europe/Berlin")).date()
        events = db.get_email_derived_events_for_evening_preview(berlin_day)
        if not events:
            logger.info(
                "Keine Mail-Beiträge für Abend-Preview (Berlin-Datum %s)", berlin_day
            )
            return
        ids = await telegram_bot.send_evening_email_posts_batch(events)
        if ids:
            db.mark_evening_preview_sent(ids)
        logger.info("Abend-Preview: %s Beiträge an Telegram gesendet", len(ids))
    except Exception as e:
        logger.exception("Abend-Preview-Fehler: %s", e)
    finally:
        if own_connection:
            db.close()


async def post_approved_events() -> None:
    """Freigegebene Events auf Instagram/Facebook posten."""
    logger.info("Starte Meta-Posting …")
    try:
        db.connect()
        db.create_tables()
        try:
            purged = db.purge_rejected_stale(days=REJECTED_RETENTION_DAYS)
            if purged["events_deleted"] or purged["email_submissions_deleted"]:
                logger.info(
                    "Alte abgelehnte Einträge gelöscht (≥%s Tage): %s",
                    REJECTED_RETENTION_DAYS,
                    purged,
                )
        except Exception as e:
            logger.warning("purge_rejected_stale: %s", e)

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
