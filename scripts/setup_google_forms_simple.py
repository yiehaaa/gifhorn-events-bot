#!/usr/bin/env python3
"""
Vereinfachtes Google Forms Setup — OHNE gcloud CLI.

Dieser Script:
1. Authentifiziert sich mit Google (OAuth - Browser)
2. Erstellt Google Form (8 Fragen)
3. Erstellt Google Sheet
4. Verbindet Form mit Sheet (für Responses)
5. Updated .env

Keine Abhängigkeiten: nur Google API Client.
"""

import json
import os
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import googleapiclient.discovery as discovery
from googleapiclient.errors import HttpError

# ==================== CONFIG ====================
FORM_TITLE = "Südheide Veranstaltungen — Event einreichen"
FORM_DESCRIPTION = "Reiche dein Event ein — wir posten es auf Instagram & Facebook!"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms",
    "https://www.googleapis.com/auth/spreadsheets",
]

OAUTH_CLIENT_ID_FILE = "client_secret.json"
TOKEN_FILE = "google_forms_token.json"
ENV_FILE = ".env"

# ==================== HELPERS ====================

def authenticate_oauth() -> Credentials:
    """
    Authentifiziere mit Google OAuth (öffnet Browser).
    """
    print("\n🔐 Authentifiziere mit Google...")

    creds = None

    # Nutze existierenden Token falls vorhanden
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        print("   ✅ Existierenden Token verwendet")

    # Falls kein gültiger Token: neuer OAuth-Flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("   🔄 Aktualisiere Token...")
            creds.refresh(Request())
        else:
            print("   📱 Öffne Browser für Google-Login...")
            if not os.path.exists(OAUTH_CLIENT_ID_FILE):
                print(f"\n❌ FEHLER: {OAUTH_CLIENT_ID_FILE} nicht gefunden!")
                print("\nSo behebst du das:")
                print("1. Gehe zu: https://console.cloud.google.com/")
                print("2. Erstelle neues Projekt: 'gifhorn-events-bot'")
                print("3. Aktiviere: Google Forms API, Sheets API, Drive API")
                print("4. Erstelle OAuth 2.0 Client ID (Desktop-App)")
                print("5. Lade JSON herunter als 'client_secret.json'")
                print("6. Speichere es im Repo-Root")
                exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                OAUTH_CLIENT_ID_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Speichere Token für später
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        print(f"   ✅ Token gespeichert: {TOKEN_FILE}")

    return creds


def create_google_form(forms_service, drive_service, sheets_service) -> Dict[str, str]:
    """
    Erstelle Google Form + Sheet.
    """
    print("\n" + "=" * 60)
    print("📋 GOOGLE FORM ERSTELLEN")
    print("=" * 60)

    # 1. Erstelle Form
    print("\n📝 Erstelle Google Form...")
    form_body = {
        "info": {
            "title": FORM_TITLE,
        }
    }

    try:
        form = forms_service.forms().create(body=form_body).execute()
        form_id = form["formId"]
        form_url = f"https://docs.google.com/forms/d/{form_id}/viewform"
        print(f"   ✅ Form erstellt")
        print(f"   🔗 {form_url}")
    except HttpError as e:
        print(f"   ❌ Fehler: {e}")
        return {}

    # 2. Definiere Fragen
    questions_data = [
        {
            "title": "Wie heißt die Veranstaltung?",
            "type": "SHORT_ANSWER",
            "required": True,
        },
        {
            "title": "Veranstaltung beginnt (Datum)",
            "type": "DATE",
            "required": True,
        },
        {
            "title": "Veranstaltung endet (Datum)",
            "type": "DATE",
            "required": True,
        },
        {
            "title": "Uhrzeit (z.B. '10:00 - 17:00' oder '10:00 - 18:00')",
            "type": "SHORT_ANSWER",
            "required": True,
        },
        {
            "title": "Veranstaltungsort (Ort/Adresse mit PLZ)",
            "type": "SHORT_ANSWER",
            "required": True,
        },
        {
            "title": "Stadt",
            "type": "MULTIPLE_CHOICE",
            "required": True,
            "options": ["Gifhorn", "Wolfsburg", "Braunschweig", "Umliegend"]
        },
        {
            "title": "Beschreibung",
            "type": "PARAGRAPH",
            "required": False,
        },
        {
            "title": "Eintritt (€)",
            "type": "SHORT_ANSWER",
            "required": False,
        },
        {
            "title": "Link zu mehr Informationen",
            "type": "SHORT_ANSWER",
            "required": False,
        },
        {
            "title": "Flyer oder mehr Infos (Google Drive Link oder URL)",
            "type": "SHORT_ANSWER",
            "required": False,
        },
        {
            "title": "Deine Email (für Rückfragen)",
            "type": "EMAIL",
            "required": True,
        }
    ]

    # 3. Füge Fragen hinzu (Batch Update)
    print(f"\n❓ Füge {len(questions_data)} Fragen hinzu (mit Datumsbereich)...")
    requests = []

    for i, q in enumerate(questions_data):
        question_item = {
            "title": q["title"],
            "questionItem": {
                "question": {
                    "required": q.get("required", False),
                }
            }
        }

        # Setze Frage-Typ
        if q["type"] == "SHORT_ANSWER":
            question_item["questionItem"]["question"]["textQuestion"] = {
                "paragraph": False
            }
        elif q["type"] == "PARAGRAPH":
            question_item["questionItem"]["question"]["textQuestion"] = {
                "paragraph": True
            }
        elif q["type"] == "EMAIL":
            question_item["questionItem"]["question"]["textQuestion"] = {
                "paragraph": False
            }
        elif q["type"] == "DATE":
            question_item["questionItem"]["question"]["dateQuestion"] = {
                "includeTime": False
            }
        elif q["type"] == "DATE_TIME":
            question_item["questionItem"]["question"]["dateQuestion"] = {
                "includeTime": True
            }
        elif q["type"] == "MULTIPLE_CHOICE":
            options = [{"value": opt} for opt in q.get("options", [])]
            question_item["questionItem"]["question"]["choiceQuestion"] = {
                "type": "RADIO",
                "options": options
            }

        requests.append({
            "createItem": {
                "item": question_item,
                "location": {"index": i}
            }
        })

    try:
        forms_service.forms().batchUpdate(
            formId=form_id,
            body={"requests": requests}
        ).execute()
        print(f"   ✅ {len(questions_data)} Fragen hinzugefügt")
    except HttpError as e:
        print(f"   ⚠️  Warnung beim Hinzufügen von Fragen: {e}")

    # 4. Erstelle Google Sheet
    print(f"\n📊 Erstelle Google Sheet für Responses...")
    sheet_body = {
        "properties": {
            "title": f"{FORM_TITLE} — Responses"
        }
    }

    try:
        sheet = sheets_service.spreadsheets().create(body=sheet_body).execute()
        sheet_id = sheet["spreadsheetId"]
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        print(f"   ✅ Sheet erstellt")
        print(f"   🔗 {sheet_url}")
    except HttpError as e:
        print(f"   ❌ Fehler: {e}")
        sheet_id = None
        sheet_url = None

    # 5. Füge Description hinzu
    print(f"\n📝 Füge Form-Beschreibung hinzu...")
    try:
        forms_service.forms().batchUpdate(
            formId=form_id,
            body={
                "requests": [
                    {
                        "updateFormInfo": {
                            "info": {
                                "description": FORM_DESCRIPTION,
                            },
                            "updateMask": "description"
                        }
                    }
                ]
            }
        ).execute()
        print(f"   ✅ Beschreibung hinzugefügt")
    except Exception as e:
        print(f"   ⚠️  Warnung: {e}")

    return {
        "form_id": form_id,
        "form_url": form_url,
        "sheet_id": sheet_id,
        "sheet_url": sheet_url,
    }


