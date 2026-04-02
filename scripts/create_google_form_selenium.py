#!/usr/bin/env python3
"""
Browser-Bot: Erstellt Google Form automatisch mit Selenium.

Nutzt Browser-Automation (Chrome/Chromium) um eine Google Form
mit 8 Fragen zu erstellen.
"""

import time
import sys
from pathlib import Path
from typing import Optional

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.chrome.options import Options
except ImportError:
    print("❌ Selenium nicht installiert. Installiere zuerst:")
    print("   pip install selenium")
    sys.exit(1)

# ==================== CONFIG ====================
FORM_TITLE = "Südheide Veranstaltungen — Event einreichen"
FORM_DESCRIPTION = "Reiche dein Event ein — wir posten es auf Instagram & Facebook!"

QUESTIONS = [
    {
        "title": "Veranstaltungstitel",
        "type": "short_text",
        "required": True,
    },
    {
        "title": "Datum & Uhrzeit",
        "type": "date_time",
        "required": True,
    },
    {
        "title": "Veranstaltungsort (Ort/Adresse)",
        "type": "short_text",
        "required": True,
    },
    {
        "title": "Stadt",
        "type": "multiple_choice",
        "options": ["Gifhorn", "Wolfsburg", "Braunschweig", "Umliegend"],
        "required": True,
    },
    {
        "title": "Beschreibung",
        "type": "paragraph",
        "required": False,
    },
    {
        "title": "Eintritt (€)",
        "type": "short_text",
        "required": False,
    },
    {
        "title": "Link zu mehr Informationen (optional)",
        "type": "short_text",
        "required": False,
    },
    {
        "title": "Deine Email (für Rückfragen)",
        "type": "email",
        "required": True,
    }
]

# ==================== SELENIUM BOT ====================

