"""
Hash- und Fuzzy-Deduplizierung für Events (siehe 01c-DEDUPLICATION).
"""

from __future__ import annotations

import hashlib
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List

from config import DEDUP_HASH_THRESHOLD

logger = logging.getLogger(__name__)


class EventDeduplicator:
    def __init__(self, fuzzy_threshold: float | None = None) -> None:
        """
        fuzzy_threshold: Wie ähnlich müssen Events sein? (0.0–1.0)
        """
        self.fuzzy_threshold = (
            fuzzy_threshold if fuzzy_threshold is not None else DEDUP_HASH_THRESHOLD
        )

    def generate_hash(self, event_data: Dict[str, Any]) -> str:
        """
        Hash aus title, event_date, location (normalisiert).
        """
        key_fields = [
            event_data.get("title", ""),
            event_data.get("event_date", ""),
            event_data.get("location", ""),
        ]
        normalized = "|".join(str(f).lower().strip() for f in key_fields)
        return hashlib.sha256(normalized.encode()).hexdigest()

    def fuzzy_compare(self, str1: str, str2: str) -> float:
        """Ähnlichkeit zweier Strings (0.0–1.0)."""
        matcher = SequenceMatcher(None, str1.lower(), str2.lower())
        return matcher.ratio()

    def is_duplicate(self, event1: Dict[str, Any], event2: Dict[str, Any]) -> bool:
        """Prüft, ob event1 ein Duplikat von event2 ist."""
        hash1 = self.generate_hash(event1)
        hash2 = self.generate_hash(event2)

        if hash1 == hash2:
            logger.info(
                "Duplikat erkannt (Hash): %s",
                event1.get("title", ""),
            )
            return True

        title_match = self.fuzzy_compare(
            str(event1.get("title", "")),
            str(event2.get("title", "")),
        )
        location_match = self.fuzzy_compare(
            str(event1.get("location", "")),
            str(event2.get("location", "")),
        )
        # Mittel aus Titel + Ort (wie Spezifikation)
        avg_fields = (title_match + location_match) / 2
        # Zusätzlich: ein kombinierter String (andere Schreibweisen, gleicher Abend/Ort)
        blob1 = f"{event1.get('title', '')} {event1.get('location', '')}"
        blob2 = f"{event2.get('title', '')} {event2.get('location', '')}"
        blob_match = self.fuzzy_compare(blob1, blob2)
        combined_score = max(avg_fields, blob_match)

        if combined_score >= self.fuzzy_threshold:
            logger.info(
                "Duplikat erkannt (Fuzzy): %s (Score: %.2f%%)",
                event1.get("title", ""),
                combined_score * 100,
            )
            return True

        # Gleicher Termin + sehr ähnlicher Ort + verwandter Titel (z. B. anderes Wording)
        same_date = str(event1.get("event_date", "")).strip() == str(
            event2.get("event_date", "")
        ).strip()
        if same_date and location_match >= 0.85 and title_match >= 0.55:
            logger.info(
                "Duplikat erkannt (Datum+Ort+Titel): %s",
                event1.get("title", ""),
            )
            return True

        return False

    def deduplicate_list(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Entfernt Duplikate aus einer Event-Liste (Reihenfolge: erstes Vorkommen bleibt)."""
        deduplicated: List[Dict[str, Any]] = []

        for event in events:
            is_dupe = False
            for existing in deduplicated:
                if self.is_duplicate(event, existing):
                    is_dupe = True
                    break

            if not is_dupe:
                deduplicated.append(event)
            else:
                logger.debug(
                    "Überspringen: %s (Duplikat)",
                    event.get("title", ""),
                )

        logger.info(
            "Deduplizierung: %s → %s Events",
            len(events),
            len(deduplicated),
        )
        return deduplicated


deduplicator = EventDeduplicator()
