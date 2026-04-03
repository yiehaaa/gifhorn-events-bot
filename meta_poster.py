"""
Instagram & Facebook Graph API – Posts mit Bild + Text.
Siehe 01f-META-POSTER.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from config import (
    META_ACCESS_TOKEN,
    META_API_VERSION,
    META_FB_PAGE_ID,
    META_IG_ACCOUNT_ID,
    MOCK_MODE,
    public_image_url,
)
from database import db

logger = logging.getLogger(__name__)


class MetaPoster:
    def __init__(self) -> None:
        self.mock = MOCK_MODE or not META_ACCESS_TOKEN
        self.access_token = META_ACCESS_TOKEN
        self.ig_account_id = META_IG_ACCOUNT_ID
        self.fb_page_id = META_FB_PAGE_ID
        self.api_version = META_API_VERSION
        self.graph_base = f"https://graph.facebook.com/{self.api_version}"

    @staticmethod
    def _image_url_for_api(event: Dict[str, Any]) -> str:
        """DB kann /flyers/… speichern — Meta braucht absolute https-URL (PUBLIC_IMAGE_BASE_URL)."""
        return public_image_url(str(event.get("image_url") or "").strip())

    def post_to_instagram(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Instagram: Container + media_publish (Business/Creator API)."""
        try:
            if self.mock:
                eid = event.get("id")
                return {
                    "success": True,
                    "platform": "instagram",
                    "post_id": f"mock-ig-{eid}",
                    "url": "mock://instagram",
                }
            if not self.ig_account_id:
                return {"success": False, "reason": "META_IG_ACCOUNT_ID fehlt"}

            post_text = event.get("post_text", "") or ""
            image_url = self._image_url_for_api(event)

            if not image_url:
                logger.warning("Kein Bild für: %s", event.get("title", ""))
                return {"success": False, "reason": "No image"}
            if not image_url.startswith(("http://", "https://")):
                logger.warning(
                    "Instagram: Bild-URL nicht öffentlich (%r). Worker: PUBLIC_IMAGE_BASE_URL "
                    "auf die Dashboard-Basis setzen (siehe config.py). Event: %s",
                    image_url[:200],
                    event.get("title", ""),
                )
                return {"success": False, "reason": "image_url not absolute URL"}

            container_url = f"{self.graph_base}/{self.ig_account_id}/media"
            container_data = {
                "image_url": image_url,
                "caption": post_text,
                "access_token": self.access_token,
            }
            response = requests.post(container_url, data=container_data, timeout=60)
            container = response.json()

            if not container.get("id"):
                logger.error("Instagram Container-Fehler: %s", container)
                return {"success": False, "reason": str(container)}

            container_id = container["id"]
            time.sleep(1)

            publish_url = f"{self.graph_base}/{self.ig_account_id}/media_publish"
            publish_data = {
                "creation_id": container_id,
                "access_token": self.access_token,
            }
            pub_response = requests.post(publish_url, data=publish_data, timeout=60)
            pub_result = pub_response.json()

            if pub_result.get("id"):
                logger.info("Instagram Post: %s", event.get("title", ""))
                return {
                    "success": True,
                    "platform": "instagram",
                    "post_id": pub_result["id"],
                    "url": f"https://www.instagram.com/p/{pub_result['id']}/",
                }

            logger.error("Instagram Publish-Fehler: %s", pub_result)
            return {"success": False, "reason": str(pub_result)}

        except Exception as e:
            logger.error("Instagram-Fehler: %s", e)
            return {"success": False, "reason": str(e)}

    def post_to_facebook(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Facebook Page: Feed-Post mit Link + Bild."""
        try:
            if self.mock:
                eid = event.get("id")
                return {
                    "success": True,
                    "platform": "facebook",
                    "post_id": f"mock-fb-{eid}",
                    "url": "mock://facebook",
                }
            if not self.fb_page_id:
                return {"success": False, "reason": "META_FB_PAGE_ID fehlt"}

            post_text = event.get("post_text", "") or ""
            image_url = self._image_url_for_api(event)

            fb_url = f"{self.graph_base}/{self.fb_page_id}/feed"
            fb_data: Dict[str, Any] = {
                "message": post_text,
                "access_token": self.access_token,
            }
            if event.get("url"):
                fb_data["link"] = event["url"]
            if image_url:
                if not image_url.startswith(("http://", "https://")):
                    logger.warning(
                        "Facebook: picture ist keine gültige URL (%r). PUBLIC_IMAGE_BASE_URL prüfen. %s",
                        image_url[:200],
                        event.get("title", ""),
                    )
                else:
                    fb_data["picture"] = image_url

            response = requests.post(fb_url, data=fb_data, timeout=60)
            result = response.json()

            if result.get("id"):
                logger.info("Facebook Post: %s", event.get("title", ""))
                post_id = result["id"]
                return {
                    "success": True,
                    "platform": "facebook",
                    "post_id": post_id,
                    "url": f"https://www.facebook.com/{self.fb_page_id}/posts/{post_id}",
                }

            logger.error("Facebook-Fehler: %s", result)
            return {"success": False, "reason": str(result)}

        except Exception as e:
            logger.error("Facebook-Fehler: %s", e)
            return {"success": False, "reason": str(e)}

    def batch_post(
        self,
        events: List[Dict[str, Any]],
        platforms: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Postet Events; markiert DB nur bei mindestens einem Erfolg."""
        if platforms is None:
            platforms = ["instagram", "facebook"]

        results: List[Dict[str, Any]] = []

        for event in events:
            event_results: Dict[str, Any] = {
                "event_id": event.get("id"),
                "title": event.get("title"),
            }

            ig_ok = False
            fb_ok = False

            if "instagram" in platforms:
                ig_result = self.post_to_instagram(event)
                event_results["instagram"] = ig_result
                ig_ok = bool(ig_result.get("success"))

            if "facebook" in platforms:
                time.sleep(1)
                fb_result = self.post_to_facebook(event)
                event_results["facebook"] = fb_result
                fb_ok = bool(fb_result.get("success"))

            eid = event.get("id")
            if eid is not None and (ig_ok or fb_ok):
                db.mark_event_posted(int(eid), instagram=ig_ok, facebook=fb_ok)

            results.append(event_results)

        return results


meta_poster = MetaPoster()
