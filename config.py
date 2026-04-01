"""
Umgebungsvariablen & Konstanten für den Gifhorn Events Bot.
Lädt .env und validiert Pflicht-Keys beim Import (siehe 01a-CONFIG).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

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

# ==================== EMAIL SCREENING ====================
EMAIL_SCREENING_ENABLED: bool = os.getenv("EMAIL_SCREENING_ENABLED", "1").strip() == "1"
EMAIL_ATTACHMENT_STORAGE_PATH: str = os.getenv(
    "EMAIL_ATTACHMENT_STORAGE_PATH", "/app/email_attachments"
)
# Sender-Whitelist (Regex-Patterns, kommagerennt)
EMAIL_SENDER_PATTERNS: list[str] = [
    p.strip() for p in (os.getenv("EMAIL_SENDER_PATTERNS", ".*@example.com") or "").split(",")
    if p.strip()
]
# Keywords für Email-Screening (kommagerennt)
EMAIL_KEYWORDS: list[str] = [
    k.strip() for k in (
        os.getenv("EMAIL_KEYWORDS", "event,plakat,anmeldung,veranstaltung,ankündigung")
        or ""
    ).split(",")
    if k.strip()
]
EMAIL_REQUIRE_ATTACHMENTS: bool = os.getenv("EMAIL_REQUIRE_ATTACHMENTS", "1").strip() == "1"
EMAIL_MIN_ATTACHMENT_SIZE: int = int(os.getenv("EMAIL_MIN_ATTACHMENT_SIZE", "50000"))  # Bytes
EMAIL_MAX_ATTACHMENT_SIZE: int = int(os.getenv("EMAIL_MAX_ATTACHMENT_SIZE", "10000000"))  # 10MB

# Nach freigegebener Email: Event sofort für Meta markieren (keine 2. Telegram-Runde)
AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS: bool = (
    os.getenv("AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS", "0").strip() == "1"
)
# Direkt nach Email→Event auf Instagram/Facebook posten (impliziert Social-Freigabe)
AUTO_POST_AFTER_EMAIL_CONVERSION: bool = (
    os.getenv("AUTO_POST_AFTER_EMAIL_CONVERSION", "0").strip() == "1"
)
# Öffentliche Basis-URL der Flyer (Dashboard muss /flyers bereitstellen), z. B.
# https://dein-service.railway.app/flyers — für Meta image_url bei lokalem Speicherpfad
PUBLIC_IMAGE_BASE_URL: Optional[str] = os.getenv("PUBLIC_IMAGE_BASE_URL") or None

# ==================== GLOBALE KONSTANTEN ====================

# Posting-Zeiten (Empfehlung Europe/Berlin — Uhrzeiten im Railway-Cron eintragen)
# ~19:00  worker.py --collect   → Mail-Digest: Spam pro Mail ❌, dann „Alle übrigen freigeben“
# ~21:00  worker.py --evening-preview → KI-Beiträge zur Freigabe
# danach  worker.py --post       → Meta (wenn du die Beiträge freigegeben hast)
CRON_COLLECT_TIME = "19:00"  # = Mail-Abruf + Digest (deine Bestätigung)
CRON_EVENING_PREVIEW_TIME = "21:00"
POSTING_TIME = "22:00"  # Meta-Posting nach Freigabe der Abend-Vorschau
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

# ==================== EMAIL SCREENER INITIALISIERUNG ====================
# (wird am Ende importiert um Circular Import zu vermeiden)
try:
    from scrapers.email_screener import EmailScreener
    email_screener = EmailScreener(
        sender_patterns=EMAIL_SENDER_PATTERNS,
        keywords=EMAIL_KEYWORDS,
        require_attachments=EMAIL_REQUIRE_ATTACHMENTS,
        min_attachment_size=EMAIL_MIN_ATTACHMENT_SIZE,
        max_attachment_size=EMAIL_MAX_ATTACHMENT_SIZE,
    ) if EMAIL_SCREENING_ENABLED else None
except ImportError:
    email_screener = None  # Bei Import-Fehler: deaktiviert


def public_image_url(stored: str) -> str:
    """
    Wandelt einen lokalen Anhang-Pfad in eine öffentliche URL um, wenn
    PUBLIC_IMAGE_BASE_URL gesetzt ist (sonst unverändert — Meta braucht https).
    """
    if not stored:
        return ""
    s = stored.strip()
    if s.startswith(("http://", "https://")):
        return s
    base = (PUBLIC_IMAGE_BASE_URL or "").rstrip("/")
    if not base:
        return s
    name = Path(s).name
    return f"{base}/{name}"
