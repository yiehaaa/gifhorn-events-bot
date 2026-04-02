#!/usr/bin/env python3
"""
Sendet den Mail-Digest erneut für pending `email_submissions` (z. B. nach Fix:
Telegram bei MOCK_MODE).

Nutzt die neueste `ingest_batch_id` (32 hex) unter den pending Zeilen.

  python scripts/resend_pending_email_digest.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Repo-Root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db  # noqa: E402
from telegram_bot import telegram_bot  # noqa: E402


def _row_to_email(r: dict) -> dict:
    att_raw = r.get("attachment_urls")
    attachments: list = []
    if att_raw:
        if isinstance(att_raw, str):
            try:
                att_raw = json.loads(att_raw)
            except json.JSONDecodeError:
                att_raw = {}
        if isinstance(att_raw, dict):
            attachments = [{"filename": k} for k in att_raw.keys()]
        elif isinstance(att_raw, list):
            attachments = att_raw
    return {
        "id": r.get("gmail_message_id"),
        "sender": r.get("sender_email") or "unknown",
        "subject": r.get("subject") or "",
        "body": r.get("body_text") or "",
        "attachments": attachments,
        "screening_score": r.get("screening_score") or 0,
        "db_submission_id": int(r["id"]),
    }


async def main() -> None:
    db.connect()
    db.create_tables()
    pending = db.get_pending_email_submissions()
    if not pending:
        print("Keine pending email_submissions.")
        return

    batch = (pending[0].get("ingest_batch_id") or "").strip()
    if len(batch) != 32:
        print("Neueste pending-Zeile hat keine gültige ingest_batch_id (32 hex).")
        return

    same = [r for r in pending if (r.get("ingest_batch_id") or "").strip() == batch]
    emails = [_row_to_email(r) for r in same]

    if telegram_bot.disabled:
        print("Telegram deaktiviert: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen.")
        return

    await telegram_bot.send_daily_email_digest(emails, batch)
    print(f"Digest gesendet: {len(emails)} Mails, batch={batch[:8]}…")


if __name__ == "__main__":
    asyncio.run(main())
