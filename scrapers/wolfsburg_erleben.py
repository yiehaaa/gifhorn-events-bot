"""
Wolfsburg erleben: Veranstaltungskalender Scraper
https://wolfsburg-erleben.de/event/
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


class WolfsburgErlebenScraper:
    def __init__(self) -> None:
        self.base_url = "https://wolfsburg-erleben.de"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GifhornEventsBot/1.0; +local)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        """Scrape events from Wolfsburg erleben Veranstaltungskalender."""
        events: List[Dict[str, Any]] = []

        try:
            r = self.session.get(self.base_url, timeout=15)
            if r.status_code != 200:
                logger.error(f"❌ Wolfsburg erleben: HTTP {r.status_code}")
                return events

            soup = BeautifulSoup(r.content, "html.parser")

            # Find all event cards: <div class="teaser-card result-item">
            event_cards = soup.find_all("div", class_=re.compile(r"teaser-card result-item"))

            for card in event_cards:
                try:
                    # Extract event URL and title
                    link = card.find("a", class_="teaser-card__link")
                    if not link:
                        continue

                    event_url = link.get("href", "").strip()
                    if not event_url.startswith("http"):
                        event_url = self.base_url + event_url

                    # Extract title from visually-hidden span: "Detailseite 'Title' öffnen"
                    title = ""
                    hidden_span = link.find("span", class_="visually-hidden")
                    if hidden_span:
                        title_raw = hidden_span.text.strip()
                        match = re.search(r"Detailseite\s*'([^']*)'\s*öffnen", title_raw)
                        if match:
                            title = match.group(1).strip()

                    if not title:
                        title = event_url.split("/")[-1].replace("-", " ").title()

                    # Initialize fields
                    date_text = ""
                    time_text = ""
                    category = ""
                    location = ""
                    image_url = ""

                    # Extract image from figure
                    figure = card.find("figure", class_="teaser-card__figure")
                    if figure:
                        img = figure.find("img")
                        if img:
                            image_url = img.get("src", "")
                            if image_url and not image_url.startswith("http"):
                                image_url = self.base_url + image_url

                    # Extract date from main div (format: "Title DD.MM.YYYY - DD.MM.YYYY")
                    main_div = card.find("div", class_="teaser-card__main")
                    if main_div:
                        main_text = main_div.text.strip()
                        # Extract start date (first DD.MM.YYYY)
                        date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", main_text)
                        if date_match:
                            date_text = f"{date_match.group(1)}.{date_match.group(2)}.{date_match.group(3)}"

                    # Extract time, category, location from info div
                    # Format: "X Termine\nHH:MM\n{optional whitespace}\nKategorie\n{optional whitespace}\nOrt mit Adresse"
                    info_div = card.find("div", class_="teaser-card__info")
                    if info_div:
                        info_text = info_div.text.strip()
                        # Extract time (HH:MM)
                        time_match = re.search(r"(\d{1,2}):(\d{2})", info_text)
                        if time_match:
                            time_text = f"{time_match.group(1)}:{time_match.group(2)}"

                        # Split by multiple whitespace/newlines to get parts
                        # Remove "X Termine" prefix and split remaining
                        parts = re.split(r"\s{2,}|\n\s*\n", info_text)
                        filtered_parts = [p.strip() for p in parts if p.strip() and not re.match(r"^\d+\s+Termine", p)]

                        if len(filtered_parts) > 0:
                            # First part usually has time + category mixed
                            first_part = filtered_parts[0]
                            # Remove time from first part to get category
                            category_text = re.sub(r"^\d{1,2}:\d{2}\s*", "", first_part).strip()
                            category = category_text

                        # Location is typically the last part (longest string with address)
                        if len(filtered_parts) > 1:
                            # Look for part with address (contains comma or "straße")
                            for part in reversed(filtered_parts):
                                if "," in part or re.search(r"straße|str\.", part, re.I):
                                    location = part
                                    break
                            # If not found, take last non-empty part
                            if not location and filtered_parts:
                                location = filtered_parts[-1]

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
                        source="wolfsburg_erleben",
                        source_id=event_url.split("/")[-1],
                        title=title,
                        description=category,
                        image_url=image_url,
                        event_date=event_date,
                        location=location or "Wolfsburg",
                        city="Wolfsburg",
                        url=event_url,
                    )

                    events.append(event)

                except Exception as e:
                    logger.debug(f"Wolfsburg erleben: Parse error: {e}")
                    continue

            logger.info(f"✅ Wolfsburg erleben: {len(events)} events")

        except Exception as e:
            logger.error(f"❌ Wolfsburg erleben scraper error: {e}")

        return events


# Global instance
wolfsburg_erleben_scraper = WolfsburgErlebenScraper()
