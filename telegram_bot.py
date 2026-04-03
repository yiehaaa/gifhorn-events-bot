"""
Telegram: Sammelnachricht mit Inline-Buttons zur Freigabe (vor Meta-Posting).
Callbacks laufen im Polling-Prozess; Freigaben in der DB (approved_for_social).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from claude_handler import claude_handler
from config import (
    DASHBOARD_URL,
    EMAIL_ATTACHMENT_STORAGE_PATH,
    FORM_URL,
    PUBLIC_IMAGE_BASE_URL,
    REFRESH_FLYER_SECRET,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    public_image_url,
)
from database import db

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self) -> None:
        # MOCK_MODE blockiert Meta/Claude-Pflichtkeys, nicht den Telegram-Freigabe-Chat.
        tok = (TELEGRAM_BOT_TOKEN or "").strip()
        cid_raw = (TELEGRAM_CHAT_ID or "").strip()
        self.bot_token: Optional[str] = tok or None
        self.chat_id: Optional[int] = None
        self.disabled = (not self.bot_token) or (not cid_raw)
        if not self.disabled:
            try:
                self.chat_id = int(cid_raw)
            except ValueError:
                logger.error(
                    "TELEGRAM_CHAT_ID ist keine Ganzzahl (nach strip): %r — Telegram deaktiviert.",
                    cid_raw[:48],
                )
                self.disabled = True
                self.chat_id = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.disabled:
            return
        if update.message:
            # Infotext und Menü getrennt: Manche Clients zeigen Inline-Keyboards
            # zuverlässiger, wenn es eine eigene kurze Nachricht ist.
            await update.message.reply_text(
                "👋 Gifhorn Events Bot\n"
                "Mail-Digest: Spam pro Zeile mit ❌ ablehnen, dann „Alle übrigen freigeben“.\n"
                "Neue Mails aus Gmail: täglich ~19 Uhr (Cron) oder Menü „E-Mail-Flyer abrufen“ / /emailabruf.\n"
                "KI-Beiträge: ~21 Uhr (Cron) freigeben.\n"
                "Läuft mit: python telegram_bot.py",
            )
            await update.message.reply_text(
                "📋 Menü — bitte einen Button wählen:",
                reply_markup=self._menu_keyboard(),
            )

    async def cmd_emailabruf(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Gleiche Pipeline wie ~19-Uhr-Collect: Gmail → Digest → ggf. freigegebene Mails verarbeiten."""
        if self.disabled or not update.message:
            return
        if self.chat_id is not None and update.message.chat_id != self.chat_id:
            await update.message.reply_text("Nur im Freigabe-Chat.")
            return
        await update.message.reply_text(
            "📧 E-Mail-/Flyer-Abruf gestartet — Ergebnis folgt."
        )
        bot = Bot(self.bot_token)
        chat = self.chat_id

        async def _run_manual_email_collect() -> None:
            try:
                from main import run_manual_email_flyer_collect

                msg = await run_manual_email_flyer_collect()
                await bot.send_message(chat_id=chat, text=msg[:3900])
            except Exception as exc:
                logger.exception("Manueller E-Mail-/Flyer-Abruf (/emailabruf)")
                await bot.send_message(
                    chat_id=chat,
                    text=f"❌ E-Mail-/Flyer-Abruf fehlgeschlagen: {exc}"[:3900],
                )

        asyncio.create_task(_run_manual_email_collect())

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Explizites Menu-Kommando für On-Demand-Revision."""
        if self.disabled or not update.message:
            return
        await update.message.reply_text("📋 Revision-Menü")
        await update.message.reply_text(
            "Bitte einen Button wählen:",
            reply_markup=self._menu_keyboard(),
        )

    def _menu_keyboard(self) -> InlineKeyboardMarkup:
        # Telegram: Inline-Button-Text max. 64 Zeichen; kurz halten.
        dashboard_url = self._dashboard_url()
        form_url = self._form_url(dashboard_url)
        rows: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "📥 Events zur Revision",
                    callback_data="menu_incoming_events",
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 Erstellte Beiträge zur Revision",
                    callback_data="menu_created_posts",
                )
            ],
            [
                InlineKeyboardButton(
                    "📧 E-Mail-Flyer abrufen",
                    callback_data="menu_email_flyer_collect",
                )
            ],
        ]
        if dashboard_url:
            rows.append([InlineKeyboardButton("🌐 Dashboard öffnen", url=dashboard_url)])
        if form_url:
            rows.append([InlineKeyboardButton("📝 Formular öffnen", url=form_url)])
        return InlineKeyboardMarkup(
            rows
        )

    @staticmethod
    def _ensure_https(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        if u.startswith(("http://", "https://")):
            return u
        return f"https://{u}"

    def _dashboard_url(self) -> str:
        direct = os.getenv("DASHBOARD_PUBLIC_URL", "").strip()
        if direct:
            return self._ensure_https(direct.rstrip("/"))

        railway_dash = os.getenv("RAILWAY_SERVICE_GIFHORN_DASHBOARD_URL", "").strip()
        if railway_dash:
            return self._ensure_https(railway_dash.rstrip("/"))

        base = (PUBLIC_IMAGE_BASE_URL or "").strip().rstrip("/")
        if base.endswith("/flyers"):
            return base[: -len("/flyers")]
        if base:
            return base

        dash_cfg = (DASHBOARD_URL or "").strip()
        if dash_cfg and "localhost" not in dash_cfg and "127.0.0.1" not in dash_cfg:
            return self._ensure_https(dash_cfg.rstrip("/"))
        return ""

    def _form_url(self, dashboard_url: str) -> str:
        form = (FORM_URL or "").strip()
        if form and "localhost" not in form and "127.0.0.1" not in form:
            return self._ensure_https(form)
        if dashboard_url:
            return f"{dashboard_url}/form/event"
        return ""

    def _flyer_refresh_base_url(self) -> str:
        """Basis-URL des Dashboards für POST /internal/refresh-flyer/…"""
        internal = os.getenv("DASHBOARD_INTERNAL_BASE_URL", "").strip()
        if internal:
            return self._ensure_https(internal.rstrip("/"))
        return self._dashboard_url()

    async def _maybe_refresh_flyer_for_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formular-Events ohne manuellen Flyer: vor der Vorschau neu rendern,
        damit Telegram die aktuelle HTML-Vorlage (neuer Dateiname) nutzt.
        """
        if not REFRESH_FLYER_SECRET:
            return event
        src = (event.get("source") or "").strip()
        if src not in ("web_form", "web", "web_submit"):
            return event
        auto = event.get("flyer_auto_generated")
        if auto is False or auto == 0:
            return event
        raw_img = str(event.get("image_url") or "")
        ext = Path(raw_img).suffix.lower()
        if ext in (".jpg", ".jpeg", ".webp", ".gif"):
            return event
        base = self._flyer_refresh_base_url()
        if not base:
            return event
        eid = int(event["id"])
        url = f"{base}/internal/refresh-flyer/{eid}"
        try:
            import httpx

            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    url,
                    headers={"X-Internal-Token": REFRESH_FLYER_SECRET},
                )
            if r.status_code != 200:
                logger.warning(
                    "refresh-flyer HTTP %s für event_id=%s",
                    r.status_code,
                    eid,
                )
                return event
            data = r.json()
            if data.get("ok") and data.get("image_url"):
                out = dict(event)
                out["image_url"] = data["image_url"]
                return out
        except Exception:
            logger.exception("refresh-flyer fehlgeschlagen (event_id=%s)", eid)
        return event

    @staticmethod
    def _format_price_label(event: Dict[str, Any]) -> str:
        """Normalize empty/zero prices to a friendlier text."""
        pmin = event.get("price_min")
        pmax = event.get("price_max")

        def _to_float(value: Any) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        min_value = _to_float(pmin)
        max_value = _to_float(pmax)
        if (min_value in (None, 0.0)) and (max_value in (None, 0.0)):
            return "Eintritt frei!"
        if min_value is not None and max_value is not None:
            return f"{min_value:g}–{max_value:g} €"
        if min_value is not None:
            return f"ab {min_value:g} €"
        if max_value is not None:
            return f"bis {max_value:g} €"
        return "Eintritt frei!"

    async def _handle_menu_callback(self, data: str, query: Any) -> bool:
        """On-demand Menueaktionen; gibt True zurueck, wenn verarbeitet."""
        if data not in {
            "menu_incoming_events",
            "menu_created_posts",
            "menu_email_flyer_collect",
        }:
            return False

        if self.chat_id is not None and query.message and query.message.chat_id != self.chat_id:
            await query.answer("Nur im konfigurierten Freigabe-Chat.", show_alert=True)
            return True

        if data != "menu_email_flyer_collect":
            if not db.conn:
                db.connect()
                db.create_tables()

        await query.answer()

        if data == "menu_email_flyer_collect":
            await query.edit_message_text(
                "📧 E-Mail-/Flyer-Abruf gestartet — Ergebnis folgt als neue Nachricht."
            )
            bot = Bot(self.bot_token)
            chat = self.chat_id

            async def _run_manual_email_collect() -> None:
                try:
                    from main import run_manual_email_flyer_collect

                    msg = await run_manual_email_flyer_collect()
                    await bot.send_message(chat_id=chat, text=msg[:3900])
                except Exception as exc:
                    logger.exception("Manueller E-Mail-/Flyer-Abruf (Menü)")
                    await bot.send_message(
                        chat_id=chat,
                        text=f"❌ E-Mail-/Flyer-Abruf fehlgeschlagen: {exc}"[:3900],
                    )

            asyncio.create_task(_run_manual_email_collect())
            return True

        if data == "menu_incoming_events":
            events = db.get_events_awaiting_telegram()
            if not events:
                await query.edit_message_text(
                    "📥 Aktuell keine eingegangenen Events zur Revision."
                )
                return True
            await self.send_events_for_approval(events)
            await query.edit_message_text(
                f"📥 {len(events[:10])} Event(s) zur Revision gesendet ({datetime.now().strftime('%H:%M')})."
            )
            return True

        # menu_created_posts
        from zoneinfo import ZoneInfo

        berlin_day = datetime.now(ZoneInfo("Europe/Berlin")).date()
        events = db.get_email_derived_events_for_evening_preview(berlin_day)
        if not events:
            await query.edit_message_text(
                "📝 Aktuell keine erstellten Beitraege zur Revision."
            )
            return True

        await self.send_evening_email_posts_batch(events)
        await query.edit_message_text(
            f"📝 {len(events[:12])} Beitrag(e) zur Revision gesendet ({datetime.now().strftime('%H:%M')})."
        )
        return True

    async def send_daily_email_digest(
        self, emails: List[Dict[str, Any]], batch_hex: str
    ) -> None:
        """
        Einmal pro Lauf: alle neuen Mails in einer Nachricht + Batch-Freigabe.
        batch_hex: 32 Zeichen (uuid.hex), steht in DB ingest_batch_id.
        """
        if self.disabled:
            logger.info("Telegram ist deaktiviert (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen).")
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

        await bot.send_message(
            chat_id=self.chat_id,
            text=(
                "🌆 Erstellte Beiträge zur Revision\n\n"
                "Quelle: Mail (KI-Caption + Mail-Flyer) und freigegebene Form-Events.\n"
                "Du bekommst pro Beitrag nur das Bild mit ✅/❌."
            ),
        )

        for event in chunk:
            event = await self._maybe_refresh_flyer_for_event(event)
            eid = int(event["id"])
            included_ids.append(eid)
            title = str(event.get("title", "Event"))[:100]
            preview = str(event.get("post_text", ""))[:200]
            if len(str(event.get("post_text", ""))) > 200:
                preview += "…"
            short = title[:22] + ("…" if len(title) > 22 else "")
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"✅ {short}",
                            callback_data=f"approve_{eid}",
                        ),
                        InlineKeyboardButton("❌", callback_data=f"reject_{eid}"),
                        InlineKeyboardButton("🔄", callback_data=f"reset_{eid}"),
                    ]
                ]
            )
            raw_image = str(event.get("image_url") or "")
            image_url = public_image_url(raw_image)
            has_public_image = image_url.startswith(("http://", "https://"))

            if has_public_image:
                try:
                    await bot.send_photo(
                        chat_id=self.chat_id,
                        photo=image_url,
                        reply_markup=reply_markup,
                    )
                    continue
                except Exception:
                    logger.exception(
                        "Bildvorschau fehlgeschlagen, fallback auf Text (event_id=%s)",
                        eid,
                    )

            local_image = self._resolve_local_image_path(raw_image)
            if local_image and local_image.is_file():
                try:
                    with local_image.open("rb") as fh:
                        await bot.send_photo(
                            chat_id=self.chat_id,
                            photo=fh,
                            reply_markup=reply_markup,
                        )
                    continue
                except Exception:
                    logger.exception(
                        "Lokale Bildvorschau fehlgeschlagen, fallback auf Text (event_id=%s)",
                        eid,
                    )

            try:
                fallback_image = self._build_fallback_preview_image(event)
                await bot.send_photo(
                    chat_id=self.chat_id,
                    photo=fallback_image,
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.exception("Fallback-Bild konnte nicht erzeugt/gesendet werden (event_id=%s)", eid)

        if len(events) > max_events:
            await bot.send_message(
                chat_id=self.chat_id,
                text=f"… und {len(events) - max_events} weitere im Dashboard.",
            )
        logger.info("🌆 Abend-Preview gesendet (%s Beiträge)", len(chunk))
        return included_ids

    @staticmethod
    def _resolve_local_image_path(raw_image: str) -> Path | None:
        if not raw_image:
            return None
        s = raw_image.strip()
        if not s:
            return None
        if s.startswith(("http://", "https://")):
            return None
        if s.startswith("/flyers/"):
            return Path(EMAIL_ATTACHMENT_STORAGE_PATH) / Path(s).name
        p = Path(s)
        if p.is_absolute():
            return p
        return Path(EMAIL_ATTACHMENT_STORAGE_PATH) / p.name

    @staticmethod
    def _build_fallback_preview_image(event: Dict[str, Any]) -> BytesIO:
        """Build a minimal readable fallback image if source file/url is unavailable."""
        from PIL import Image, ImageDraw, ImageFont

        width, height = 1080, 1350
        img = Image.new("RGB", (width, height), color=(18, 22, 35))
        draw = ImageDraw.Draw(img)

        def _font(size: int):
            for candidate in (
                "DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            ):
                try:
                    return ImageFont.truetype(candidate, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        title = str(event.get("title") or "Veranstaltung")
        date_text = str(event.get("event_date") or "").strip()
        location = str(event.get("location") or "").strip()
        city = str(event.get("city") or "").strip()
        place = f"{location} ({city})" if city and city not in location else (location or city)

        draw.rounded_rectangle((60, 70, 1020, 1280), radius=36, fill=(25, 31, 50))
        draw.text((100, 120), "BILD NICHT VERFUEGBAR", fill=(139, 162, 255), font=_font(34))
        y = 220
        for line in title.split("\n"):
            for part in [line[i : i + 20] for i in range(0, len(line), 20)][:4]:
                draw.text((100, y), part, fill=(244, 248, 255), font=_font(82))
                y += 90
        y += 20
        if date_text:
            draw.text((100, y), date_text[:70], fill=(203, 215, 255), font=_font(44))
            y += 64
        if place:
            draw.text((100, y), place[:70], fill=(203, 215, 255), font=_font(44))

        out = BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out

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
            logger.info("Telegram ist deaktiviert (TELEGRAM_* fehlen).")
            return
        if not events:
            logger.info("Keine neuen Events für Telegram")
            return

        for event in events:
            if not str(event.get("post_text") or "").strip():
                event["post_text"] = claude_handler.generate_post_text(event)

        lines: List[str] = ["🎪 Neue Events zur Freigabe", ""]
        keyboard: List[List[InlineKeyboardButton]] = []

        for event in events[:10]:
            title = str(event.get("title", "Event"))
            loc = event.get("location", "N/A")
            city = event.get("city", "N/A")
            ed = event.get("event_date", "N/A")
            preview = str(event.get("post_text", ""))[:150]
            try:
                eid = int(event["id"])
            except (TypeError, ValueError) as exc:
                logger.error("Event ohne gültige id: %s", exc)
                continue
            price_label = self._format_price_label(event)

            lines.append(title)
            lines.append(f"📍 {loc} ({city})")
            lines.append(f"📅 {ed}")
            lines.append(f"💰 {price_label}")
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
                    InlineKeyboardButton("🔄", callback_data=f"reset_{eid}"),
                ]
            )

        if not keyboard:
            logger.error("send_events_for_approval: Batch ohne gültige Event-IDs")
            return

        message_text = "\n".join(lines)
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # PTB 20+: expliziter Kontext stellt HTTP-Client korrekt ein (sonst sporadisch leere Fehler).
            async with Bot(self.bot_token) as bot:
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
            logger.info("%s Events zur Freigabe gesendet", len(events[:10]))
        except TelegramError as exc:
            logger.error(
                "Telegram send_events_for_approval fehlgeschlagen: %s (chat_id=%s)",
                exc,
                self.chat_id,
            )

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Callback-Handler für beide:
        - approve_* / reject_* (Events)
        - email_bok_* / emspam_* (Mail-Digest)
        """
        query = update.callback_query
        if not query:
            return

        data = (query.data or "").strip()
        if not data:
            await query.answer("Leere Auswahl.", show_alert=True)
            return

        callback_answered = False
        try:
            # Menueaktionen (on-demand Abrufe)
            if await self._handle_menu_callback(data, query):
                return

            # Einzelne Mail als Spam (vor „Alle übrigen freigeben“)
            if data.startswith("emspam_"):
                try:
                    sub_id = int(data[7:])
                except ValueError:
                    await query.answer("Ungültig.", show_alert=True)
                    return
                await self._handle_single_email_spam_reject(sub_id, query)
                return

            # Loading sofort beenden (sonst bleibt „Lädt…“ hängen)
            await query.answer()
            callback_answered = True

            # Alle noch pending Mails dieser Batch freigeben
            if data.startswith("email_bok_"):
                batch_hex = data[len("email_bok_") :]
                if len(batch_hex) == 32:
                    await self._handle_email_batch_confirm(batch_hex, query)
                else:
                    await query.edit_message_text(
                        text=f"❌ Ungültige Batch-ID (Länge {len(batch_hex)}, erwartet 32)."
                    )
                return

            # Parse callback_data: "approve_123" / "reject_123"
            parts = data.rsplit("_", 1)
            if len(parts) != 2:
                logger.warning("Unbekannter Callback: %s", data[:80])
                return

            action_with_type = parts[0]
            sid = parts[1]

            await self._handle_event_callback(action_with_type, sid, query)
        except Exception:
            logger.exception("Telegram on_callback data=%r", data[:100])
            if not callback_answered:
                try:
                    await query.answer(
                        "Interner Fehler — Bot-Log prüfen, Bot neu starten.",
                        show_alert=True,
                    )
                except Exception:
                    pass

    async def _edit_callback_feedback(self, query: Any, text: str) -> None:
        """
        Nach Inline-Button: Telegram unterscheidet Text- vs. Medien-Nachrichten.
        Bei Fotos schlägt edit_message_text fehl → Nutzer sieht endlos „Lädt…“ ohne Feedback.
        """
        msg = query.message
        if msg is None:
            return
        cap = text[:1024]
        try:
            if msg.photo:
                await query.edit_message_caption(caption=cap, reply_markup=None)
            elif msg.document and not (msg.text or "").strip():
                await query.edit_message_caption(caption=cap, reply_markup=None)
            else:
                await query.edit_message_text(text=cap, reply_markup=None)
        except TelegramError as exc:
            logger.warning("Telegram Nachricht nach Callback nicht editierbar: %s", exc)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except TelegramError:
                pass
            try:
                await query.answer(cap[:180], show_alert=True)
            except TelegramError:
                pass

    async def _handle_event_callback(
        self, action: str, sid: str, query: Any
    ) -> None:
        """Handhabe Event-Approvals"""
        try:
            event_id = int(sid)
        except ValueError:
            await self._edit_callback_feedback(query, "❌ Ungültige Auswahl.")
            return

        if not db.conn:
            db.connect()
        row = db.get_event_by_id(event_id)
        if not row:
            await self._edit_callback_feedback(query, "❌ Event nicht gefunden.")
            return

        title = str(row.get("title") or "")

        if action == "approve":
            db.set_telegram_approval(event_id, approved=True)
            await self._edit_callback_feedback(query, f"✅ Freigegeben: {title}")
            logger.info("Telegram freigegeben: %s (id=%s)", title, event_id)
        elif action == "reject":
            db.set_telegram_approval(event_id, approved=False)
            await self._edit_callback_feedback(query, f"❌ Verworfen: {title}")
            logger.info("Telegram verworfen: %s (id=%s)", title, event_id)
        elif action == "reset":
            db.reset_event_for_regeneration(event_id)
            await self._edit_callback_feedback(
                query,
                f"🔄 Zurückgesetzt: {title}\nWird in der nächsten Runde neu generiert.",
            )
            logger.info("Telegram zurückgesetzt: %s (id=%s)", title, event_id)

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
        if n == 0:
            logger.warning(
                "Batch-Freigabe: 0 Zeilen (falsche DB oder Batch schon erledigt?). batch=%s…",
                batch_hex[:8],
            )
            await query.edit_message_text(
                text=(
                    "⚠️ Keine pending Mails in der Datenbank für diesen Batch.\n\n"
                    "Typisch: `telegram_bot.py` und `worker.py` müssen dieselbe SQLite-Datei "
                    "nutzen (ab jetzt: Pfad fest zum Repo-Root). "
                    "Bot neu starten und nochmal „Freigeben“ — oder Batch erneut per Collect erzeugen."
                )
            )
            return

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
        application.add_handler(CommandHandler("menu", self.menu))
        application.add_handler(CommandHandler("emailabruf", self.cmd_emailabruf))
        # Kein Regex-Filter: In PTB 21 kann ein zu strenges Pattern Callbacks verwerfen
        # → Telegram zeigt endlos „Lädt…“, weil answer() nie aufgerufen wird.
        application.add_handler(CallbackQueryHandler(self.on_callback))


telegram_bot = TelegramBot()


def run_polling() -> None:
    """Separater Prozess: empfängt Button-Klicks (Polling)."""
    if telegram_bot.disabled:
        logger.info("Telegram Polling abgebrochen: Telegram ist deaktiviert (TELEGRAM_* fehlen).")
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
