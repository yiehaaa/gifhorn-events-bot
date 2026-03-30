"""
Stadthalle Gifhorn – Programm-Seite (tx_news / rowLatestStart).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from config import STADTHALLE_PROGRAM_URL
from scrapers._normalize import base_event, ensure_url, parse_de_month_date, to_event_timestamp

logger = logging.getLogger(__name__)


class StadthalleScraper:
    def __init__(self) -> None:
        self.url = STADTHALLE_PROGRAM_URL
        self.base = "https://www.stadthalle-gifhorn.de"

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

            for row in soup.select("div.row.rowLatestStart"):
                date_el = row.select_one(".newsDate")
                h3 = row.select_one("h3.newsLatest, h3[itemprop=headline]")
                link = row.select_one('a[href*="tx_news_pi1"]')
                if not h3 or not link:
                    continue

                title = h3.get_text(strip=True)
                href = ensure_url(self.base, link.get("href"))
                m = re.search(r"\[news\]=(\d+)", href) or re.search(
                    r"news%5D=(\d+)", href
                )
                news_id = m.group(1) if m else re.sub(r"\W+", "", href)[-20:]

                date_raw = date_el.get_text(separator=" ", strip=True) if date_el else ""
                d = parse_de_month_date(date_raw)

                teaser = row.select_one(".rowNewsTeaser [itemprop=description]")
                desc = teaser.get_text(" ", strip=True) if teaser else ""

                img = row.select_one(".newsImage[style*='background-image']")
                image_url = ""
                if img and img.get("style"):
                    m2 = re.search(r"url\(['\"]?([^'\")]+)", img["style"])
                    if m2:
                        image_url = m2.group(1)
                        if image_url.startswith("//"):
                            image_url = "https:" + image_url

                events.append(
                    base_event(
                        source="stadthalle",
                        source_id=f"sh-{news_id}",
                        title=title,
                        description=desc[:2000],
                        image_url=image_url[:500],
                        event_date=to_event_timestamp(d, None),
                        location="Stadthalle Gifhorn",
                        city="Gifhorn",
                        url=href[:500],
                    )
                )

            logger.info("Stadthalle: %s Events", len(events))
        except Exception as e:
            logger.error("Stadthalle: %s", e)
        return events


stadthalle_scraper = StadthalleScraper()
