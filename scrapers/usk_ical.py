"""
USK Gifhorn (o. ä.) – iCal-Feed.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List

import requests
from icalendar import Calendar

from config import USK_ICAL_URL
from scrapers._normalize import base_event

logger = logging.getLogger(__name__)


class USKiCalScraper:
    def __init__(self) -> None:
        self.ical_url = USK_ICAL_URL

    def get_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        if not self.ical_url:
            logger.info("USK iCal: USK_ICAL_URL nicht gesetzt — übersprungen")
            return events
        try:
            r = requests.get(
                self.ical_url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0)"},
            )
            r.raise_for_status()
            cal = Calendar.from_ical(r.content)

            for component in cal.walk():
                if component.name != "VEVENT":
                    continue
                try:
                    uid = component.get("uid")
                    summary = component.get("summary")
                    title = str(summary) if summary else "Event"
                    uid_s = str(uid) if uid else title[:40]

                    dtstart = component.get("dtstart")
                    if not dtstart:
                        continue
                    raw = dtstart.dt
                    if isinstance(raw, datetime):
                        event_date = raw.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(raw, date):
                        event_date = datetime(raw.year, raw.month, raw.day, 12, 0).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    else:
                        event_date = str(raw)

                    loc = component.get("location")
                    location = str(loc) if loc else "USK Gifhorn"

                    desc = component.get("description")
                    description = str(desc) if desc else ""

                    url_c = component.get("url")
                    url = str(url_c) if url_c else ""

                    events.append(
                        base_event(
                            source="usk_ical",
                            source_id=uid_s[:255],
                            title=title[:500],
                            description=description[:2000],
                            image_url="",
                            event_date=event_date,
                            location=location[:255],
                            city="Gifhorn",
                            url=url[:500],
                        )
                    )
                except Exception as ex:
                    logger.debug("iCal VEVENT: %s", ex)

            logger.info("USK iCal: %s Events", len(events))
        except Exception as e:
            logger.error("iCal: %s", e)
        return events


usk_ical_scraper = USKiCalScraper()
