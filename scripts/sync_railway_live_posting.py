#!/usr/bin/env python3
"""
Railway-Variablen für Live-Posting (Meta) mit Flyern **ohne** Claude-Pflicht.

Setzt u. a. MOCK_MODE=0, EMAIL_FLYER_USE_CLAUDE_CAPTION=0, PUBLIC_IMAGE_BASE_URL,
AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS, AUTO_POST_AFTER_EMAIL_CONVERSION, TELEGRAM_*.

CLAUDE_API_KEY nur mitschicken, wenn in `.env` vorhanden (später EMAIL_FLYER_USE_CLAUDE_CAPTION=1).

  .venv/bin/python scripts/sync_railway_live_posting.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

SERVICES = ["gifhorn-worker", "gifhorn-dashboard"]
PUBLIC_IMAGE_BASE_URL = os.getenv(
    "PUBLIC_IMAGE_BASE_URL",
    "https://gifhorn-dashboard-production.up.railway.app/flyers",
).strip()


def _run(cmd: list[str], **kwargs) -> None:
    subprocess.run(cmd, cwd=REPO, check=True, **kwargs)


def _set(svc: str, key: str, value: str) -> None:
    _run(
        [
            "railway",
            "variable",
            "set",
            f"{key}={value}",
            "-s",
            svc,
            "--skip-deploys",
        ]
    )


def _set_stdin(svc: str, key: str, value: str) -> None:
    _run(
        ["railway", "variable", "set", key, "--stdin", "-s", svc, "--skip-deploys"],
        input=value.encode(),
    )


def main() -> None:
    claude = (os.getenv("CLAUDE_API_KEY") or "").strip()
    tok = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    auto_post = os.getenv("AUTO_POST_AFTER_EMAIL_CONVERSION", "1").strip()

    for svc in SERVICES:
        _set(svc, "PUBLIC_IMAGE_BASE_URL", PUBLIC_IMAGE_BASE_URL.rstrip("/"))
        _set(svc, "AUTO_APPROVE_SOCIAL_FOR_EMAIL_SUBMISSIONS", "1")
        _set(svc, "EMAIL_FLYER_USE_CLAUDE_CAPTION", "0")
        _set(svc, "MOCK_MODE", "0")
        _set(svc, "AUTO_POST_AFTER_EMAIL_CONVERSION", auto_post)
        print(
            f"OK {svc}: MOCK_MODE=0, Flyer ohne Claude, PUBLIC_IMAGE, "
            f"AUTO_APPROVE_SOCIAL, AUTO_POST_AFTER_EMAIL_CONVERSION={auto_post}"
        )

    if tok and chat:
        for svc in SERVICES:
            _set_stdin(svc, "TELEGRAM_BOT_TOKEN", tok)
            _set(svc, "TELEGRAM_CHAT_ID", chat)
            print(f"OK {svc}: TELEGRAM_*")
    else:
        print("WARN: TELEGRAM_* fehlen in .env")

    if claude:
        for svc in SERVICES:
            _set_stdin(svc, "CLAUDE_API_KEY", claude)
            print(f"OK {svc}: CLAUDE_API_KEY (für später; Caption bleibt aus bis EMAIL_FLYER_USE_CLAUDE_CAPTION=1)")
    else:
        print("Hinweis: Kein CLAUDE_API_KEY in .env — für KI-Caption später setzen + EMAIL_FLYER_USE_CLAUDE_CAPTION=1.")

    for svc in SERVICES:
        _run(["railway", "redeploy", "-s", svc, "-y"])
        print(f"Redeploy {svc}")

    print("\nFertig. Events nur in Railway-Postgres; Flyer-URL muss https + /flyers sein.")


if __name__ == "__main__":
    main()
