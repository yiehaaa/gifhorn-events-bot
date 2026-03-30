"""
Gmail OAuth2: Einreichungen lesen, optional Antwort senden.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GMAIL_ADDRESS, GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES: List[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class EmailHandler:
    def __init__(self) -> None:
        self.service: Any = None
        self.user_email = GMAIL_ADDRESS

    def authenticate(self) -> None:
        """OAuth2; öffnet ggf. Browser für erste Anmeldung."""
        creds: Optional[UserCredentials] = None

        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = UserCredentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"OAuth-Client fehlt: {GOOGLE_CREDENTIALS_FILE}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail authentifiziert")

    def search_event_submissions(
        self, query: str = "subject:VERANSTALTUNG OR subject:veranstaltung"
    ) -> List[Dict[str, Any]]:
        """Listet Nachrichten-Metadaten (id, threadId)."""
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")
        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=10)
                .execute()
            )
            messages = results.get("messages", [])
            logger.info("%s Event-Mails gefunden", len(messages))
            return messages
        except HttpError as error:
            logger.error("Gmail-Fehler: %s", error)
            return []

    def get_message_content(self, message_id: str) -> Dict[str, Any]:
        """Betreff, Absender, Klartext-Body (best effort)."""
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")
        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = message["payload"].get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "",
            )

            body = self._extract_body(message["payload"])

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "body": body,
            }
        except HttpError as error:
            logger.error("Message-Abruf: %s", error)
            return {}

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Rekursiv text/plain aus Multipart."""
        if "body" in payload and payload["body"].get("data"):
            data = payload["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        parts = payload.get("parts") or []
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if "parts" in part:
                inner = self._extract_body(part)
                if inner:
                    return inner
        return ""

    def download_attachment(
        self, message_id: str, attachment_id: str, filename: str
    ) -> None:
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")
        try:
            att = (
                self.service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            file_data = base64.urlsafe_b64decode(att["data"])
            with open(filename, "wb") as f:
                f.write(file_data)
            logger.info("Anhang gespeichert: %s", filename)
        except HttpError as error:
            logger.error("Download-Fehler: %s", error)

    def send_email(self, to: str, subject: str, body: str) -> None:
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")
        try:
            message = MIMEText(body, "plain", "utf-8")
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            send_body = {"raw": raw}
            self.service.users().messages().send(userId="me", body=send_body).execute()
            logger.info("E-Mail gesendet an %s", to)
        except HttpError as error:
            logger.error("Send-Fehler: %s", error)


email_handler = EmailHandler()