def update_env(key: str, value: str) -> None:
    """Update .env Datei"""
    if not value:
        return

    env_path = Path(ENV_FILE)
    lines = []
    found = False

    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    print(f"   ✅ .env: {key}={value[:60]}")


def configure_env(form_data: Dict[str, str]) -> None:
    """Update .env"""
    print("\n" + "=" * 60)
    print("⚙️  KONFIGURIERE .ENV")
    print("=" * 60)

    updates = {
        "GOOGLE_FORM_SPREADSHEET_ID": form_data.get("sheet_id", ""),
        "GOOGLE_FORM_SHEET_NAME": "Form Responses 1",
        "GOOGLE_FORM_URL": form_data.get("form_url", ""),
        "GOOGLE_CREDENTIALS_FILE": "client_secret.json",
    }

    for key, value in updates.items():
        if value:
            update_env(key, value)


# ==================== MAIN ====================

def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║  🚀 GOOGLE FORMS SETUP — VEREINFACHT (KEINE CLI)          ║
╚════════════════════════════════════════════════════════════╝
    """)

    try:
        # 1. Authentifiziere
        creds = authenticate_oauth()

        # 2. Erstelle Google APIs Clients
        forms_service = discovery.build("forms", "v1", credentials=creds)
        drive_service = discovery.build("drive", "v3", credentials=creds)
        sheets_service = discovery.build("sheets", "v4", credentials=creds)

        # 3. Erstelle Form + Sheet
        form_data = create_google_form(forms_service, drive_service, sheets_service)

        if not form_data or not form_data.get("form_id"):
            print("\n❌ Form-Erstellung fehlgeschlagen")
            exit(1)

        # 4. Update .env
        configure_env(form_data)

        # 5. Success
        print("\n" + "=" * 60)
        print("✅ SETUP ABGESCHLOSSEN!")
        print("=" * 60)
        print(f"\n📋 Google Form (öffentlicher Link):")
        print(f"   {form_data['form_url']}")
        print(f"\n📊 Google Sheet (Responses):")
        print(f"   {form_data['sheet_url']}")
        print(f"\n✅ .env wurde aktualisiert")
        print(f"\n⏭️  Nächste Schritte:")
        print(f"   1. Öffne Form im Browser")
        print(f"   2. Teste: Fülle ein Event-Beispiel aus")
        print(f"   3. Überprüfe Google Sheet auf neue Row")
        print(f"   4. Lokal testen: python main.py")
        print(f"   5. Prüfe Telegram auf Nachricht")
        print(f"   6. Bio-Link aktualisieren: https://[domain]/form/redirect")

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
