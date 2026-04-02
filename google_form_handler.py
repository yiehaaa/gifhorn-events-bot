"""
Google Forms + Sheets API Integration für Event-Datenerfassung.

Flow (täglich um ~19:00 mit collect_and_approve_flow):
1. Google Form (öffentlich) → Responses in Google Sheets speichern
2. Dieser Handler: polling der Sheets → neue Rows extrahieren (einmal täglich)
3. Jede Row → Event in DB (source="google_form", contact_email=...)
4. Normale Pipeline: Claude → Telegram → Meta

Anforderungen (.env):
- GOOGLE_FORM_SPREADSHEET_ID: Sheets-ID (aus URL)
- GOOGLE_FORM_SHEET_NAME: Tab-Name (default: "Form Responses 1")
- GOOGLE_CREDENTIALS_FILE: Service Account JSON
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials
    from google.oauth2 import service_account
    import googleapiclient.discovery as discovery
except ImportError:
    # Fallback wenn Google-Libs nicht installiert
    Credentials = None
    discovery = None

from config import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_FORM_SPREADSHEET_ID,
    GOOGLE_FORM_SHEET_NAME,
    MOCK_MODE,
)

logger = logging.getLogger(__name__)

# Google Sheets API Scopes
SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class GoogleFormHandler:
    """Handler für Google Forms → Sheets → Events"""

    def __init__(self) -> None:
        self.service = None
        self.spreadsheet_id = GOOGLE_FORM_SPREADSHEET_ID
        self.sheet_name = GOOGLE_FORM_SHEET_NAME
        self.last_processed_row = 0  # Track welche Rows wir bereits verarbeitet haben

    def authenticate(self) -> None:
        """Google Sheets API authentifizieren via Service Account"""
        if MOCK_MODE:
            logger.warning("MOCK_MODE: Google Sheets nicht authentifiziert")
            return

        if not discovery:
            logger.warning("google-api-client nicht installiert; google_form_handler disabled")
            return

        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=SHEETS_SCOPE
            )
            self.service = discovery.build("sheets", "v4", credentials=creds)
            logger.info("Google Sheets API authentifiziert")
        except Exception as e:
            logger.error(f"Google Sheets Auth fehlgeschlagen: {e}")
            raise

    def get_form_responses(self) -> List[Dict[str, Any]]:
        """
        Lese alle Responses aus Google Sheets.

        Returns:
            Liste von Response-Dicts, jeweils mit Keys aus Header-Zeile
        """
        if MOCK_MODE or not self.service:
            logger.debug("MOCK_MODE oder Service nicht verfügbar; leere Response-Liste")
            return []

        try:
            # Lese Sheets (A1:K mit Header für 11 Spalten)
            # Form: Titel, Start-Datum, End-Datum, Uhrzeit, Ort, Stadt, Beschreibung, Eintritt, Link, Flyer, Email
            range_name = f"{self.sheet_name}!A1:K"
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=range_name)
                .execute()
            )

            values = result.get("values", [])
            if not values:
                logger.debug("Keine Responses in Google Sheets")
                return []

            # Header = erste Zeile
            header = values[0]
            responses = []

            # Ab Zeile 2: Daten
            for row in values[1:]:
                # Pad row falls kürzer als header
                row_padded = row + [""] * (len(header) - len(row))
                response_dict = {header[i]: row_padded[i] for i in range(len(header))}
                responses.append(response_dict)

            logger.info(f"Google Sheets: {len(responses)} Responses gelesen")
            return responses

        except Exception as e:
            logger.error(f"Fehler beim Lesen von Google Sheets: {e}")
            return []

    def parse_form_response(self, response: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Parse Google Form Response → Event-Dict

        Form-Felder (neue Struktur):
        1. Wie heißt die Veranstaltung?
        2. Tag, Monat, Jahr
        3. Eintägig oder mehrtägig?
        4. Uhrzeit (z.B. '10:00 - 17:00')
        5. Veranstaltungsort (Ort/Adresse mit PLZ)
        6. Stadt
        7. Beschreibung
        8. Eintritt (€)
        9. Link zu mehr Informationen
        10. Deine Email
        """
        try:
            # Parse Datumsbereich + Uhrzeit
            start_date_str = response.get("Veranstaltung beginnt (Datum)", "").strip()  # Format: YYYY-MM-DD
            end_date_str = response.get("Veranstaltung endet (Datum)", "").strip()      # Format: YYYY-MM-DD
            time_str = response.get("Uhrzeit (z.B. '10:00 - 17:00' oder '10:00 - 18:00')", "").strip()

            # Berechne Tageanzahl
            days_count = 1
            if start_date_str and end_date_str:
                try:
                    from datetime import datetime
                    start = datetime.strptime(start_date_str, "%Y-%m-%d")
                    end = datetime.strptime(end_date_str, "%Y-%m-%d")
                    days_count = (end - start).days + 1
                except:
                    days_count = 1

            # Formatiere event_date
            if start_date_str and end_date_str:
                event_date = f"{start_date_str} bis {end_date_str} ({days_count} Tage)"
            elif start_date_str:
                event_date = f"{start_date_str}"
            else:
                event_date = "Datum nicht angegeben"

            # Füge Uhrzeit hinzu wenn vorhanden
            if time_str:
                event_date = f"{event_date} | {time_str}"

            event = {
                "source": "google_form",
                "source_id": f"gform-{response.get('Timestamp', 'unknown').replace(' ', '_')}",
                "title": response.get("Wie heißt die Veranstaltung?", "").strip(),
                "event_date": event_date,
                "location": response.get("Veranstaltungsort (Ort/Adresse mit PLZ)", "").strip(),
                "city": response.get("Stadt", "Gifhorn").strip(),
                "description": response.get("Beschreibung", "").strip(),
                "price_min": self._parse_price(response.get("Eintritt (€)", "0")),
                "price_max": self._parse_price(response.get("Eintritt (€)", "0")),
                "url": response.get("Link zu mehr Informationen", "").strip(),
                "image_url": response.get("Flyer oder mehr Infos (Google Drive Link oder URL)", "").strip(),  # Flyer-Link
                "contact_email": response.get("Deine Email (für Rückfragen)", "").strip(),
            }

            # Validierung: Title + event_date erforderlich
            if not event["title"] or not event["event_date"]:
                logger.warning(f"Form-Response unvollständig: {response}")
                return None

            return event

        except Exception as e:
            logger.error(f"Fehler beim Parsen von Form-Response: {e}")
            return None

    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse Preis aus String (z.B. '5,50' oder '0')"""
        if not price_str:
            return None
        try:
            # Komma zu Punkt
            price_clean = price_str.replace(",", ".").strip()
            return float(price_clean) if price_clean and price_clean != "0" else 0.0
        except ValueError:
            return None

    def get_new_responses(self) -> List[Dict[str, Any]]:
        """
        Lese nur NEUE Responses seit letztem Lauf.

        (Vereinfachte Logik: Zähle Gesamtrows, verarbeite nur neue)
        """
        all_responses = self.get_form_responses()
        if not all_responses:
            return []

        # Neue Responses = ab self.last_processed_row
        new_responses = all_responses[self.last_processed_row :]
        self.last_processed_row = len(all_responses)

        parsed_events = []
        for resp in new_responses:
            event = self.parse_form_response(resp)
            if event:
                parsed_events.append(event)

        logger.info(f"Google Forms: {len(parsed_events)} neue Events geparst")
        return parsed_events


# Globale Instanz
google_form_handler = GoogleFormHandler()
