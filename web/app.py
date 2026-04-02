"""
Lokales Web-Dashboard: Events, Freigaben, Logs.

Start:
  .venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8080

.env: DASHBOARD_PASSWORD (und optional DASHBOARD_USER)
"""

from __future__ import annotations

import logging
import secrets
import os
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from pathlib import Path
from typing import List, Optional
import uuid
import shutil

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, validator

from claude_handler import claude_handler
from config import (
    AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS,
    AUTO_POST_AFTER_EMAIL_CONVERSION,
    CRON_COLLECT_TIME,
    CRON_EVENING_PREVIEW_TIME,
    DASHBOARD_PASSWORD,
    DASHBOARD_USER,
    EMAIL_ATTACHMENT_STORAGE_PATH,
    EMAIL_SCREENING_ENABLED,
    GOOGLE_FORM_URL,
    META_ACCESS_TOKEN,
    MOCK_MODE,
    POSTING_TIME,
    POSTING_TIMEZONE,
    PUBLIC_IMAGE_BASE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from database import db
from dm_handler import create_dm_router
from web.email_approval_dashboard import router as email_router
from meta_poster import meta_poster

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

security = HTTPBasic(auto_error=False)

VALID_FILTERS: List[str] = [
    "all",
    "awaiting_telegram",
    "ready_meta",
    "posted",
    "rejected",
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Kein DB-Connect beim Start — sonst stürzt Uvicorn ab, wenn Postgres nicht läuft (-102 im Browser)."""
    yield
    db.close()


app = FastAPI(title="Gifhorn Events Dashboard", lifespan=lifespan)

# Öffentliche Flyer für Meta image_url (PUBLIC_IMAGE_BASE_URL …/flyers/Dateiname)
_flyers_root = Path(EMAIL_ATTACHMENT_STORAGE_PATH)
try:
    _flyers_root.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
if _flyers_root.is_dir():
    app.mount(
        "/flyers",
        StaticFiles(directory=str(_flyers_root.resolve())),
        name="flyers",
    )

# DM Webhook-Routen im selben Service bereitstellen (später per Reverse Proxy nach außen).
app.include_router(create_dm_router(), tags=["dm"])

# Email Submission Approval API + Dashboard
app.include_router(email_router)


def require_db() -> None:
    """Einmalig verbinden, wenn noch nicht geschehen."""
    if db.conn is not None:
        return
    try:
        db.connect()
        db.create_tables()
    except Exception as e:
        logger.exception("Dashboard: DB-Verbindung fehlgeschlagen")
        raise HTTPException(
            status_code=503,
            detail=(
                "PostgreSQL nicht erreichbar. Prüfe DATABASE_URL und ob die DB läuft. "
                f"Technisch: {e!s}"
            ),
        ) from e


@app.get("/health")
async def health() -> dict[str, str]:
    """Ohne Auth — prüfen, ob Uvicorn überhaupt läuft (bei -102 hier testen)."""
    return {"status": "ok", "service": "gifhorn-events-dashboard"}


@app.get("/start", response_class=HTMLResponse)
async def dashboard_start() -> HTMLResponse:
    """
    Öffentliche Einstiegshilfe: `/` verlangt sofort Basic Auth (401) — wirkt wie „leere Seite“,
    wenn der Browser keinen Login-Dialog zeigt oder man die URL nur testet.
    """
    html = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Gifhorn Events – Web-Dashboard</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    code { background: #f0f0f0; padding: 0.1em 0.35em; border-radius: 4px; }
    a { color: #0b57d0; }
  </style>
</head>
<body>
  <h1>Web-Dashboard</h1>
  <p>Dieser Railway-Service <strong>ist</strong> das Dashboard (FastAPI + Uvicorn). Die eigentliche Oberfläche liegt unter <code>/</code> und ist mit <strong>HTTP Basic Auth</strong> geschützt.</p>
  <ol>
    <li>In Railway beim Service <code>gifhorn-dashboard</code> die Variable <code>DASHBOARD_PASSWORD</code> setzen (und optional <code>DASHBOARD_USER</code>, Standard <code>admin</code>).</li>
    <li>Die öffentliche URL öffnen (Railway → Service → Networking → Domain), dann auf <a href="/">Startseite /</a> gehen.</li>
    <li>Der Browser sollte nach <strong>Benutzername und Passwort</strong> fragen — nicht mit der Railway-Anmeldung verwechseln.</li>
  </ol>
  <p>Nach dem Login: <strong>Betrieb &amp; Live</strong> (MOCK_MODE, angebundene APIs, E-Mail-Warteschlange, Auto-Flags — aktualisiert sich alle 45&nbsp;s), Eventliste, Freigaben, Einreichung. E-Mail-Flyer: <a href="/api/emails/">/api/emails/</a> (ebenfalls nach Login).</p>
  <p>Wenn stattdessen ein Datenbank-Fehler kommt: Postgres und <code>DATABASE_URL</code> prüfen.</p>
  <p><a href="/health">Technischer Health-Check (/health)</a> (ohne Login)</p>
</body>
</html>"""
    return HTMLResponse(content=html)


def require_dashboard_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:
    if not DASHBOARD_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="DASHBOARD_PASSWORD in .env setzen",
        )
    if credentials is None:
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Gifhorn Events"'},
        )
    u_ok = secrets.compare_digest(credentials.username, DASHBOARD_USER)
    p_ok = secrets.compare_digest(credentials.password, DASHBOARD_PASSWORD)
    if not (u_ok and p_ok):
        raise HTTPException(
            status_code=401,
            detail="Ungültige Zugangsdaten",
            headers={"WWW-Authenticate": 'Basic realm="Gifhorn Events"'},
        )
    return credentials.username


