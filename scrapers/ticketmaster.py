"""
Ticketmaster Discovery API (kostenlos mit Key).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from config import TICKETMASTER_API_KEY
from scrapers._normalize import base_event

logger = logging.getLogger(__name__)

BASE = "https://app.ticketmaster.com/discovery/v2"


class TicketmasterScraper:
    def get_events(self) -> List[Dict[str, Any]]:
        if not TICKETMASTER_API_KEY:
            logger.info("Ticketmaster: TICKETMASTER_API_KEY fehlt — übersprungen")
            return []

        now = datetime.now(timezone.utc)
        params = {
            "apikey": TICKETMASTER_API_KEY,
            "classificationName": "music,sports,arts,Miscellaneous",
            "geoPoint": "52.4889,10.5461",
            "radius": "50",
            "unit": "km",
            "size": 100,
            "sort": "date,asc",
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": (now + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        events: List[Dict[str, Any]] = []
        try:
            r = requests.get(f"{BASE}/events.json", params=params, timeout=20)
            if r.status_code != 200:
                logger.warning("Ticketmaster HTTP %s: %s", r.status_code, r.text[:200])
                return events
            data = r.json()
            for event in data.get("_embedded", {}).get("events", []):
                try:
                    pr = event.get("priceRanges") or []
                    mins = [p.get("min") for p in pr if p.get("min") is not None]
                    maxs = [p.get("max") for p in pr if p.get("max") is not None]
                    price_min = min(mins) if mins else None
                    price_max = max(maxs) if maxs else None

                    venues = event.get("_embedded", {}).get("venues", [])
                    venue = venues[0] if venues else {}
                    dt = (
                        event.get("dates", {})
                        .get("start", {})
                        .get("dateTime")
                    )
                    images = event.get("images") or []
                    img = next(
                        (i.get("url") for i in images if (i.get("width") or 0) >= 400),
                        images[0].get("url") if images else None,
                    )

                    events.append(
                        base_event(
                            source="ticketmaster",
                            source_id=event.get("id", "")[:255],
                            title=event.get("name", "Event"),
                            description=(event.get("info") or event.get("pleaseNote") or "")[
                                :2000
                            ],
                            image_url=(img or "")[:500],
                            event_date=dt,
                            location=(venue.get("name") or "")[:255],
                            city=(venue.get("city") or {}).get("name") or "",
                            price_min=price_min,
                            price_max=price_max,
                            url=(event.get("url") or "")[:500],
                        )
                    )
                except Exception as ex:
                    logger.debug("Ticketmaster Parse: %s", ex)
            logger.info("Ticketmaster: %s Events", len(events))
        except Exception as e:
            logger.error("Ticketmaster: %s", e)
        return events


ticketmaster_scraper = TicketmasterScraper()
