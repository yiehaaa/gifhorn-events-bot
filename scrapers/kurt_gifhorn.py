"""
Kurt Gifhorn: Lokales Magazin Blog-Scraper
https://kurt-gifhorn.de/
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from scrapers._normalize import base_event, parse_de_date, to_event_timestamp

logger = logging.getLogger(__name__)


class KurtGifhornScraper:
    def __init__(self) -> None:
        self.base_url = "https://kurt-gifhorn.de"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0; +local)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        """Scrape blog articles from Kurt homepage."""
        events: List[Dict[str, Any]] = []

        try:
            r = self.session.get(self.base_url, timeout=15)
            if r.status_code != 200:
                logger.error(f"❌ Kurt: HTTP {r.status_code}")
                return events

            soup = BeautifulSoup(r.content, "html.parser")
            main = soup.find("main")
            if not main:
                logger.warning("Kurt: <main> tag not found")
                return events

            # Find all article links in main
            article_links = main.find_all("a", href=re.compile(r"/blog/"))

            for link in article_links:
                try:
                    article_url = link.get("href", "").strip()
                    if not article_url:
                        continue

                    # Make absolute URL
                    if not article_url.startswith("http"):
                        article_url = self.base_url + article_url

                    # Extract event info from link structure
                    title_elem = link.find("h2") or link.find("h1") or link.find("h3")
                    title = title_elem.text.strip() if title_elem else "Ohne Titel"

                    # Get category from link structure
                    category_elem = link.find("div", class_=re.compile(r"category|tag"))
                    category = category_elem.text.strip() if category_elem else "Veranstaltung"

                    # Extract date from link structure (look for date pattern)
                    date_elem = link.find("div", class_=re.compile(r"date|time"))
                    date_text = date_elem.text.strip() if date_elem else ""

                    # Also try finding date in generic "generic" divs
                    if not date_text:
                        for generic in link.find_all("generic"):
                            text = generic.text.strip()
                            # Match DD.MM.YYYY pattern
                            if re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text):
                                date_text = text
                                break

                    # Extract date using regex
                    date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_text)
                    event_date = None
                    if date_match:
                        day = int(date_match.group(1))
                        month = int(date_match.group(2))
                        year = int(date_match.group(3))
                        event_date = to_event_timestamp(
                            __import__("datetime").date(year, month, day), None
                        )
                    else:
                        event_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    # Get image if available
                    img = link.find("img")
                    image_url = img.get("src", "") if img else ""
                    if image_url and not image_url.startswith("http"):
                        image_url = self.base_url + image_url

                    # Get description (first 200 chars from paragraph if available)
                    desc_elem = link.find("p")
                    description = desc_elem.text.strip() if desc_elem else ""
                    description = description[:500]

                    # Create event dict
                    event = base_event(
                        source="kurt_gifhorn",
                        source_id=article_url.split("/")[-1],
                        title=title,
                        description=description,
                        image_url=image_url,
                        event_date=event_date,
                        location="Gifhorn",  # Default, extracted from title if possible
                        city="Gifhorn",
                        url=article_url,
                    )

                    events.append(event)

                except Exception as e:
                    logger.debug(f"Kurt: Parse error for article: {e}")
                    continue

            logger.info(f"✅ Kurt Gifhorn: {len(events)} events")

        except Exception as e:
            logger.error(f"❌ Kurt Gifhorn scraper error: {e}")

        return events


# Global instance
kurt_scraper = KurtGifhornScraper()
