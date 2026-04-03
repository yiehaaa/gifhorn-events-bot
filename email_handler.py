"""
Gmail OAuth2: Einreichungen lesen, optional Antwort senden.
Email-Screening für Event-Plakate und -Texte.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
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
    GMAIL_PENDING_QUERY,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)

logger = logging.getLogger(__name__)

SCOPES: List[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_client_secret_temp: Optional[str] = None
_token_temp: Optional[str] = None


def gmail_oauth_configured() -> bool:
    """True, wenn Token- und/oder Client-Daten als Datei oder Railway-JSON-Variable vorliegen."""
    if os.path.isfile(GOOGLE_TOKEN_FILE):
        return True
    if (os.getenv("GOOGLE_TOKEN_JSON") or "").strip():
        return True
    if os.path.isfile(GOOGLE_CREDENTIALS_FILE):
        return True
    if (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_JSON") or "").strip():
        return True
    return False


def _ensure_token_file() -> Optional[str]:
    """Pfad zu token.json oder temporäre Datei aus GOOGLE_TOKEN_JSON."""
    global _token_temp
    if os.path.isfile(GOOGLE_TOKEN_FILE):
        return GOOGLE_TOKEN_FILE
    raw = (os.getenv("GOOGLE_TOKEN_JSON") or "").strip()
    if not raw:
        return None
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_TOKEN_JSON ist kein gültiges JSON: {e}") from e
    if _token_temp and os.path.isfile(_token_temp):
        return _token_temp
    fd, path = tempfile.mkstemp(prefix="gmail_token_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(raw)
    _token_temp = path
    logger.info("Gmail-Token aus Umgebungsvariable GOOGLE_TOKEN_JSON (temp-Datei)")
    return path


def _ensure_client_secret_file() -> Optional[str]:
    """Pfad zu client_secret.json oder temporäre Datei aus GOOGLE_OAUTH_CLIENT_SECRET_JSON."""
    global _client_secret_temp
    if os.path.isfile(GOOGLE_CREDENTIALS_FILE):
        return GOOGLE_CREDENTIALS_FILE
    raw = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_JSON") or "").strip()
    if not raw:
        return None
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"GOOGLE_OAUTH_CLIENT_SECRET_JSON ist kein gültiges JSON: {e}"
        ) from e
    if _client_secret_temp and os.path.isfile(_client_secret_temp):
        return _client_secret_temp
    fd, path = tempfile.mkstemp(prefix="gmail_oauth_client_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(raw)
    _client_secret_temp = path
    logger.info(
        "OAuth-Client aus GOOGLE_OAUTH_CLIENT_SECRET_JSON (temp-Datei)"
    )
    return path


class EmailHandler:
    def __init__(self) -> None:
        self.service: Any = None
        self.user_email = GMAIL_ADDRESS

    def authenticate(self) -> None:
        """OAuth2; öffnet ggf. Browser für erste Anmeldung (nur lokal)."""
        creds: Optional[UserCredentials] = None

        token_path = _ensure_token_file()
        if token_path:
            creds = UserCredentials.from_authorized_user_file(token_path, SCOPES)

        need_persist = False
        if not creds or not creds.valid:
            need_persist = True
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    logger.warning(
                        "Gmail access token refresh fehlgeschlagen: %s", exc
                    )
                    creds = None
            if not creds or not creds.valid:
                client_path = _ensure_client_secret_file()
                if not client_path:
                    raise FileNotFoundError(
                        "Gmail: Weder gültiges token (Datei/GOOGLE_TOKEN_JSON) noch "
                        "OAuth-Client (Datei/GOOGLE_OAUTH_CLIENT_SECRET_JSON). "
                        "Railway: beide Variablen als Secrets setzen oder Dateien mounten."
                    )
                if (os.getenv("RAILWAY_ENVIRONMENT") or "").strip():
                    raise RuntimeError(
                        "Gmail auf Railway: Kein gültiges Token oder Refresh fehlgeschlagen — "
                        "kein Browser-Login möglich. Lokal einmal OAuth, dann kompletten Inhalt "
                        "von token.json als Secret GOOGLE_TOKEN_JSON eintragen (oder Datei mounten). "
                        "Wenn Google Refresh verweigert, zusätzlich "
                        "GOOGLE_OAUTH_CLIENT_SECRET_JSON (Desktop-Client-JSON) setzen."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

        if need_persist and creds and creds.valid:
            try:
                Path(GOOGLE_TOKEN_FILE).parent.mkdir(parents=True, exist_ok=True)
                with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
                    token.write(creds.to_json())
            except OSError as oe:
                logger.warning(
                    "Konnte token nicht nach %s schreiben (OK bei reinem GOOGLE_TOKEN_JSON): %s",
                    GOOGLE_TOKEN_FILE,
                    oe,
                )

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
        self, query: Optional[str] = None
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

        q = query if query is not None else GMAIL_PENDING_QUERY

        try:
            # 1. Hole Message-IDs
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=q, maxResults=20)
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

    @staticmethod
    def _walk_payload_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flacht multipart/* rekursiv (Flyer oft in verschachtelten parts)."""
        out: List[Dict[str, Any]] = []
        stack = [payload]
        while stack:
            node = stack.pop()
            for p in node.get("parts") or []:
                stack.append(p)
            out.append(node)
        return out

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

            attachments: List[Dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            root = message.get("payload") or {}
            for part in self._walk_payload_parts(root):
                fn = (part.get("filename") or "").strip()
                if not fn:
                    continue
                body = part.get("body") or {}
                att_id = body.get("attachmentId") or ""
                if not att_id:
                    continue
                key = (fn, att_id)
                if key in seen:
                    continue
                seen.add(key)
                attachments.append(
                    {
                        "filename": fn,
                        "mime_type": part.get("mimeType", "application/octet-stream"),
                        "size": int(body.get("size", 0)),
                        "attachment_id": att_id,
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
