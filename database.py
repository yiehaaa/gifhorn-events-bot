"""
DB-Schicht:
- PostgreSQL, wenn `DATABASE_URL` gesetzt ist
- sonst lokal SQLite (Fallback) für `MOCK_MODE=1` und erste Tests.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import psycopg2
from psycopg2 import IntegrityError
from psycopg2.extras import Json, RealDictCursor

from config import DATABASE_URL, SQLITE_PATH

logger = logging.getLogger(__name__)


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
                         event_date, location, city, price_min, price_max, url, post_text, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                     event_date, location, city, price_min, price_max, url, post_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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


db = Database()