def _normalize_filter(v: Optional[str]) -> str:
    if not v or v not in VALID_FILTERS:
        return "all"
    return v


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="filter"),
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
):
    f = _normalize_filter(status_filter)
    events = db.list_events_dashboard(status_filter=f, limit=250)
    stats = db.dashboard_stats()
    email_stats = db.dashboard_email_submission_stats()
    logs = db.list_recent_logs(limit=35)
    now_utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        _tz = ZoneInfo(POSTING_TIMEZONE)
        now_local_str = datetime.now(_tz).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        now_local_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    live = {
        "generated_at": now_utc.isoformat(),
        "now_local": now_local_str,
        "timezone_label": POSTING_TIMEZONE,
        "mock_mode": MOCK_MODE,
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "meta_token_set": bool(META_ACCESS_TOKEN),
        "public_image_base_url_set": bool(PUBLIC_IMAGE_BASE_URL),
        "email_screening_enabled": EMAIL_SCREENING_ENABLED,
        "auto_post_after_email": AUTO_POST_AFTER_EMAIL_CONVERSION,
        "auto_approve_email_social": AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS,
        "schedule": {
            "collect": CRON_COLLECT_TIME,
            "evening_preview": CRON_EVENING_PREVIEW_TIME,
            "posting": POSTING_TIME,
            "timezone": POSTING_TIMEZONE,
        },
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "events": events,
            "stats": stats,
            "email_stats": email_stats,
            "logs": logs,
            "live": live,
            "current_filter": f,
            "filters": [
                ("all", "Alle"),
                ("awaiting_telegram", "Warten auf Freigabe"),
                ("ready_meta", "Freigegeben → Meta"),
                ("posted", "Gepostet"),
                ("rejected", "Abgelehnt"),
            ],
        },
    )


@app.get("/api/dashboard/snapshot")
async def dashboard_snapshot(
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
) -> JSONResponse:
    """
    Kompakte Live-Daten für Auto-Refresh im Browser (gleiche Basic Auth wie /).
    """
    now_utc = datetime.now(timezone.utc)
    return JSONResponse(
        {
            "generated_at": now_utc.isoformat(),
            "stats": db.dashboard_stats(),
            "email_stats": db.dashboard_email_submission_stats(),
            "runtime": {
                "mock_mode": MOCK_MODE,
                "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
                "meta_token_set": bool(META_ACCESS_TOKEN),
                "public_image_base_url_set": bool(PUBLIC_IMAGE_BASE_URL),
                "email_screening_enabled": EMAIL_SCREENING_ENABLED,
                "auto_post_after_email": AUTO_POST_AFTER_EMAIL_CONVERSION,
                "auto_approve_email_social": AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS,
            },
            "schedule": {
                "collect": CRON_COLLECT_TIME,
                "evening_preview": CRON_EVENING_PREVIEW_TIME,
                "posting": POSTING_TIME,
                "timezone": POSTING_TIMEZONE,
            },
        }
    )


@app.post("/action/{event_id}/approve")
async def action_approve(
    event_id: int,
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
):
    db.set_telegram_approval(event_id, approved=True)
    return RedirectResponse(url="/", status_code=303)


@app.post("/action/{event_id}/reject")
async def action_reject(
    event_id: int,
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
):
    db.set_telegram_approval(event_id, approved=False)
    return RedirectResponse(url="/", status_code=303)


