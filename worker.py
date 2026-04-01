"""
Railway Worker (Cron-Job Friendly)

Empfehlung Europe/Berlin:
- 19:00  --collect     Mail-Abruf + ein Telegram-Digest (Spam pro Mail ❌, dann „Alle übrigen freigeben“)
- 21:00  --evening-preview   KI-Beiträge aus Mails in Telegram zur Freigabe
- danach --post        Meta (nach deiner Freigabe der Abend-Vorschau)

Läuft als Short-Lived Prozess; Telegram-Buttons brauchen dauerhaft: python telegram_bot.py
"""

from __future__ import annotations

import argparse
import asyncio

from main import (
    collect_and_approve_flow,
    evening_email_post_previews_flow,
    post_approved_events,
)


async def _run(
    do_collect: bool, do_post: bool, do_evening_preview: bool
) -> None:
    if do_collect:
        await collect_and_approve_flow()
    if do_evening_preview:
        await evening_email_post_previews_flow()
    if do_post:
        await post_approved_events()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true", help="collect step run")
    parser.add_argument("--post", action="store_true", help="post step run")
    parser.add_argument(
        "--all",
        action="store_true",
        help="run collect and post (equivalent to --collect --post)",
    )
    parser.add_argument(
        "--evening-preview",
        action="store_true",
        help="Telegram: Abend-Übersicht der KI-Beiträge aus Einreichungs-Mails",
    )
    args = parser.parse_args()

    do_collect = args.all or args.collect
    do_evening_preview = args.evening_preview
    do_post = args.all or args.post

    # Default: nur post (zum sicheren Betrieb, besonders im MOCK_MODE)
    if not do_collect and not do_post and not do_evening_preview:
        do_post = True

    asyncio.run(
        _run(
            do_collect=do_collect,
            do_post=do_post,
            do_evening_preview=do_evening_preview,
        )
    )


if __name__ == "__main__":
    main()

