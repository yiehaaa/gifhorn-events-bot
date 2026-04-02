#!/usr/bin/env python3
"""
Railway-Variablen für Image Hosting Setup (Task #1.23 Phase 2).

Setzt NUR PUBLIC_IMAGE_BASE_URL auf Railway.
Behält MOCK_MODE=1 (kein echtes Posting).

  .venv/bin/python scripts/sync_railway_image_hosting.py

Nach erfolgreichem Deploy:
- https://gifhorn-dashboard-production.up.railway.app/flyers/ → 404 OK (Route funktioniert)
- Bilder können über https://.../flyers/{filename} abgerufen werden
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
PUBLIC_IMAGE_BASE_URL = (
    os.getenv(
        "PUBLIC_IMAGE_BASE_URL",
        "https://gifhorn-dashboard-production.up.railway.app",
    )
    .strip()
    .rstrip("/")
)


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


def main() -> None:
    """Setze PUBLIC_IMAGE_BASE_URL auf Railway (Phase 2 Vorbereitung)."""

    print(f"Setting PUBLIC_IMAGE_BASE_URL = {PUBLIC_IMAGE_BASE_URL}\n")

    for svc in SERVICES:
        _set(svc, "PUBLIC_IMAGE_BASE_URL", PUBLIC_IMAGE_BASE_URL)
        print(f"✅ {svc}: PUBLIC_IMAGE_BASE_URL gesetzt")

    for svc in SERVICES:
        _run(["railway", "redeploy", "-s", svc, "-y"])
        print(f"✅ Redeploy {svc}")

    print(
        f"\n✅ Fertig! Image-Hosting vorbereitet.\n"
        f"   - PUBLIC_IMAGE_BASE_URL: {PUBLIC_IMAGE_BASE_URL}\n"
        f"   - Route: {PUBLIC_IMAGE_BASE_URL}/flyers/{{filename}}\n"
        f"   - MOCK_MODE bleibt: 1 (kein echtes Posting)\n"
    )


if __name__ == "__main__":
    main()