def _normalize_datetime_local(value: str) -> str:
    """
    Server-seitig normalisieren, damit wir das DB-TIMESTAMP akzeptieren:
    - HTML input[type=datetime-local] liefert meist `YYYY-MM-DDTHH:MM`
    - Postgres bevorzugt `YYYY-MM-DD HH:MM:SS`
    """
    v = (value or "").strip()
    v = v.replace("T", " ")
    # Wenn Sekunden fehlen: ergänzen
    if len(v) == 16 and v.count(":") == 1:
        v = v + ":00"
    return v


@app.post("/submit")
async def submit_event(
    title: str = Form(...),
    event_date: str = Form(...),
    location: str = Form(""),
    city: str = Form(""),
    description: str = Form(""),
    url: str = Form(""),
    image_url: str = Form(""),
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
):
    """Event einreichen (ohne externe APIs) → landet in 'awaiting_telegram'."""
    event_date_norm = _normalize_datetime_local(event_date)
    source_id = f"web-{uuid.uuid4().hex}"

    event = {
        "source": "web_submit",
        "source_id": source_id,
        "title": title,
        "event_date": event_date_norm,
        "location": location,
        "city": city,
        "description": description,
        "url": url,
        "image_url": image_url,
    }

    # In MOCK_MODE generiert claude_handler einen Text-Fallback.
    post_text = claude_handler.generate_post_text(event)
    eid = db.add_event(
        source=event["source"],
        source_id=event["source_id"],
        title=event["title"],
        description=event["description"],
        image_url=event["image_url"],
        event_date=event["event_date"],
        location=event["location"],
        city=event["city"],
        url=event["url"],
        post_text=post_text,
    )

    if eid is None:
        # Sollte bei unique(source_id) kaum passieren; Redirect trotzdem.
        pass

    return RedirectResponse(url="/", status_code=303)


@app.post("/action/post_ready")
async def action_post_ready(
    _: str = Depends(require_dashboard_auth),
    __: None = Depends(require_db),
):
    """Poste/simuliere alle 'ready_meta' Events (ohne externe APIs im MOCK_MODE)."""
    ready = db.get_events_ready_for_meta()
    if ready:
        meta_poster.batch_post(ready, platforms=["instagram", "facebook"])
    return RedirectResponse(url="/", status_code=303)


@app.get("/form/redirect", response_class=RedirectResponse)
async def form_redirect():
    """
    Bio-Link Redirect: öffentlich zugänglich (kein Auth).
    Nutzer klickt Insta/FB Bio → /form/redirect → Google Form.
    """
    return RedirectResponse(url=GOOGLE_FORM_URL, status_code=307)


# ==================== WEB FORM (mit dynamischen Uhrzeiten) ====================

class TimeSlot(BaseModel):
    start: str  # HH:MM
    end: str    # HH:MM

