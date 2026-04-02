"""
Google Drive Uploader — für Flyer und Datei-Uploads aus der Web-Form.

Nutzt Google Drive API mit Service Account.
Erstellt Ordner pro Event und speichert Dateien dort.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

try:
    from google.oauth2 import service_account
    import googleapiclient.discovery as discovery
    from googleapiclient.http import MediaIoBaseUpload
except ImportError:
    service_account = None
    discovery = None

from config import GOOGLE_CREDENTIALS_FILE, MOCK_MODE

logger = logging.getLogger(__name__)

DRIVE_SCOPE = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveUploader:
    """Upload Dateien zu Google Drive."""

    def __init__(self, folder_id: Optional[str] = None):
        """
        Init mit optionaler Ziel-Folder ID.
        Falls None: Dateien gehen ins Root der Service Account's Drive.
        """
        self.service = None
        self.folder_id = folder_id
        self._authenticate()

    def _authenticate(self) -> None:
        """Authentifiziere mit Service Account."""
        if MOCK_MODE:
            logger.warning("MOCK_MODE: Google Drive nicht authentifiziert")
            return

        if not discovery:
            logger.warning("google-api-client nicht installiert")
            return

        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=DRIVE_SCOPE
            )
            self.service = discovery.build("drive", "v3", credentials=creds)
            logger.info("Google Drive API authentifiziert")
        except Exception as e:
            logger.error(f"Google Drive Auth fehlgeschlagen: {e}")

    def upload_file(
        self,
        file_name: str,
        file_content: bytes,
        mime_type: str = "application/octet-stream",
    ) -> Optional[str]:
        """
        Upload Datei zu Google Drive.

        Args:
            file_name: Dateiname (z.B. "flyer.pdf")
            file_content: Datei-Bytes
            mime_type: MIME-Type (z.B. "application/pdf")

        Returns:
            Google Drive Link (https://drive.google.com/file/d/FILE_ID/view)
            oder None bei Fehler
        """
        if MOCK_MODE or not self.service:
            logger.warning("Google Drive Upload nicht verfügbar (MOCK_MODE)")
            return None

        try:
            # Erstelle Media Object
            media = MediaIoBaseUpload(
                BytesIO(file_content),
                mimetype=mime_type,
                resumable=True,
            )

            # Datei Metadaten
            file_metadata = {"name": file_name}
            if self.folder_id:
                file_metadata["parents"] = [self.folder_id]

            # Upload
            file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )

            file_id = file.get("id")
            file_url = f"https://drive.google.com/file/d/{file_id}/view"

            logger.info(f"Datei hochgeladen: {file_name} → {file_url}")
            return file_url

        except Exception as e:
            logger.error(f"Google Drive Upload fehlgeschlagen: {e}")
            return None

    def create_folder(self, folder_name: str) -> Optional[str]:
        """
        Erstelle einen neuen Ordner in Google Drive.

        Returns:
            Folder ID oder None bei Fehler
        """
        if MOCK_MODE or not self.service:
            logger.warning("Google Drive Folder-Erstellung nicht verfügbar")
            return None

        try:
            folder_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if self.folder_id:
                folder_metadata["parents"] = [self.folder_id]

            folder = (
                self.service.files()
                .create(body=folder_metadata, fields="id")
                .execute()
            )

            folder_id = folder.get("id")
            logger.info(f"Folder erstellt: {folder_name} (ID: {folder_id})")
            return folder_id

        except Exception as e:
            logger.error(f"Google Drive Folder-Erstellung fehlgeschlagen: {e}")
            return None


# Globale Instanz
google_drive_uploader = GoogleDriveUploader()
