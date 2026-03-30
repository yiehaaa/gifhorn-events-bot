"""
Telegram: Sammelnachricht mit Inline-Buttons zur Freigabe (vor Meta-Posting).
Callbacks laufen im Polling-Prozess; Freigaben in der DB (approved_for_social).
"""

from __future__ import annotations

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
                "Tägliche Sammelnachricht mit Freigabe per Button.\n"
                "Stelle sicher, dass dieser Prozess mit `python telegram_bot.py` "
                "läuft, damit Klicks ankommen."
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
        """Ein Callback für approve_* / reject_*."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        parts = query.data.split("_", 1)
        if len(parts) != 2:
            return
        action, sid = parts[0], parts[1]
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

    def setup_handlers(self, application: Application) -> None:
        if self.disabled:
            return
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^(approve|reject)_\d+$"))


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