class EventFormData(BaseModel):
    title: str
    startDate: str  # YYYY-MM-DD
    endDate: str    # YYYY-MM-DD
    times: List[TimeSlot]
    location: str
    city: str
    description: Optional[str] = ""
    price: Optional[float] = 0.0
    url: Optional[str] = ""
    flyerUrl: Optional[str] = ""
    email: str
    source: str = "web_form"

    @validator('title')
    def title_not_empty(cls, v):
        if not v or len(v) < 3:
            raise ValueError('Veranstaltungstitel erforderlich (min. 3 Zeichen)')
        return v.strip()

    @validator('email')
    def email_valid(cls, v):
        if '@' not in v:
            raise ValueError('Gültige Email erforderlich')
        return v.strip().lower()

    @validator('location')
    def location_not_empty(cls, v):
        if not v or len(v) < 5:
            raise ValueError('Veranstaltungsort erforderlich')
        return v.strip()

    @validator('startDate')
    def start_date_valid(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError('Ungültiges Startdatum')
        return v

    @validator('endDate')
    def end_date_valid(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError('Ungültiges Enddatum')
        return v


@app.get("/form/event")
async def form_event_page(request: Request):
    """Web-Form für Veranstalter (öffentlich)."""
    return templates.TemplateResponse("event_form.html", {"request": request})


@app.post("/form/submit")
async def form_submit(
    title: str = Form(...),
    startDate: str = Form(...),
    endDate: str = Form(...),
    times: str = Form(...),  # JSON string
    locationStreet: str = Form(...),
    locationZip: str = Form(...),
    locationCity: str = Form(...),
    description: str = Form(""),
    price: float = Form(0.0),
    url: str = Form(""),
    email: str = Form(...),
    source: str = Form("web_form"),
    flyerFile: UploadFile = File(None),
    __: None = Depends(require_db),
):
    """
    Event-Submission über Web-Form mit Datei-Upload.
    - Datei wird lokal in /flyers gespeichert
    - Event wird in DB gespeichert
    - Claude Post-Text wird generiert
    """
    try:
        # Validierungen
        title = title.strip()
        if not title or len(title) < 3:
            raise ValueError('Veranstaltungstitel erforderlich (min. 3 Zeichen)')

        locationStreet = locationStreet.strip()
        if not locationStreet or len(locationStreet) < 3:
            raise ValueError('Straße/Ort erforderlich')

        locationZip = locationZip.strip()
        if not locationZip or not locationZip.isdigit() or len(locationZip) != 5:
            raise ValueError('PLZ erforderlich (5 Ziffern)')

        locationCity = locationCity.strip()
        if not locationCity or len(locationCity) < 2:
            raise ValueError('Ort/Dorf erforderlich')

        if '@' not in email:
            raise ValueError('Gültige Email erforderlich')

        # Parse Datumsbereich
        start = datetime.strptime(startDate, '%Y-%m-%d')
        end = datetime.strptime(endDate, '%Y-%m-%d')

        if end < start:
            raise ValueError('Enddatum muss nach Startdatum liegen')

        # Parse Uhrzeiten JSON
        import json
        try:
            times_list = json.loads(times)
        except json.JSONDecodeError:
            times_list = []

        # Formatiere Uhrzeiten
        times_formatted = [f"{t['start']}-{t['end']}" for t in times_list] if times_list else []
        times_str = " | ".join(times_formatted) if times_formatted else "Uhrzeiten nicht angegeben"

        # Speichere Flyer-Datei (optional)
        flyer_url = ""
        if flyerFile and flyerFile.filename:
            try:
                # Erstelle /flyers Ordner falls nicht existent
                flyers_dir = Path(EMAIL_ATTACHMENT_STORAGE_PATH)
                flyers_dir.mkdir(parents=True, exist_ok=True)

                # Generiere sicheren Dateinamen
                file_ext = Path(flyerFile.filename).suffix
                safe_filename = f"{uuid.uuid4().hex}{file_ext}"
                file_path = flyers_dir / safe_filename

                # Speichere Datei
                with open(file_path, 'wb') as f:
                    content = await flyerFile.read()
                    f.write(content)

                # Generiere öffentlichen Link
                flyer_url = f"/flyers/{safe_filename}"
                logger.info(f"Flyer hochgeladen: {safe_filename}")
            except Exception as e:
                logger.warning(f"Fehler beim Flyer-Upload: {e}")
                # Fahre trotzdem fort — Flyer ist optional

        # Formatiere event_date
        days_count = (end - start).days + 1
        event_date_str = f"{startDate} bis {endDate} ({days_count} Tage) | {times_str}"

        # Kombiniere die drei Standort-Felder
        location_combined = f"{locationStreet} {locationZip} {locationCity}"

        # Erstelle Event
        event = {
            "source": source,
            "source_id": f"webform-{uuid.uuid4().hex[:8]}",
            "title": title,
            "event_date": event_date_str,
            "location": location_combined,
            "city": locationCity,  # Stadt wird aus dem "Ort/Dorf" Feld genommen
            "description": description.strip(),
            "price_min": price or 0.0,
            "price_max": price or 0.0,
            "url": url.strip(),
            "image_url": flyer_url,  # Lokaler Link zu Flyer
            "contact_email": email.strip(),
        }

        # Generiere Claude Post-Text
        post_text = claude_handler.generate_post_text(event)

        # Speichere in DB
        eid = db.add_event(
            source=event["source"],
            source_id=event["source_id"],
            title=event["title"],
            description=event["description"],
            image_url=event["image_url"],
            event_date=event["event_date"],
            location=event["location"],
            city=event["city"],
            url=event["url"],
            post_text=post_text,
            contact_email=event["contact_email"],
        )

        logger.info(f"Web-Form Event eingereicht: {event['title']} (ID: {eid})")

        return JSONResponse(
            {"status": "success", "event_id": eid},
            status_code=200
        )

    except ValueError as e:
        return JSONResponse(
            {"detail": str(e)},
            status_code=400
        )
    except Exception as e:
        logger.exception("Fehler beim Web-Form Submit")
        return JSONResponse(
            {"detail": f"Fehler beim Speichern des Events: {str(e)}"},
            status_code=500
        )
