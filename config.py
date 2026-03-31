"""
Umgebungsvariablen & Konstanten für den Gifhorn Events Bot.
Lädt .env und validiert Pflicht-Keys beim Import (siehe 01a-CONFIG).
"""

from __future__ import annotations

import os
from typing import Optional

from pathlib import Path

from dotenv import load_dotenv

# .env relativ zum config.py-Verzeichnis laden – funktioniert unabhängig vom CWD
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ==================== MODE ====================
# Wenn `MOCK_MODE=1` ist gesetzt, laufen wir ohne externe API-Keys durch
# (für lokale Tests, Dashboard-Einreichung und Posting-Simulation).
MOCK_MODE: bool = os.getenv("MOCK_MODE", "0").strip() == "1"

# ==================== DATABASE ====================
DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
if not DATABASE_URL and not MOCK_MODE:
    assert DATABASE_URL, "DATABASE_URL nicht in .env gesetzt"

SQLITE_PATH: str = os.getenv("SQLITE_PATH", "events.sqlite3")

# ==================== CLAUDE API ====================
CLAUDE_API_KEY: Optional[str] = os.getenv("CLAUDE_API_KEY")
if not MOCK_MODE:
    assert CLAUDE_API_KEY, "CLAUDE_API_KEY nicht in .env gesetzt"
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

# ==================== TELEGRAM ====================
TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
if not MOCK_MODE:
    assert TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN nicht in .env gesetzt"
    assert TELEGRAM_CHAT_ID, "TELEGRAM_CHAT_ID nicht in .env gesetzt"

# ==================== META (Instagram/Facebook) ====================
META_ACCESS_TOKEN: Optional[str] = os.getenv("META_ACCESS_TOKEN")
META_IG_ACCOUNT_ID: Optional[str] = os.getenv("META_IG_ACCOUNT_ID")  # Instagram Business Account ID
META_FB_PAGE_ID: Optional[str] = os.getenv("META_FB_PAGE_ID")  # Facebook Page ID
META_API_VERSION: str = os.getenv("META_API_VERSION", "v18.0")
if not MOCK_MODE:
    assert META_ACCESS_TOKEN, "META_ACCESS_TOKEN nicht in .env gesetzt"

# ==================== GOOGLE (Gmail + Calendar) ====================
GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "client_secret.json")
GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
GMAIL_ADDRESS: Optional[str] = os.getenv("GMAIL_ADDRESS")  # Bot's Gmail Adresse

# ==================== GLOBALE KONSTANTEN ====================

# Posting-Zeiten
CRON_COLLECT_TIME = "19:00"  # Tägliche Sammlung
POSTING_TIME = "20:00"  # Wann wird gepostet?
POSTING_TIMEZONE = "Europe/Berlin"

# Deduplizierung
DEDUP_HASH_THRESHOLD = 0.95  # Fuzzy-Match Score (0-1)
DEDUP_MIN_CHARS = 50  # Minimale Event-Beschreibung

# Claude
CLAUDE_POST_TEMPLATE = """Du bist ein Event-Manager für Gifhorn und Umgebung.
Schreibe einen Instagram-Post für folgendes Event (gleicher Text für Instagram und Facebook):

{event_details}

Hashtag-Basis (verwende diese Tags als Ausgangspunkt):
{hashtags}

Anforderungen:
- 200–500 Zeichen (ohne harte Grenzen, aber kürzen wenn nötig)
- Lockerer, freundlicher Ton
- Keine Werbung, nur Info
- Uhrzeit & Ort prominent
- Hashtags: Füge am ENDE als letzte Zeile exakt eine Hashtag-Zeile ein.
  Nutze hauptsächlich die Hashtag-Basis; ergänze höchstens 1–3 weitere passende Tags.
"""

# Telegram
TELEGRAM_MESSAGE_FORMAT = """
🎪 *Neue Events zur Freigabe*

{event_preview}

Reagiere mit:
✅ zum Freigeben
❌ zum Ablehnen
📝 für Details
"""

# Meta
INSTAGRAM_HASHTAGS = "#gifhorn #veranstaltung #events #niedersachsen #wolfsburg #braunschweig"
FACEBOOK_HASHTAGS = "#gifhorn #veranstaltung #events"

# Fehler-Handling
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
ERROR_WEBHOOK: Optional[str] = os.getenv("ERROR_WEBHOOK")  # Optional: Sentry/Custom Webhook

# Web-Dashboard (FastAPI, nur für dich – HTTP Basic Auth)
DASHBOARD_USER: str = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD: Optional[str] = os.getenv("DASHBOARD_PASSWORD")

# Phase 2 – Datenquellen
TICKETMASTER_API_KEY: Optional[str] = os.getenv("TICKETMASTER_API_KEY")
# Leer lassen, bis du einen gültigen .ics-Link hast (alter Default 404).
USK_ICAL_URL: Optional[str] = os.getenv("USK_ICAL_URL") or None
SUEDHEIDE_EVENTS_URL: str = os.getenv(
    "SUEDHEIDE_EVENTS_URL", "https://www.suedheide-gifhorn.de/veranstaltungen"
)
STADTHALLE_PROGRAM_URL: str = os.getenv(
    "STADTHALLE_PROGRAM_URL", "https://www.stadthalle-gifhorn.de/programm"
)

# Externe Scraper standardmäßig deaktivieren (damit Tests ohne APIs funktionieren).
SCRAPERS_ENABLED: bool = os.getenv("SCRAPERS_ENABLED", "0").strip() == "1"
