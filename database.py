"""
DB-Schicht:
- PostgreSQL, wenn `DATABASE_URL` gesetzt ist
- sonst lokal SQLite (Fallback) für `MOCK_MODE=1` und erste Tests.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2 import IntegrityError
from psycopg2.extras import Json, RealDictCursor

from config import DATABASE_URL, SQLITE_PATH

logger = logging.getLogger(__name__)

_BERLIN = ZoneInfo("Europe/Berlin")


def _created_at_to_berlin_date(val: Any) -> date:
    """created_at aus DB → Datum in Europe/Berlin (naive Zeit = UTC)."""
    if val is None:
        return date.min
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(_BERLIN).date()
    if isinstance(val, str):
        try:
            raw = val.replace("Z", "+00:00")
            if "T" in raw:
                dt = datetime.fromisoformat(raw[:26])
            else:
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt.astimezone(_BERLIN).date()
        except (ValueError, TypeError):
            pass
    return date.min


class Database:
    def __init__(self) -> None:
        self.conn: Optional[Any] = None
        self.mode: str = "pg" if DATABASE_URL else "sqlite"

    def connect(self) -> None:
        if self.mode == "pg":
            if not DATABASE_URL:
                raise RuntimeError("DATABASE_URL fehlt, aber Modus=pg")
            self.conn = psycopg2.connect(DATABASE_URL)
            logger.info("PostgreSQL verbunden")
            return

        # FastAPI kann Requests über Threads verteilen.
        # SQLite-Connection muss daher thread-safe konfiguriert sein.
        self.conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info("SQLite verbunden: %s", SQLITE_PATH)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _ensure_conn(self) -> None:
        if not self.conn:
            raise RuntimeError("Database not connected; call connect() first")

    def create_tables(self) -> None:
        self._ensure_conn()

        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                      id SERIAL PRIMARY KEY,
                      source VARCHAR(50),
                      source_id VARCHAR(255) UNIQUE,
                      title VARCHAR(500) NOT NULL,
                      description TEXT,
                      image_url VARCHAR(500),
                      event_date TIMESTAMP NOT NULL,
                      location VARCHAR(255),
                      city VARCHAR(100),
                      price_min DECIMAL(8,2),
                      price_max DECIMAL(8,2),
                      url VARCHAR(500),
                      post_text TEXT,
                      posted_at TIMESTAMP,
                      posted_to_instagram BOOLEAN DEFAULT FALSE,
                      posted_to_facebook BOOLEAN DEFAULT FALSE,
                      event_hash VARCHAR(64),
                      canonical_id INT REFERENCES events(id),
                      created_at TIMESTAMP DEFAULT NOW(),
                      updated_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS posts (
                      id SERIAL PRIMARY KEY,
                      event_id INT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                      post_text TEXT NOT NULL,
                      image_url VARCHAR(500),
                      status VARCHAR(50),
                      instagram_post_id VARCHAR(255),
                      facebook_post_id VARCHAR(255),
                      instagram_url VARCHAR(500),
                      facebook_url VARCHAR(500),
                      created_at TIMESTAMP DEFAULT NOW(),
                      approved_at TIMESTAMP,
                      posted_at TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS logs (
                      id SERIAL PRIMARY KEY,
                      level VARCHAR(20),
                      message TEXT,
                      context JSONB,
                      created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )

                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_source_id ON events(source_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_event_hash ON events(event_hash)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_posts_event_id ON posts(event_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)"
                )

                cur.execute(
                    """
                    ALTER TABLE events ADD COLUMN IF NOT EXISTS approved_for_social BOOLEAN DEFAULT FALSE
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE events ADD COLUMN IF NOT EXISTS telegram_rejected BOOLEAN DEFAULT FALSE
                    """
                )

                # Email Submission Tables (neu)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS email_sender_whitelist (
                      id SERIAL PRIMARY KEY,
                      email_pattern VARCHAR(255) NOT NULL UNIQUE,
                      organization_name VARCHAR(255),
                      score_boost FLOAT DEFAULT 1.0,
                      created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS email_submissions (
                      id SERIAL PRIMARY KEY,
                      gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
                      sender_email VARCHAR(255) NOT NULL,
                      sender_name VARCHAR(255),
                      subject VARCHAR(500) NOT NULL,
                      body_text TEXT,
                      attachment_urls JSONB,
                      screening_score FLOAT,
                      matched_filters JSONB,
                      approval_status VARCHAR(50) DEFAULT 'pending',
                      approved_by VARCHAR(255),
                      approved_at TIMESTAMP,
                      approved_post_text TEXT,
                      converted_to_event_id INT REFERENCES events(id),
                      created_at TIMESTAMP DEFAULT NOW(),
                      updated_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )

                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_email_submissions_status ON email_submissions(approval_status)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_email_submissions_sender ON email_submissions(sender_email)"
                )
                cur.execute(
                    """
                    ALTER TABLE email_submissions
                    ADD COLUMN IF NOT EXISTS ingest_batch_id VARCHAR(32)
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE events
                    ADD COLUMN IF NOT EXISTS evening_preview_sent BOOLEAN DEFAULT FALSE
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE events
                    ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255)
                    """
                )

            self.conn.commit()
            logger.info("Tabellen erstellt/überprüft (Postgres)")
            return

        # SQLite schema
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT,
                  source_id TEXT UNIQUE,
                  title TEXT NOT NULL,
                  description TEXT,
                  image_url TEXT,
                  event_date TEXT NOT NULL,
                  location TEXT,
                  city TEXT,
                  price_min REAL,
                  price_max REAL,
                  url TEXT,
                  post_text TEXT,
                  posted_at TEXT,
                  posted_to_instagram INTEGER DEFAULT 0,
                  posted_to_facebook INTEGER DEFAULT 0,
                  event_hash TEXT,
                  canonical_id INTEGER,
                  approved_for_social INTEGER DEFAULT 0,
                  telegram_rejected INTEGER DEFAULT 0,
                  contact_email TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_id INTEGER,
                  post_text TEXT NOT NULL,
                  image_url TEXT,
                  status TEXT,
                  instagram_post_id TEXT,
                  facebook_post_id TEXT,
                  instagram_url TEXT,
                  facebook_url TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  approved_at TEXT,
                  posted_at TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  level TEXT,
                  message TEXT,
                  context TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_sender_whitelist (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email_pattern TEXT UNIQUE NOT NULL,
                  organization_name TEXT,
                  score_boost REAL DEFAULT 1.0,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_submissions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  gmail_message_id TEXT UNIQUE NOT NULL,
                  sender_email TEXT NOT NULL,
                  sender_name TEXT,
                  subject TEXT NOT NULL,
                  body_text TEXT,
                  attachment_urls TEXT,
                  screening_score REAL,
                  matched_filters TEXT,
                  approval_status TEXT DEFAULT 'pending',
                  approved_by TEXT,
                  approved_at TEXT,
                  approved_post_text TEXT,
                  converted_to_event_id INTEGER,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for _alter in (
                "ALTER TABLE email_submissions ADD COLUMN ingest_batch_id TEXT",
                "ALTER TABLE events ADD COLUMN evening_preview_sent INTEGER DEFAULT 0",
                "ALTER TABLE events ADD COLUMN contact_email TEXT",
            ):
                try:
                    self.conn.execute(_alter)
                except sqlite3.OperationalError:
                    pass
        logger.info("Tabellen erstellt/überprüft (SQLite)")

    def add_event(
        self,
        source: str,
        source_id: str,
        title: str,
        description: str,
        image_url: str,
        event_date: Union[str, datetime],
        location: str,
        city: str,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        url: Optional[str] = None,
        post_text: Optional[str] = None,
        contact_email: Optional[str] = None,
    ) -> Optional[int]:
        self._ensure_conn()

        if isinstance(event_date, datetime):
            event_date_param = event_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            event_date_param = str(event_date)

        if self.mode == "pg":
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO events
                        (source, source_id, title, description, image_url,
                         event_date, location, city, price_min, price_max, url, post_text, contact_email, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        RETURNING id
                        """,
                        (
                            source,
                            source_id,
                            title,
                            description,
                            image_url,
                            event_date_param,
                            location,
                            city,
                            price_min,
                            price_max,
                            url,
                            post_text,
                            contact_email,
                        ),
                    )
                    row = cur.fetchone()
                self.conn.commit()
                return int(row[0]) if row else None
            except IntegrityError:
                self.conn.rollback()
                logger.warning("Event %s existiert bereits (source_id)", source_id)
                return None

        # sqlite
        try:
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO events
                    (source, source_id, title, description, image_url,
                     event_date, location, city, price_min, price_max, url, post_text, contact_email, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        source,
                        source_id,
                        title,
                        description,
                        image_url,
                        event_date_param,
                        location,
                        city,
                        price_min,
                        price_max,
                        url,
                        post_text,
                        contact_email,
                    ),
                )
                return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            logger.warning("Event %s existiert bereits (source_id)", source_id)
            return None

    def get_pending_events(self) -> List[Dict[str, Any]]:
        return self.get_events_awaiting_telegram()

    def get_events_awaiting_telegram(self) -> List[Dict[str, Any]]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM events
                    WHERE posted_at IS NULL
                      AND COALESCE(approved_for_social, FALSE) = FALSE
                      AND COALESCE(telegram_rejected, FALSE) = FALSE
                    ORDER BY event_date ASC
                    LIMIT 20
                    """
                )
                return [dict(r) for r in cur.fetchall()]

        rows = self.conn.execute(
            """
            SELECT * FROM events
            WHERE posted_at IS NULL
              AND COALESCE(approved_for_social, 0) = 0
              AND COALESCE(telegram_rejected, 0) = 0
            ORDER BY event_date ASC
            LIMIT 20
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_ready_for_meta(self) -> List[Dict[str, Any]]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM events
                    WHERE posted_at IS NULL
                      AND COALESCE(approved_for_social, FALSE) = TRUE
                      AND COALESCE(telegram_rejected, FALSE) = FALSE
                    ORDER BY event_date ASC
                    LIMIT 50
                    """
                )
                return [dict(r) for r in cur.fetchall()]

        rows = self.conn.execute(
            """
            SELECT * FROM events
            WHERE posted_at IS NULL
              AND COALESCE(approved_for_social, 0) = 1
              AND COALESCE(telegram_rejected, 0) = 0
            ORDER BY event_date ASC
            LIMIT 50
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_event_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
                row = cur.fetchone()
            return dict(row) if row else None

        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def set_telegram_approval(self, event_id: int, approved: bool) -> None:
        self._ensure_conn()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                if approved:
                    cur.execute(
                        """
                        UPDATE events
                        SET approved_for_social = TRUE,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE events
                        SET telegram_rejected = TRUE,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
            self.conn.commit()
            return

        with self.conn:
            if approved:
                self.conn.execute(
                    """
                    UPDATE events
                    SET approved_for_social = 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, event_id),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE events
                    SET telegram_rejected = 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, event_id),
                )

    def mark_event_posted(
        self, event_id: int, instagram: bool = False, facebook: bool = False
    ) -> None:
        self._ensure_conn()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE events
                    SET posted_at = NOW(),
                        posted_to_instagram = %s,
                        posted_to_facebook = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (instagram, facebook, event_id),
                )
            self.conn.commit()
            return

        with self.conn:
            self.conn.execute(
                """
                UPDATE events
                SET posted_at = ?,
                    posted_to_instagram = ?,
                    posted_to_facebook = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, int(bool(instagram)), int(bool(facebook)), now, event_id),
            )

    def list_events_dashboard(
        self, status_filter: str = "all", limit: int = 200
    ) -> List[Dict[str, Any]]:
        self._ensure_conn()

        if self.mode == "pg":
            cond = "1=1"
            if status_filter == "awaiting_telegram":
                cond = """
                    posted_at IS NULL
                    AND COALESCE(approved_for_social, FALSE) = FALSE
                    AND COALESCE(telegram_rejected, FALSE) = FALSE
                """
            elif status_filter == "ready_meta":
                cond = """
                    posted_at IS NULL
                    AND COALESCE(approved_for_social, FALSE) = TRUE
                    AND COALESCE(telegram_rejected, FALSE) = FALSE
                """
            elif status_filter == "posted":
                cond = "posted_at IS NOT NULL"
            elif status_filter == "rejected":
                cond = "COALESCE(telegram_rejected, FALSE) = TRUE"

            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM events
                    WHERE {cond}
                    ORDER BY event_date DESC NULLS LAST, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]

        # sqlite
        if status_filter == "awaiting_telegram":
            where = """
              posted_at IS NULL
              AND COALESCE(approved_for_social, 0) = 0
              AND COALESCE(telegram_rejected, 0) = 0
            """
        elif status_filter == "ready_meta":
            where = """
              posted_at IS NULL
              AND COALESCE(approved_for_social, 0) = 1
              AND COALESCE(telegram_rejected, 0) = 0
            """
        elif status_filter == "posted":
            where = "posted_at IS NOT NULL"
        elif status_filter == "rejected":
            where = "COALESCE(telegram_rejected, 0) = 1"
        else:
            where = "1=1"

        rows = self.conn.execute(
            f"""
            SELECT * FROM events
            WHERE {where}
            ORDER BY event_date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def dashboard_stats(self) -> Dict[str, int]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (
                        WHERE posted_at IS NULL
                          AND COALESCE(approved_for_social, FALSE) = FALSE
                          AND COALESCE(telegram_rejected, FALSE) = FALSE
                      ) AS awaiting,
                      COUNT(*) FILTER (
                        WHERE posted_at IS NULL
                          AND COALESCE(approved_for_social, FALSE) = TRUE
                          AND COALESCE(telegram_rejected, FALSE) = FALSE
                      ) AS ready,
                      COUNT(*) FILTER (WHERE posted_at IS NOT NULL) AS posted,
                      COUNT(*) FILTER (WHERE COALESCE(telegram_rejected, FALSE)) AS rejected,
                      COUNT(*) AS total
                    FROM events
                    """
                )
                row = cur.fetchone()
            if not row:
                return {"awaiting": 0, "ready": 0, "posted": 0, "rejected": 0, "total": 0}
            return {
                "awaiting": int(row[0] or 0),
                "ready": int(row[1] or 0),
                "posted": int(row[2] or 0),
                "rejected": int(row[3] or 0),
                "total": int(row[4] or 0),
            }

        row = self.conn.execute(
            """
            SELECT
              SUM(CASE WHEN posted_at IS NULL
                        AND COALESCE(approved_for_social, 0) = 0
                        AND COALESCE(telegram_rejected, 0) = 0
                       THEN 1 ELSE 0 END) AS awaiting,
              SUM(CASE WHEN posted_at IS NULL
                        AND COALESCE(approved_for_social, 0) = 1
                        AND COALESCE(telegram_rejected, 0) = 0
                       THEN 1 ELSE 0 END) AS ready,
              SUM(CASE WHEN posted_at IS NOT NULL THEN 1 ELSE 0 END) AS posted,
              SUM(CASE WHEN COALESCE(telegram_rejected, 0) = 1 THEN 1 ELSE 0 END) AS rejected,
              COUNT(*) AS total
            FROM events
            """
        ).fetchone()

        return {
            "awaiting": int(row[0] or 0),
            "ready": int(row[1] or 0),
            "posted": int(row[2] or 0),
            "rejected": int(row[3] or 0),
            "total": int(row[4] or 0),
        }

    def list_recent_logs(self, limit: int = 40) -> List[Dict[str, Any]]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, level, message, context, created_at
                    FROM logs
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]

        rows = self.conn.execute(
            """
            SELECT id, level, message, context, created_at
            FROM logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def log_message(
        self,
        level: str,
        message: str,
        context: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> None:
        self._ensure_conn()
        ctx: Any
        if context is None:
            ctx = None
        elif isinstance(context, dict):
            ctx = context
        else:
            ctx = {"raw": context}

        if self.mode == "pg":
            ctx_pg = Json(ctx) if ctx is not None else None
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO logs (level, message, context, created_at)
                    VALUES (%s, %s, %s, NOW())
                    """,
                    (level, message, ctx_pg),
                )
            self.conn.commit()
            return

        ctx_sqlite = json.dumps(ctx) if ctx is not None else None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO logs (level, message, context, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (level, message, ctx_sqlite),
            )

    def add_email_submission(
        self,
        gmail_message_id: str,
        sender_email: str,
        subject: str,
        body_text: Optional[str] = None,
        sender_name: Optional[str] = None,
        attachment_urls: Optional[Dict[str, str]] = None,
        screening_score: Optional[float] = None,
        matched_filters: Optional[Dict[str, Any]] = None,
        ingest_batch_id: Optional[str] = None,
    ) -> Optional[int]:
        """Speichert eine Email-Submission in die DB"""
        self._ensure_conn()

        if self.mode == "pg":
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO email_submissions
                        (gmail_message_id, sender_email, sender_name, subject, body_text,
                         attachment_urls, screening_score, matched_filters, approval_status,
                         ingest_batch_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, NOW())
                        RETURNING id
                        """,
                        (
                            gmail_message_id,
                            sender_email,
                            sender_name,
                            subject,
                            body_text,
                            Json(attachment_urls) if attachment_urls else None,
                            screening_score,
                            Json(matched_filters) if matched_filters else None,
                            ingest_batch_id,
                        ),
                    )
                    row = cur.fetchone()
                self.conn.commit()
                return int(row[0]) if row else None
            except IntegrityError:
                self.conn.rollback()
                logger.warning("Email %s bereits in DB", gmail_message_id)
                return None
        else:
            try:
                with self.conn:
                    cur = self.conn.execute(
                        """
                        INSERT INTO email_submissions
                        (gmail_message_id, sender_email, sender_name, subject, body_text,
                         attachment_urls, screening_score, matched_filters, approval_status,
                         ingest_batch_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            gmail_message_id,
                            sender_email,
                            sender_name,
                            subject,
                            body_text,
                            json.dumps(attachment_urls) if attachment_urls else None,
                            screening_score,
                            json.dumps(matched_filters) if matched_filters else None,
                            ingest_batch_id,
                        ),
                    )
                    return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                logger.warning("Email %s bereits in DB", gmail_message_id)
                return None

    def get_pending_email_submissions(self) -> List[Dict[str, Any]]:
        """Hole alle unbearbeiteten Email-Submissions"""
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM email_submissions
                    WHERE approval_status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                )
                return [dict(r) for r in cur.fetchall()]

        rows = self.conn.execute(
            """
            SELECT * FROM email_submissions
            WHERE approval_status = 'pending'
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_email_sender_whitelist_patterns(self) -> List[str]:
        """Alle gespeicherten Sender-Regex-Patterns (zusätzlich zu EMAIL_SENDER_PATTERNS in .env)."""
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT email_pattern FROM email_sender_whitelist ORDER BY id ASC"
                )
                return [r[0] for r in cur.fetchall()]
        rows = self.conn.execute(
            "SELECT email_pattern FROM email_sender_whitelist ORDER BY id ASC"
        ).fetchall()
        return [r[0] for r in rows]

    def upsert_email_sender_whitelist(
        self,
        email_pattern: str,
        organization_name: Optional[str] = None,
        score_boost: float = 1.0,
    ) -> None:
        """Pattern idempotent einfügen oder Metadaten aktualisieren."""
        self._ensure_conn()
        pat = (email_pattern or "").strip()
        if not pat:
            return
        org = (organization_name or "").strip() or None
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_sender_whitelist (email_pattern, organization_name, score_boost)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email_pattern) DO UPDATE SET
                        organization_name = EXCLUDED.organization_name,
                        score_boost = EXCLUDED.score_boost
                    """,
                    (pat, org, score_boost),
                )
            self.conn.commit()
        else:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO email_sender_whitelist (email_pattern, organization_name, score_boost)
                    VALUES (?, ?, ?)
                    ON CONFLICT(email_pattern) DO UPDATE SET
                        organization_name = excluded.organization_name,
                        score_boost = excluded.score_boost
                    """,
                    (pat, org or "", score_boost),
                )

    def get_email_submission_by_id(self, submission_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM email_submissions WHERE id = %s", (submission_id,)
                )
                row = cur.fetchone()
            return dict(row) if row else None

        row = self.conn.execute(
            "SELECT * FROM email_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_approved_emails_pending_conversion(self) -> List[Dict[str, Any]]:
        """Freigegeben, aber noch kein Event (Claude / Meta-Pipeline)."""
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM email_submissions
                    WHERE approval_status = 'approved'
                      AND converted_to_event_id IS NULL
                    ORDER BY id ASC
                    LIMIT 50
                    """
                )
                return [dict(r) for r in cur.fetchall()]

        rows = self.conn.execute(
            """
            SELECT * FROM email_submissions
            WHERE approval_status = 'approved'
              AND converted_to_event_id IS NULL
            ORDER BY id ASC
            LIMIT 50
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def set_email_approval(
        self,
        email_submission_id: int,
        approved: bool,
        approved_by: str = "telegram",
        approved_post_text: Optional[str] = None,
    ) -> None:
        """Setzt Genehmigungsstatus für Email-Submission"""
        self._ensure_conn()
        status = "approved" if approved else "rejected"

        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_submissions
                    SET approval_status = %s,
                        approved_by = %s,
                        approved_post_text = %s,
                        approved_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, approved_by, approved_post_text, email_submission_id),
                )
            self.conn.commit()
        else:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE email_submissions
                    SET approval_status = ?,
                        approved_by = ?,
                        approved_post_text = ?,
                        approved_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status, approved_by, approved_post_text, now, now, email_submission_id),
                )

    def link_email_to_event(self, email_submission_id: int, event_id: int) -> None:
        """Verknüpft Email-Submission mit erstelltem Event"""
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_submissions
                    SET converted_to_event_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (event_id, email_submission_id),
                )
            self.conn.commit()
        else:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE email_submissions
                    SET converted_to_event_id = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (event_id, now, email_submission_id),
                )

    def approve_email_submissions_by_batch(
        self, batch_hex: str, approved_by: str = "telegram"
    ) -> int:
        """Alle noch pending Mails dieser Tages-Batch freigeben (ingest_batch_id = 32 hex)."""
        if not batch_hex or len(batch_hex) != 32:
            return 0
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_submissions
                    SET approval_status = 'approved',
                        approved_by = %s,
                        approved_at = NOW(),
                        updated_at = NOW()
                    WHERE ingest_batch_id = %s AND approval_status = 'pending'
                    """,
                    (approved_by, batch_hex),
                )
                n = cur.rowcount
            self.conn.commit()
            return int(n)

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE email_submissions
                SET approval_status = 'approved',
                    approved_by = ?,
                    approved_at = ?,
                    updated_at = ?
                WHERE ingest_batch_id = ? AND approval_status = 'pending'
                """,
                (approved_by, now, now, batch_hex),
            )
        return int(cur.rowcount) if cur.rowcount is not None else 0

    def reject_email_submissions_by_batch(
        self, batch_hex: str, approved_by: str = "telegram"
    ) -> int:
        if not batch_hex or len(batch_hex) != 32:
            return 0
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE email_submissions
                    SET approval_status = 'rejected',
                        approved_by = %s,
                        approved_at = NOW(),
                        updated_at = NOW()
                    WHERE ingest_batch_id = %s AND approval_status = 'pending'
                    """,
                    (approved_by, batch_hex),
                )
                n = cur.rowcount
            self.conn.commit()
            return int(n)

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE email_submissions
                SET approval_status = 'rejected',
                    approved_by = ?,
                    approved_at = ?,
                    updated_at = ?
                WHERE ingest_batch_id = ? AND approval_status = 'pending'
                """,
                (approved_by, now, now, batch_hex),
            )
        return int(cur.rowcount) if cur.rowcount is not None else 0

    def get_email_derived_events_for_evening_preview(
        self, berlin_day: date
    ) -> List[Dict[str, Any]]:
        """
        Aus Mails erzeugte Beiträge: warten auf Freigabe, Abend-Übersicht noch nicht gesendet,
        Erstellungsdatum (created_at) am berlin_day.
        """
        self._ensure_conn()
        if self.mode == "pg":
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM events
                    WHERE source = 'email_submission'
                      AND posted_at IS NULL
                      AND COALESCE(approved_for_social, FALSE) = FALSE
                      AND COALESCE(telegram_rejected, FALSE) = FALSE
                      AND COALESCE(evening_preview_sent, FALSE) = FALSE
                      AND post_text IS NOT NULL
                      AND TRIM(post_text) <> ''
                    ORDER BY id ASC
                    LIMIT 100
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM events
                WHERE source = 'email_submission'
                  AND posted_at IS NULL
                  AND COALESCE(approved_for_social, 0) = 0
                  AND COALESCE(telegram_rejected, 0) = 0
                  AND COALESCE(evening_preview_sent, 0) = 0
                  AND post_text IS NOT NULL
                  AND TRIM(post_text) <> ''
                ORDER BY id ASC
                LIMIT 100
                """
            ).fetchall()
            rows = [dict(r) for r in rows]

        out: List[Dict[str, Any]] = []
        for r in rows:
            if _created_at_to_berlin_date(r.get("created_at")) == berlin_day:
                out.append(r)
        return out[:20]

    def mark_evening_preview_sent(self, event_ids: List[int]) -> None:
        if not event_ids:
            return
        self._ensure_conn()
        if self.mode == "pg":
            ph = ",".join(["%s"] * len(event_ids))
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE events
                    SET evening_preview_sent = TRUE, updated_at = NOW()
                    WHERE id IN ({ph})
                    """,
                    event_ids,
                )
            self.conn.commit()
            return

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        q_marks = ",".join("?" * len(event_ids))
        with self.conn:
            self.conn.execute(
                f"""
                UPDATE events
                SET evening_preview_sent = 1, updated_at = ?
                WHERE id IN ({q_marks})
                """,
                (now, *event_ids),
            )


db = Database()
