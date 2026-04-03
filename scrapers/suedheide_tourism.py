"""
Südheide Gifhorn Tourism: Veranstaltungskalender Scraper
https://www.suedheide-gifhorn.de/veranstaltungen
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from scrapers._normalize import base_event, to_event_timestamp

logger = logging.getLogger(__name__)


class SuedheideGifhornScraper:
    def __init__(self) -> None:
        self.base_url = "https://www.suedheide-gifhorn.de/veranstaltungen"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0; +local)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        """Scrape events from Südheide Gifhorn Veranstaltungskalender."""
        events: List[Dict[str, Any]] = []

        try:
            r = self.session.get(self.base_url, timeout=15)
            if r.status_code != 200:
                logger.error(f"❌ Südheide: HTTP {r.status_code}")
                return events

            soup = BeautifulSoup(r.content, "html.parser")

            # Find all event cards: <a class="teaser-card__link" href="/event/...">
            event_links = soup.find_all("a", class_="teaser-card__link", href=re.compile(r"/event/"))

            for link in event_links:
                try:
                    # Extract event URL
                    event_url = link.get("href", "").strip()
                    if not event_url.startswith("http"):
                        event_url = "https://www.suedheide-gifhorn.de" + event_url

                    # Extract title from visually-hidden span: "Detailseite 'Title' öffnen"
                    title = ""
                    hidden_span = link.find("span", class_="visually-hidden")
                    if hidden_span:
                        title_raw = hidden_span.text.strip()
                        # Extract title from "Detailseite 'Title' öffnen"
                        match = re.search(r"Detailseite\s*'([^']*)'\s*öffnen", title_raw)
                        if match:
                            title = match.group(1)

                    if not title:
                        title = event_url.split("/")[-1].replace("-", " ").title()

                    # Get parent card container
                    parent = link.parent
                    category = ""
                    location = ""
                    date_text = ""
                    time_text = ""
                    image_url = ""

                    if parent:
                        # Extract image from figure
                        figure = parent.find("figure", class_="teaser-card__figure")
                        if figure:
                            img = figure.find("img")
                            if img:
                                image_url = img.get("src", "")
                                if image_url and not image_url.startswith("http"):
                                    image_url = "https://www.suedheide-gifhorn.de" + image_url

                        # Extract date from main div (concatenated with title)
                        main_div = parent.find("div", class_="teaser-card__main")
                        if main_div:
                            main_text = main_div.text.strip()
                            # Date format: "Title03.04.2026" or "Title 03.04.2026"
                            date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", main_text)
                            if date_match:
                                date_text = f"{date_match.group(1)}.{date_match.group(2)}.{date_match.group(3)}"

                        # Extract time, category, location from info div
                        info_div = parent.find("div", class_="teaser-card__info")
                        if info_div:
                            info_text = info_div.text.strip()
                            # Format: "10:00 Ausstellung  Glockenpalast, Str. X"
                            # Time at start
                            time_match = re.match(r"^(\d{1,2}):(\d{2})", info_text)
                            if time_match:
                                time_text = f"{time_match.group(1)}:{time_match.group(2)}"

                            # Category: word after time, before location (often has multiple spaces)
                            # Split by multiple spaces or regex
                            parts = re.split(r"\s{2,}", info_text)
                            if len(parts) > 1:
                                # First part has time + category
                                first_part = parts[0]
                                category_match = re.sub(r"^\d{1,2}:\d{2}\s+", "", first_part)
                                category = category_match.strip()
                                # Rest is location
                                if len(parts) > 1:
                                    location = parts[1].strip()
                            elif time_text:
                                # No clear split, try to extract category manually
                                after_time = info_text[len(time_text):].strip()
                                # Take words until we hit a comma or street pattern
                                category_match = re.match(r"^([A-Za-zäöüß\s]+?)(?:\s+[0-9]|,|$)", after_time)
                                if category_match:
                                    category = category_match.group(1).strip()
                                    location = after_time[len(category):].strip()
                                else:
                                    # Fallback
                                    words = after_time.split()
                                    if words:
                                        category = words[0]
                                        location = " ".join(words[1:])

                    # Parse date (DD.MM.YYYY)
                    event_date = None
                    if date_text:
                        date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_text)
                        if date_match:
                            day = int(date_match.group(1))
                            month = int(date_match.group(2))
                            year = int(date_match.group(3))
                            from datetime import date
                            event_date = to_event_timestamp(date(year, month, day), time_text if time_text else None)

                    if not event_date:
                        event_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    # Create event dict
                    event = base_event(
                        source="suedheide_tourism",
                        source_id=event_url.split("/")[-1],
                        title=title,
                        description=category,
                        image_url=image_url,
                        event_date=event_date,
                        location=location or "Gifhorn",
                        city="Gifhorn",
                        url=event_url,
                    )

                    events.append(event)

                except Exception as e:
                    logger.debug(f"Südheide: Parse error: {e}")
                    continue

            logger.info(f"✅ Südheide Gifhorn Tourism: {len(events)} events")

        except Exception as e:
            logger.error(f"❌ Südheide Gifhorn scraper error: {e}")

        return events


# Global instance
suedheide_tourism_scraper = SuedheideGifhornScraper()
