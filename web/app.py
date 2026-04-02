"""
Lokales Web-Dashboard: Events, Freigaben, Logs.

Start:
  .venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8080

.env: DASHBOARD_PASSWORD (und optional DASHBOARD_USER)
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
import uuid

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from claude_handler import claude_handler
from config import DASHBOARD_PASSWORD, DASHBOARD_USER, EMAIL_ATTACHMENT_STORAGE_PATH, GOOGLE_FORM_URL
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
    logs = db.list_recent_logs(limit=35)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "events": events,
            "stats": stats,
            "logs": logs,
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
