"""
Gmail OAuth2: Einreichungen lesen, optional Antwort senden.
Email-Screening für Event-Plakate und -Texte.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    EMAIL_ATTACHMENT_STORAGE_PATH,
    FORM_URL,
    GMAIL_ADDRESS,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)

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

    def get_pending_email_submissions(
        self, query: str = "is:unread label:INBOX"
    ) -> List[Dict[str, Any]]:
        """
        Hole unbearbeitete Event-Einreichungs-Emails aus Gmail.

        Args:
            query: Gmail search query (default: unread inbox messages)

        Returns:
            Liste von Emails mit vollständiger Analyse
                - id, subject, sender, body
                - attachments (mit Metadaten: filename, mime_type, size)
        """
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")

        try:
            # 1. Hole Message-IDs
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=20)
                .execute()
            )
            message_ids = [m["id"] for m in results.get("messages", [])]
            logger.info(f"📧 {len(message_ids)} unbearbeitete Emails gefunden")

            # 2. Für jede Message: hole vollständigen Inhalt
            emails = []
            for msg_id in message_ids:
                msg_data = self.get_message_content(msg_id)
                if msg_data:
                    # 3. Extrahiere Attachments
                    attachments = self._get_attachments_info(msg_id)
                    msg_data["attachments"] = attachments
                    emails.append(msg_data)

            return emails

        except HttpError as error:
            logger.error(f"Email-Abruf Fehler: {error}")
            return []

    def _get_attachments_info(self, message_id: str) -> List[Dict[str, Any]]:
        """
        Extrahiere Anhang-Metadaten aus einer Email (ohne Download).

        Returns:
            Liste von {filename, mime_type, size, attachment_id}
        """
        if not self.service:
            return []

        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            attachments = []
            parts = message["payload"].get("parts", [])

            for part in parts:
                if part.get("filename"):
                    # Das ist eine Datei
                    headers = {h["name"]: h["value"] for h in part.get("headers", [])}
                    attachments.append(
                        {
                            "filename": part["filename"],
                            "mime_type": part.get("mimeType", "application/octet-stream"),
                            "size": int(part.get("body", {}).get("size", 0)),
                            "attachment_id": part["body"].get("attachmentId", ""),
                        }
                    )

            return attachments
        except HttpError as error:
            logger.error(f"Attachments-Abruf Fehler: {error}")
            return []

    def save_attachment_to_storage(
        self, message_id: str, attachment_id: str, filename: str
    ) -> Optional[str]:
        """
        Speichert Anhang zu Railway Persistent Storage.

        Args:
            message_id: Gmail message ID
            attachment_id: Gmail attachment ID
            filename: Original filename

        Returns:
            Relativer Pfad zum gespeicherten File (z.B. "/app/email_attachments/...")
            oder None bei Fehler
        """
        if not self.service:
            raise RuntimeError("authenticate() zuerst aufrufen")

        try:
            # 1. Erstelle Storage-Ordner falls nicht vorhanden
            storage_dir = Path(EMAIL_ATTACHMENT_STORAGE_PATH)
            storage_dir.mkdir(parents=True, exist_ok=True)

            # 2. Generiere eindeutigen Dateinamen
            # Format: timestamp_originalfilename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            # Entferne unsichere Zeichen aus Filename
            safe_filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
            unique_filename = f"{timestamp}_{safe_filename}"
            file_path = storage_dir / unique_filename

            # 3. Download vom Gmail
            att = (
                self.service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            file_data = base64.urlsafe_b64decode(att["data"])

            # 4. Speichere Datei
            with open(file_path, "wb") as f:
                f.write(file_data)

            logger.info(f"✅ Anhang gespeichert: {file_path}")

            # Return relativer Pfad (für DB-Speicherung)
            return str(file_path)

        except HttpError as error:
            logger.error(f"❌ Download-Fehler: {error}")
            return None
        except IOError as error:
            logger.error(f"❌ Datei-Fehler: {error}")
            return None

    def send_form_suggestion_email(self, recipient_email: str, subject: str = None) -> bool:
        """
        Auto-Response bei unvollständiger Email:
        Schickt Link zum Google Form damit Nutzer die fehlenden Infos nachtragt.
        """
        if not self.service:
            logger.warning("Email-Service nicht authentifiziert; Auto-Response konnte nicht gesendet werden")
            return False

        try:
            subject = subject or "Vielen Dank für deine Event-Einreichung!"
            body = f"""Vielen Dank für deine Event-Einreichung!

Wir haben deine Email erhalten, konnten aber nicht alle Informationen automatisch erfassen.
Um sicherzustellen, dass dein Event richtig auf unseren Kanälen gezeigt wird,
bitten wir dich um ein paar Zusatzangaben:

📋 Bitte fülle unseren Event-Katalog hier aus:
{FORM_URL}

Mit wenigen Klicks können wir dein Event dann direkt veröffentlichen!

Danke für deine Unterstützung! 🎉

---
Südheide Veranstaltungen
"""

            message = MIMEText(body, "plain", "utf-8")
            message["to"] = recipient_email
            message["from"] = self.user_email or "noreply@gmail.com"
            message["subject"] = subject

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            self.service.users().messages().send(
                userId="me",
                body={"raw": raw_message}
            ).execute()

            logger.info(f"✅ Auto-Response gesendet an: {recipient_email}")
            return True

        except HttpError as error:
            logger.error(f"❌ Auto-Response Fehler: {error}")
            return False
        except Exception as error:
            logger.error(f"❌ Unerwarteter Fehler bei Auto-Response: {error}")
            return False


email_handler = EmailHandler()
