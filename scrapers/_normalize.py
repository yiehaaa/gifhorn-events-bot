"""Hilfen für einheitliche Event-Dicts (→ DB / Dedup)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urljoin


def ensure_url(base: str, href: Optional[str]) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else urljoin(base, href)


def parse_de_date(d: str) -> Optional[date]:
    """DD.MM.YYYY"""
    d = (d or "").strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", d)
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def parse_de_month_date(s: str) -> Optional[date]:
    """z. B. '09. Apr. 2026' (auch Zeilenumbrüche)."""
    s = re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()
    m = re.match(r"^(\d{1,2})\.\s*([A-Za-zäÄöÖüÜß.]+)\s*(\d{4})$", s)
    if not m:
        return None
    mon_raw = m.group(2).lower().rstrip(".")
    prefix_map = [
        ("mär", 3),
        ("mrz", 3),
        ("jan", 1),
        ("feb", 2),
        ("apr", 4),
        ("mai", 5),
        ("jun", 6),
        ("jul", 7),
        ("aug", 8),
        ("sep", 9),
        ("okt", 10),
        ("nov", 11),
        ("dez", 12),
    ]
    month_num = None
    for pref, num in prefix_map:
        if mon_raw.startswith(pref):
            month_num = num
            break
    if not month_num:
        return None
    return date(int(m.group(3)), month_num, int(m.group(1)))


def to_event_timestamp(d: Optional[date], time_str: Optional[str]) -> str:
    """ISO für PostgreSQL TIMESTAMP."""
    if not d:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    t = (time_str or "").strip()
    hm = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if hm:
        return datetime(d.year, d.month, d.day, int(hm.group(1)), int(hm.group(2))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    return datetime(d.year, d.month, d.day, 12, 0).strftime("%Y-%m-%d %H:%M:%S")


def base_event(**kwargs: Any) -> Dict[str, Any]:
    """Minimalfelder für add_event / Dedup."""
    return {
        "source": kwargs.get("source", "unknown"),
        "source_id": str(kwargs.get("source_id", "")),
        "title": (kwargs.get("title") or "Ohne Titel")[:500],
        "description": kwargs.get("description") or "",
        "image_url": kwargs.get("image_url") or "",
        "event_date": kwargs.get("event_date")
        or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "location": kwargs.get("location") or "",
        "city": kwargs.get("city") or "",
        "price_min": kwargs.get("price_min"),
        "price_max": kwargs.get("price_max"),
        "url": kwargs.get("url") or "",
    }
