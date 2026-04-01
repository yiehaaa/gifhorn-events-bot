#!/usr/bin/env python3
"""Einmalig: letzte email_submissions aus der DB listen (Railway / lokal)."""
from __future__ import annotations

import os
import sys

# Repo-Root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import RealDictCursor

from database import db


def main() -> None:
    db.connect()
    if db.mode != "pg":
        print("Nur PostgreSQL (DATABASE_URL) unterstützt für dieses Skript.")
        sys.exit(1)
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, subject, approval_status, sender_email, created_at,
                   converted_to_event_id, ingest_batch_id
            FROM email_submissions
            ORDER BY id DESC
            LIMIT 30
            """
        )
        rows = cur.fetchall()
    if not rows:
        print("Keine Zeilen in email_submissions.")
        return
    print(f"Letzte {len(rows)} Einträge:\n")
    for r in rows:
        d = dict(r)
        subj = (d.get("subject") or "")[:70]
        print(
            f"id={d.get('id')} | {d.get('approval_status')} | "
            f"{d.get('sender_email')} | {subj!r}"
        )
    db.close()


if __name__ == "__main__":
    main()
