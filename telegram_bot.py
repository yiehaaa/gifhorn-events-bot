"""
Telegram: Sammelnachricht mit Inline-Buttons zur Freigabe (vor Meta-Posting).
Callbacks laufen im Polling-Prozess; Freigaben in der DB (approved_for_social).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from claude_handler import claude_handler
from config import MOCK_MODE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import db

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self) -> None:
        self.disabled = MOCK_MODE or (not TELEGRAM_BOT_TOKEN) or (not TELEGRAM_CHAT_ID)
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.disabled:
            return
        if update.message:
            await update.message.reply_text(
                "👋 Gifhorn Events Bot\n"
                "Mail-Digest: Spam pro Zeile mit ❌ ablehnen, dann „Alle übrigen freigeben“.\n"
                "Später: KI-Beiträge (21 Uhr per Cron) freigeben.\n"
                "Läuft mit: python telegram_bot.py"
            )

    async def send_daily_email_digest(
        self, emails: List[Dict[str, Any]], batch_hex: str
    ) -> None:
        """
        Einmal pro Lauf: alle neuen Mails in einer Nachricht + Batch-Freigabe.
        batch_hex: 32 Zeichen (uuid.hex), steht in DB ingest_batch_id.
        """
        if self.disabled:
            logger.info("Telegram ist deaktiviert (MOCK_MODE oder Keys fehlen).")
            return
        if not emails or len(batch_hex) != 32:
            logger.info("Keine neuen Email-Submissions für Telegram-Digest")
            return

        bot = Bot(self.bot_token)
        lines: List[str] = [
            "📬 Neue Einreichungs-Mails",
            f"Anzahl: {len(emails)}",
            "",
            "1) Spam? Pro Mail die ❌-Taste (nur diese werden verworfen).",
            "2) Danach: „Alle übrigen freigeben“ — nur nicht abgelehnte gehen an die KI.",
            "3) Gegen 21 Uhr (Cron): Vorschau der Beiträge zur finalen Freigabe.",
            "",
        ]

        keyboard: List[List[InlineKeyboardButton]] = []

        for i, email in enumerate(emails, start=1):
            sender = str(email.get("sender", "Unknown"))[:120]
            subject = str(email.get("subject", "N/A"))[:200]
            body_snippet = str(email.get("body", ""))[:120]
            if len(str(email.get("body", ""))) > 120:
                body_snippet += "…"
            att = email.get("attachments") or []
            att_note = f" | 📎 {len(att)} Anhang" if att else ""
            score = email.get("screening_score", 0) or 0
            try:
                sc = float(score)
            except (TypeError, ValueError):
                sc = 0.0
            lines.append(f"{i}. {subject}")
            lines.append(f"   Von: {sender}{att_note} | Score: {sc:.0%}")
            if body_snippet.strip():
                lines.append(f"   {body_snippet}")
            lines.append("")

            db_id = email.get("db_submission_id")
            if db_id is not None:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"❌ #{i} als Spam",
                            callback_data=f"emspam_{int(db_id)}",
                        )
                    ]
                )

        lines.append("🖼 Flyer aus der Mail = später das einzige Post-Bild (plus KI-Caption).")

        message_text = "\n".join(lines)
        if len(message_text) > 3800:
            message_text = message_text[:3790] + "\n… (gekürzt)"

        keyboard.append(
            [
                InlineKeyboardButton(
                    "✅ Alle übrigen freigeben",
                    callback_data=f"email_bok_{batch_hex}",
                ),
            ]
        )
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=self.chat_id,
            text=message_text,
            reply_markup=reply_markup,
        )
        logger.info("📧 Täglicher Mail-Digest gesendet (%s Mails)", len(emails))

    async def send_evening_email_posts_batch(
        self, events: List[Dict[str, Any]]
    ) -> List[int]:
        """
        Abend-Übersicht: alle aus Mails erzeugten Beiträge mit Freigabe-Buttons.
        Liefert die Event-IDs, die in der (den) Nachrichten vorkommen (für DB-Flag).
        """
        if self.disabled:
            return []
        if not events:
            return []

        bot = Bot(self.bot_token)
        max_events = 12
        chunk = events[:max_events]
        included_ids: List[int] = []

        lines: List[str] = [
            "🌆 Beiträge aus Einreichungs-Mails (21 Uhr)",
            "",
            "Bild = Flyer aus der Mail; Text = KI-Caption. Pro Zeile freigeben oder verwerfen.",
            "",
        ]
        keyboard: List[List[InlineKeyboardButton]] = []

        for event in chunk:
            eid = int(event["id"])
            included_ids.append(eid)
            title = str(event.get("title", "Event"))[:100]
            preview = str(event.get("post_text", ""))[:200]
            if len(str(event.get("post_text", ""))) > 200:
                preview += "…"
            lines.append(f"— {title} —")
            lines.append(preview)
            lines.append("")
            short = title[:22] + ("…" if len(title) > 22 else "")
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✅ {short}",
                        callback_data=f"approve_{eid}",
                    ),
                    InlineKeyboardButton("❌", callback_data=f"reject_{eid}"),
                ]
            )

        if len(events) > max_events:
            lines.append(f"… und {len(events) - max_events} weitere im Dashboard.")

        message_text = "\n".join(lines)
        if len(message_text) > 4000:
            message_text = message_text[:3990] + "\n…"

        await bot.send_message(
            chat_id=self.chat_id,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        logger.info("🌆 Abend-Preview gesendet (%s Beiträge)", len(chunk))
        return included_ids

    async def send_info_message(self, text: str) -> None:
        """Kurze Info ohne Buttons (z. B. Auto-Freigabe nach Email-Pipeline)."""
        if self.disabled:
            return
        bot = Bot(self.bot_token)
        await bot.send_message(
            chat_id=self.chat_id,
            text=text[:4090],
        )

    async def send_events_for_approval(self, events: List[Dict[str, Any]]) -> None:
        """Sendet einen Batch zur Freigabe (z. B. aus dem Cron / main)."""
        if self.disabled:
            logger.info("Telegram ist deaktiviert (MOCK_MODE oder Keys fehlen).")
            return
        if not events:
            logger.info("Keine neuen Events für Telegram")
            return

        for event in events:
            if not event.get("post_text"):
                event["post_text"] = claude_handler.generate_post_text(event)

        lines: List[str] = ["🎪 Neue Events zur Freigabe", ""]
        keyboard: List[List[InlineKeyboardButton]] = []

        for event in events[:10]:
            title = str(event.get("title", "Event"))
            loc = event.get("location", "N/A")
            city = event.get("city", "N/A")
            ed = event.get("event_date", "N/A")
            pmin = event.get("price_min", "?")
            pmax = event.get("price_max", "?")
            preview = str(event.get("post_text", ""))[:150]
            eid = event["id"]

            lines.append(title)
            lines.append(f"📍 {loc} ({city})")
            lines.append(f"📅 {ed}")
            lines.append(f"💰 {pmin}–{pmax} €")
            lines.append("")
            lines.append("📝 Post (Auszug):")
            lines.append(f"{preview}…")
            lines.append("")

            short = title[:24] + ("…" if len(title) > 24 else "")
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✅ {short}",
                        callback_data=f"approve_{eid}",
                    ),
                    InlineKeyboardButton("❌", callback_data=f"reject_{eid}"),
                ]
            )

        message_text = "\n".join(lines)
        reply_markup = InlineKeyboardMarkup(keyboard)

        bot = Bot(self.bot_token)
        await bot.send_message(
            chat_id=self.chat_id,
            text=message_text,
            reply_markup=reply_markup,
        )
        logger.info("%s Events zur Freigabe gesendet", len(events[:10]))

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Callback-Handler für beide:
        - approve_* / reject_* (Events)
        - email_approve_* / email_reject_* (Emails)
        """
        query = update.callback_query
        if not query or not query.data:
            return

        data = query.data or ""
        # Einzelne Mail als Spam (vor „Alle übrigen freigeben“)
        if data.startswith("emspam_"):
            try:
                sub_id = int(data[7:])
            except ValueError:
                await query.answer("Ungültig.", show_alert=True)
                return
            await self._handle_single_email_spam_reject(sub_id, query)
            return

        await query.answer()

        # Alle noch pending Mails dieser Batch freigeben (ohne zuvor ❌ Spam)
        if data.startswith("email_bok_") and len(data) == 42:
            await self._handle_email_batch_confirm(data[10:], query)
            return

        # Parse callback_data: "approve_123" / "reject_123"
        parts = data.rsplit("_", 1)
        if len(parts) != 2:
            return

        action_with_type = parts[0]
        sid = parts[1]

        await self._handle_event_callback(action_with_type, sid, query)

    async def _handle_event_callback(
        self, action: str, sid: str, query: Any
    ) -> None:
        """Handhabe Event-Approvals"""
        try:
            event_id = int(sid)
        except ValueError:
            await query.edit_message_text(text="❌ Ungültige Auswahl.")
            return

        if not db.conn:
            db.connect()
        row = db.get_event_by_id(event_id)
        if not row:
            await query.edit_message_text(text="❌ Event nicht gefunden.")
            return

        title = row.get("title", "")

        if action == "approve":
            db.set_telegram_approval(event_id, approved=True)
            await query.edit_message_text(text=f"✅ Freigegeben: {title}")
            logger.info("Telegram freigegeben: %s (id=%s)", title, event_id)
        elif action == "reject":
            db.set_telegram_approval(event_id, approved=False)
            await query.edit_message_text(text=f"❌ Verworfen: {title}")
            logger.info("Telegram verworfen: %s (id=%s)", title, event_id)

    async def _handle_single_email_spam_reject(self, submission_id: int, query: Any) -> None:
        """Eine Mail aus dem Digest als Spam/unerwünscht markieren."""
        if not db.conn:
            db.connect()
        row = db.get_email_submission_by_id(submission_id)
        if not row:
            await query.answer("Mail nicht gefunden.", show_alert=True)
            return
        if (row.get("approval_status") or "pending") != "pending":
            await query.answer("Bereits erledigt.", show_alert=True)
            return
        subj = str(row.get("subject", ""))[:40]
        db.set_email_approval(submission_id, approved=False, approved_by="telegram_spam")
        await query.answer(f"#{submission_id}: nicht übernommen")
        logger.info("📧 Mail als Spam verworfen: id=%s %s", submission_id, subj)

    async def _handle_email_batch_confirm(self, batch_hex: str, query: Any) -> None:
        """Freigabe aller noch pending Mails dieser Batch (ohne zuvor als Spam ❌)."""
        if len(batch_hex) != 32 or any(
            c not in "0123456789abcdef" for c in batch_hex.lower()
        ):
            await query.edit_message_text(text="❌ Ungültige Batch-ID.")
            return

        if not db.conn:
            db.connect()

        n = db.approve_email_submissions_by_batch(batch_hex, approved_by="telegram")
        await query.edit_message_text(
            text=f"✅ {n} Mail(s) freigegeben (alle, die du nicht mit ❌ verworfen hast). "
            "KI läuft jetzt — um 21 Uhr die Beitrags-Vorschau per Cron."
        )
        logger.info("📧 Batch freigegeben: %s Mails (batch=%s…)", n, batch_hex[:8])

        if n > 0:

            async def _run_conversion() -> None:
                try:
                    from main import process_approved_email_submissions

                    await process_approved_email_submissions()
                except Exception:
                    logger.exception(
                        "Email-Konvertierung nach Batch-Freigabe fehlgeschlagen"
                    )

            asyncio.create_task(_run_conversion())

    def setup_handlers(self, application: Application) -> None:
        if self.disabled:
            return
        application.add_handler(CommandHandler("start", self.start))
        # Handler für Event-Callbacks: approve_ID, reject_ID
        application.add_handler(
            CallbackQueryHandler(
                self.on_callback,
                pattern=r"^(approve|reject)_\d+$|^email_bok_[a-fA-F0-9]{32}$|^emspam_\d+$",
            )
        )


telegram_bot = TelegramBot()


def run_polling() -> None:
    """Separater Prozess: empfängt Button-Klicks (Polling)."""
    if telegram_bot.disabled:
        logger.info("Telegram Polling abgebrochen: Telegram ist deaktiviert (MOCK_MODE/Keys fehlend).")
        return
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    db.connect()
    db.create_tables()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )
    telegram_bot.setup_handlers(application)
    logger.info("Telegram Polling startet …")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_polling()
