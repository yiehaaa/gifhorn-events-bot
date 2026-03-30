"""
Wetter-Integration (Open-Meteo).
Siehe Vault-Doku 02f-WEATHER.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class WeatherHandler:
    def __init__(self) -> None:
        self.openmeteo_url = "https://api.open-meteo.com/v1/forecast"
        self.gifhorn_coords = {"latitude": 52.1281, "longitude": 10.5218}

    def get_weather_for_date(self, event_date: str) -> Dict[str, Any]:
        """
        Hole Wetter für Event-Datum.
        event_date erwartet mindestens YYYY-MM-DD prefix (ISO oder Timestamp).
        """
        try:
            # Open-Meteo braucht Datum als "daily.time" Index; wir rechnen über event_date[:10]
            date_prefix = (event_date or "")[:10]
            if not date_prefix:
                return {}

            r = requests.get(
                self.openmeteo_url,
                params={
                    **self.gifhorn_coords,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "Europe/Berlin",
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

            dates = data.get("daily", {}).get("time", []) or []
            if not dates or date_prefix not in dates:
                return {}

            index = dates.index(date_prefix)
            daily = data.get("daily", {})
            return {
                "date": date_prefix,
                "temp_max": (daily.get("temperature_2m_max") or [None])[index],
                "temp_min": (daily.get("temperature_2m_min") or [None])[index],
                "precipitation": (daily.get("precipitation_sum") or [None])[index],
                "weather_code": (daily.get("weather_code") or [None])[index],
            }
        except Exception as e:
            logger.warning("Weather-Fehler: %s", e)
            return {}

    def format_weather_text(self, weather: Dict[str, Any]) -> str:
        if not weather:
            return ""

        temp_max = weather.get("temp_max")
        try:
            if temp_max is None:
                return ""
            return f"🌡️ {float(temp_max):.0f}°C"
        except Exception:
            return ""


weather_handler = WeatherHandler()