class GoogleFormBot:
    def __init__(self):
        """Initialisiere Selenium Browser"""
        print("🤖 Starte Chrome Browser...")

        # Chrome Optionen (ohne Headless für Debugging)
        chrome_options = Options()
        # chrome_options.add_argument("--headless")  # Auskommentiert für visuelles Feedback
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            print("   ✅ Chrome gestartet")
        except Exception as e:
            print(f"   ❌ Chrome-Start fehlgeschlagen: {e}")
            print("   💡 Stelle sicher, dass ChromeDriver installiert ist")
            sys.exit(1)

        self.wait = WebDriverWait(self.driver, 10)

    def create_form(self) -> Optional[str]:
        """Erstelle Google Form"""
        print("\n📝 Erstelle Google Form...")

        try:
            # 1. Öffne Google Forms
            print("   → Öffne forms.google.com...")
            self.driver.get("https://forms.google.com")
            time.sleep(2)

            # 2. Klick auf "+" (Neue Form)
            print("   → Klick auf 'Neues Formular'...")
            new_form_button = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[aria-label*='Neues Formular']"))
            )
            new_form_button.click()
            time.sleep(3)

            # 3. Setze Formular-Titel
            print(f"   → Setze Titel: '{FORM_TITLE}'...")
            title_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Formularname']"))
            )
            title_input.clear()
            title_input.send_keys(FORM_TITLE)
            time.sleep(1)

            # 4. Setze Formular-Beschreibung
            print(f"   → Setze Beschreibung...")
            desc_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Formularbeschreibung']"))
            )
            desc_input.send_keys(FORM_DESCRIPTION)
            time.sleep(1)

            # 5. Füge Fragen hinzu
            print(f"\n❓ Füge {len(QUESTIONS)} Fragen hinzu...")
            for i, q in enumerate(QUESTIONS, 1):
                self.add_question(q, i == 1)

            # 6. Speichern
            print("\n💾 Speichere Formular...")
            time.sleep(2)
            self.driver.find_element(By.KEY_COMBINATION, Keys.CONTROL + "s")
            time.sleep(2)

            # 7. Extrahiere Form-ID aus URL
            current_url = self.driver.current_url
            form_id = current_url.split("/d/")[1].split("/")[0]
            form_url = f"https://docs.google.com/forms/d/{form_id}/viewform"

            print(f"\n✅ Formular erstellt!")
            print(f"   🔗 {form_url}")

            return form_id

        except Exception as e:
            print(f"❌ Fehler beim Erstellen: {e}")
            return None
        finally:
            time.sleep(2)
            self.driver.quit()

    def add_question(self, question: dict, first: bool = False):
        """Füge Frage zum Formular hinzu"""
        q_title = question["title"]
        q_type = question["type"]
        required = question.get("required", False)

        try:
            # Klick auf "Frage hinzufügen" wenn nicht erste Frage
            if not first:
                add_q_btn = self.wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "[aria-label='Frage hinzufügen']"))
                )
                add_q_btn.click()
                time.sleep(1)

            # Setze Frage-Text
            question_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "textarea[aria-label='Frage']"))
            )
            question_input.clear()
            question_input.send_keys(q_title)
            time.sleep(0.5)

            # Setze Frage-Typ (Dropdown)
            type_dropdown = self.driver.find_element(By.CSS_SELECTOR, "[aria-label='Fragetyp']")
            type_dropdown.click()
            time.sleep(0.5)

            # Wähle Typ basierend auf Frage
            type_label = self._get_type_label(q_type)
            type_option = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{type_label}')]"))
            )
            type_option.click()
            time.sleep(0.5)

            # Setze "Erforderlich"
            if required:
                required_checkbox = self.driver.find_element(
                    By.CSS_SELECTOR, "[aria-label='Erforderlich']"
                )
                if not required_checkbox.is_selected():
                    required_checkbox.click()

            # Füge Optionen hinzu wenn Multiple Choice
            if q_type == "multiple_choice" and "options" in question:
                for option in question["options"]:
                    self._add_option(option)

            print(f"   ✅ Frage {len(QUESTIONS) - len(question) + 1}: {q_title}")
            time.sleep(0.5)

        except Exception as e:
            print(f"   ⚠️  Frage '{q_title}' — Fehler: {e}")

    def _get_type_label(self, q_type: str) -> str:
        """Map Typ zu Google Forms Label"""
        mapping = {
            "short_text": "Kurze Antwort",
            "paragraph": "Absatz",
            "email": "E-Mail",
            "date_time": "Datum",
            "multiple_choice": "Mehrfachauswahl",
        }
        return mapping.get(q_type, "Kurze Antwort")

    def _add_option(self, option_text: str):
        """Füge Option zu Multiple Choice hinzu"""
        try:
            option_input = self.driver.find_element(
                By.CSS_SELECTOR, "input[aria-label='Option 1']"
            )
            option_input.clear()
            option_input.send_keys(option_text)
            time.sleep(0.3)
        except:
            pass


# ==================== MAIN ====================

def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║  🤖 GOOGLE FORM CREATOR — BROWSER BOT                     ║
╚════════════════════════════════════════════════════════════╝
    """)

    try:
        bot = GoogleFormBot()
        form_id = bot.create_form()

        if form_id:
            form_url = f"https://docs.google.com/forms/d/{form_id}/viewform"
            print(f"\n✅ FORM ERSTELLT!")
            print(f"\n📋 Google Form:")
            print(f"   {form_url}")
            print(f"\n🔗 Form-ID für .env:")
            print(f"   {form_id}")
            print(f"\n⏭️  Nächste Schritte:")
            print(f"   1. Öffne Form im Browser")
            print(f"   2. Klick 'Responses' (oben) → 'Create Spreadsheet'")
            print(f"   3. Extrahiere Sheets-ID aus der URL")
            print(f"   4. Update .env mit Form-ID + Sheets-ID")
        else:
            print("\n❌ Form-Erstellung fehlgeschlagen")

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
