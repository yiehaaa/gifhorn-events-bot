"""
Südheide Gifhorn – Veranstaltungskalender (teaser-card auf TYPO3-Seite).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from config import SUEDHEIDE_EVENTS_URL
from scrapers._normalize import base_event, ensure_url, parse_de_date, to_event_timestamp

logger = logging.getLogger(__name__)


class SuedheideScraper:
    def __init__(self) -> None:
        self.url = SUEDHEIDE_EVENTS_URL
        self.base = "https://www.suedheide-gifhorn.de"

    def get_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        try:
            r = requests.get(
                self.url,
                timeout=25,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0)"},
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            seen: set[str] = set()

            for card in soup.select('div.teaser-card.result-item[data-type="Event"]'):
                link = card.select_one("a.teaser-card__link[href]")
                if not link:
                    continue
                href = link.get("href", "").strip()
                full = ensure_url(self.base, href)
                if full in seen:
                    continue
                seen.add(full)

                title_el = card.select_one(".teaser-card__header")
                title = (title_el.get_text(strip=True) if title_el else link.get("title") or "").strip()
                sub = card.select_one(".teaser-card__subheader")
                date_s = sub.get_text(strip=True) if sub else ""
                d = parse_de_date(date_s)

                time_s = ""
                for item in card.select(".teaser-line__item"):
                    icon = item.select_one('[data-original="time"]')
                    if icon:
                        tx = item.select_one(".teaser-line__text")
                        if tx:
                            time_s = tx.get_text(strip=True)
                        break

                loc = ""
                loc_el = card.select_one(
                    '.teaser-line__item[data-name="location"] .teaser-line__text'
                )
                if loc_el:
                    loc = loc_el.get_text(strip=True)

                img_el = card.select_one("img.teaser-card__img[src]")
                pic = img_el["src"] if img_el else ""
                if pic.startswith("//"):
                    pic = "https:" + pic

                gid = card.get("data-globalid") or re.sub(r"\W+", "-", full)[:80]

                events.append(
                    base_event(
                        source="suedheide",
                        source_id=str(gid),
                        title=title,
                        description="",
                        image_url=pic[:500],
                        event_date=to_event_timestamp(d, time_s),
                        location=loc[:255],
                        city="Gifhorn",
                        url=full[:500],
                    )
                )

            logger.info("Südheide: %s Events", len(events))
        except Exception as e:
            logger.error("Südheide: %s", e)
        return events


suedheide_scraper = SuedheideScraper()
