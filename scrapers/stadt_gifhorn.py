"""
Stadt Gifhorn: Veranstaltungskalender Scraper
https://www.stadt-gifhorn.de/freizeit-tourismus/veranstaltungen
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


class StadtGifhornScraper:
    def __init__(self) -> None:
        self.base_url = "https://www.stadt-gifhorn.de/freizeit-tourismus/veranstaltungen"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0; +local)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        """Scrape events from Stadt Gifhorn Veranstaltungskalender."""
        events: List[Dict[str, Any]] = []

        try:
            r = self.session.get(self.base_url, timeout=15)
            if r.status_code != 200:
                logger.error(f"❌ Stadt Gifhorn: HTTP {r.status_code}")
                return events

            soup = BeautifulSoup(r.content, "html.parser")

            # Find all event containers (usually <div> or <article> with event info)
            # Look for common patterns: news items, event cards
            event_containers = soup.find_all("div", class_=re.compile(r"news|event|item|card"))

            if not event_containers:
                # Fallback: look for any links with news parameters
                event_containers = soup.find_all("a", href=re.compile(r"tx_news_pi1"))

            for container in event_containers:
                try:
                    # Extract title
                    title_elem = container.find("h3") or container.find("h2") or container.find("h1")
                    if not title_elem:
                        title_elem = container.find("a")
                    title = title_elem.text.strip() if title_elem else None

                    if not title:
                        continue

                    # Extract event URL
                    link_elem = container.find("a", href=True)
                    event_url = link_elem.get("href") if link_elem else ""
                    if event_url and not event_url.startswith("http"):
                        event_url = "https://www.stadt-gifhorn.de" + event_url

                    # Extract date and time
                    # Look for pattern: "Am DD.MM.YYYY um HH:MM im Ort"
                    date_text = ""
                    time_text = ""
                    location = "Gifhorn"

                    date_elem = container.find("p")
                    if date_elem:
                        date_text = date_elem.text.strip()

                    # Parse date format: "Am 30.04.2026 um 16 Uhr im Lesesaal"
                    date_match = re.search(
                        r"Am\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s+um\s+(\d{1,2}):?(\d{2})?\s*(Uhr)?\s*(?:im|in)\s+(.+?)(?:\s*\||\s*$)",
                        date_text
                    )
                    event_date = None
                    if date_match:
                        day = int(date_match.group(1))
                        month = int(date_match.group(2))
                        year = int(date_match.group(3))
                        hour = int(date_match.group(4))
                        minute = int(date_match.group(5) or "0")
                        location = date_match.group(7).strip() if date_match.group(7) else "Gifhorn"

                        from datetime import date
                        event_date = to_event_timestamp(date(year, month, day), f"{hour}:{minute:02d}")
                    else:
                        # Fallback: try just date
                        date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_text)
                        if date_match:
                            day = int(date_match.group(1))
                            month = int(date_match.group(2))
                            year = int(date_match.group(3))
                            from datetime import date
                            event_date = to_event_timestamp(date(year, month, day), None)
                        else:
                            event_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    # Extract image if available
                    img = container.find("img")
                    image_url = img.get("src") if img else ""
                    if image_url and not image_url.startswith("http"):
                        image_url = "https://www.stadt-gifhorn.de" + image_url

                    # Get description
                    description = ""
                    desc_elem = container.find("p", class_=re.compile(r"text|description|excerpt"))
                    if not desc_elem:
                        desc_elem = container.find("p")
                        if desc_elem and desc_elem.text.strip() != date_text:
                            description = desc_elem.text.strip()
                    else:
                        description = desc_elem.text.strip()

                    description = description[:500]

                    # Create event dict
                    event = base_event(
                        source="stadt_gifhorn",
                        source_id=event_url.split("=")[-1] if "=" in event_url else title.replace(" ", "-"),
                        title=title,
                        description=description,
                        image_url=image_url,
                        event_date=event_date,
                        location=location,
                        city="Gifhorn",
                        url=event_url,
                    )

                    events.append(event)

                except Exception as e:
                    logger.debug(f"Stadt Gifhorn: Parse error: {e}")
                    continue

            logger.info(f"✅ Stadt Gifhorn: {len(events)} events")

        except Exception as e:
            logger.error(f"❌ Stadt Gifhorn scraper error: {e}")

        return events


# Global instance
stadt_gifhorn_scraper = StadtGifhornScraper()
