#!/usr/bin/env python3
"""email_sender_whitelist befüllen (Regex wie EMAIL_SENDER_PATTERNS, kommasepariert in .env)."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


def main() -> None:
    ap = argparse.ArgumentParser(description="Whitelist-Patterns in die DB schreiben.")
    ap.add_argument(
        "patterns",
        nargs="*",
        help="z.B. '.*@verein-gifhorn.de'",
    )
    ap.add_argument(
        "-f",
        "--file",
        metavar="PATH",
        help="Eine Zeile pro Pattern; leerzeilen und #-Kommentare ignorieren",
    )
    ap.add_argument(
        "-n",
        "--org",
        default="",
        help="organization_name (optional)",
    )
    args = ap.parse_args()
    lines: list[str] = list(args.patterns)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    lines.append(s)
    if not lines:
        ap.error("Mindestens ein Pattern als Argument oder per --file angeben.")
    db.connect()
    db.create_tables()
    org = args.org.strip() or None
    for pat in lines:
        db.upsert_email_sender_whitelist(pat.strip(), organization_name=org)
    db.close()
    print(f"OK: {len(lines)} Pattern(s) in email_sender_whitelist.")


if __name__ == "__main__":
    main()
