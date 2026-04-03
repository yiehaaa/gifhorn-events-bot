"""
Datenquellen Phase 2 — einzelne Scraper + Sammelfunktion.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


def collect_all_events() -> List[Dict[str, Any]]:
    """Alle konfigurierten Quellen; Fehler pro Quelle isoliert."""
    from scrapers.eventim import eventim_scraper
    from scrapers.kurt_gifhorn import kurt_scraper
    from scrapers.stadt_gifhorn import stadt_gifhorn_scraper
    from scrapers.stadthalle import stadthalle_scraper
    from scrapers.suedheide import suedheide_scraper
    from scrapers.suedheide_tourism import suedheide_tourism_scraper
    from scrapers.ticketmaster import ticketmaster_scraper
    from scrapers.usk_ical import usk_ical_scraper
    from scrapers.wolfsburg_erleben import wolfsburg_erleben_scraper

    sources: List[tuple[str, Callable[[], List[Dict[str, Any]]]]] = [
        ("kurt_gifhorn", kurt_scraper.get_events),
        ("stadt_gifhorn", stadt_gifhorn_scraper.get_events),
        ("suedheide_tourism", suedheide_tourism_scraper.get_events),
        ("wolfsburg_erleben", wolfsburg_erleben_scraper.get_events),
        ("suedheide", suedheide_scraper.get_events),
        ("stadthalle", stadthalle_scraper.get_events),
        ("usk_ical", usk_ical_scraper.get_events),
        ("ticketmaster", ticketmaster_scraper.get_events),
        ("eventim", eventim_scraper.get_events),
    ]

    out: List[Dict[str, Any]] = []
    for name, fn in sources:
        try:
            batch = fn()
            out.extend(batch)
            logger.info("Quelle %s: +%s Events", name, len(batch))
        except Exception as e:
            logger.exception("Quelle %s fehlgeschlagen: %s", name, e)
    return out


__all__ = ["collect_all_events"]
