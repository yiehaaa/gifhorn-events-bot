"""
Eventim: öffentliche Exploration-API (kann je nach IP/Header 403 liefern).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from scrapers._normalize import base_event

logger = logging.getLogger(__name__)

EXPLORATION = (
    "https://public-api.eventim.com/websearch/search/api/exploration/v1/productgroups"
)


class EventimScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0; +local)",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9",
                "Origin": "https://www.eventim.de",
                "Referer": "https://www.eventim.de/",
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for term in ("Gifhorn", "Wolfsburg", "Braunschweig"):
            try:
                r = self.session.get(
                    EXPLORATION,
                    params={"term": term, "page": 1, "pagesize": 40},
                    timeout=20,
                )
                if r.status_code != 200:
                    logger.warning(
                        "Eventim API %s: HTTP %s", term, r.status_code
                    )
                    continue
                data = r.json()
                items = (
                    data.get("productGroups")
                    or data.get("items")
                    or data.get("events")
                    or data.get("_embedded", {}).get("productGroups")
                    or []
                )
                if isinstance(items, dict):
                    items = list(items.values())
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    eid = item.get("id") or item.get("productGroupId") or item.get("code")
                    name = item.get("name") or item.get("title") or item.get("headline")
                    if not name or not eid:
                        continue
                    start = (
                        item.get("startDate")
                        or item.get("date")
                        or item.get("firstEventDate")
                    )
                    loc = item.get("location") or item.get("venue") or {}
                    if isinstance(loc, dict):
                        loc_name = loc.get("name") or loc.get("label") or ""
                        city = loc.get("city") or ""
                    else:
                        loc_name, city = str(loc), ""
                    url = item.get("url") or item.get("link")
                    if url and not str(url).startswith("http"):
                        url = "https://www.eventim.de" + str(url)
                    events.append(
                        base_event(
                            source="eventim",
                            source_id=f"{term}-{eid}",
                            title=str(name),
                            description=str(item.get("description", "") or "")[:2000],
                            image_url=str(item.get("imageUrl") or item.get("image", "") or "")[
                                :500
                            ],
                            event_date=str(start) if start else None,
                            location=str(loc_name)[:255],
                            city=str(city)[:100],
                            price_min=None,
                            price_max=None,
                            url=str(url or "")[:500],
                        )
                    )
                logger.info("Eventim %s: %s Roh-Einträge", term, len(items))
            except Exception as e:
                logger.error("Eventim (%s): %s", term, e)
        logger.info("Eventim gesamt: %s Events (nach Parsing)", len(events))
        return events


eventim_scraper = EventimScraper()
