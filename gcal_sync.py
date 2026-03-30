"""
Google Kalender Synchronisation (GCal).
Siehe Vault-Doku 02g-GCAL-SYNC.

Fail-soft: Wenn OAuth/Token fehlt oder Google nicht erreichbar ist,
wird geloggt und einfach nichts synced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE
from database import db

logger = logging.getLogger(__name__)

SCOPES: List[str] = ["https://www.googleapis.com/auth/calendar"]


class GCalSync:
    def __init__(self, calendar_id: str = "primary") -> None:
        self.service: Optional[Any] = None
        self.calendar_id = calendar_id

    def authenticate(self) -> None:
        """Authentifiziert Google Calendar via OAuth (token.json)."""
        creds: Optional[UserCredentials] = None

        try:
            # Token wiederverwenden, wenn möglich
            try:
                import os

                if os.path.exists(GOOGLE_TOKEN_FILE):
                    creds = UserCredentials.from_authorized_user_file(
                        GOOGLE_TOKEN_FILE, SCOPES
                    )
            except Exception:
                creds = None

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # Desktop/Auth Flow
                    flow = InstalledAppFlow.from_client_secrets_file(
                        GOOGLE_CREDENTIALS_FILE, SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                    # Token speichern
                    with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
                        token.write(creds.to_json())

            self.service = build("calendar", "v3", credentials=creds)
            logger.info("✅ Google Calendar authentifiziert")
        except Exception as e:
            logger.warning("GCal authenticate fehlgeschlagen: %s", e)
            self.service = None

    def sync_events(self) -> None:
        """Synchronisiere (bereits gepostete) Events zu Google Kalender."""
        if not self.service:
            self.authenticate()
        if not self.service:
            return

        try:
            # Fail-soft: nur 'posted' Events
            db.connect()
            db.create_tables()
            events = db.list_events_dashboard(status_filter="posted", limit=200)

            for event in events:
                # event_date kommt als string (TIMESTAMP in DB)
                start = str(event.get("event_date") or "")[:19]
                if not start:
                    continue

                try:
                    # robust ISO-Parse
                    # Falls event_date schon "YYYY-MM-DD HH:MM:SS" ist:
                    dt = datetime.fromisoformat(start.replace(" ", "T"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    dt = datetime.now(timezone.utc)

                gcal_body: Dict[str, Any] = {
                    "summary": event.get("title", "Event"),
                    "description": event.get("description", "") or "",
                    "location": event.get("location", "") or "",
                    "start": {
                        "dateTime": dt.isoformat(),
                        "timeZone": "Europe/Berlin",
                    },
                    "end": {
                        "dateTime": dt.isoformat(),
                        "timeZone": "Europe/Berlin",
                    },
                }

                try:
                    # Ohne eigene Idempotency-Strategie: insert kann duplizieren.
                    # In Phase 3 kann das verbessert werden (z. B. event_hash → extendedProperties).
                    self.service.events().insert(
                        calendarId=self.calendar_id, body=gcal_body
                    ).execute()
                except HttpError as he:
                    logger.warning("GCal insert HttpError: %s", he)

            logger.info("✅ GCal Sync: %s Events", len(events))
        except Exception as e:
            logger.warning("GCal sync fehlgeschlagen: %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass


gcal_sync = GCalSync()

