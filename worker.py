"""
Railway Worker (Cron-Job Friendly)

Läuft als Short-Lived Prozess (keine permanente Serverbindung):
- collect: Events sammeln, deduplizieren, Telegram-Freigabe (falls Realbetrieb)
- post: Freigegebene Events auf Social posten (im MOCK_MODE nur DB-Flag setzen)

So kannst du auf Railway Cron Jobs einrichten, ohne dass ein dauerhafter Service
benötigt wird.
"""

from __future__ import annotations

import argparse
import asyncio

from main import collect_and_approve_flow, post_approved_events


async def _run(do_collect: bool, do_post: bool) -> None:
    if do_collect:
        await collect_and_approve_flow()
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
    args = parser.parse_args()

    do_collect = args.all or args.collect
    do_post = args.all or args.post

    # Default: nur post (zum sicheren Betrieb, besonders im MOCK_MODE)
    if not do_collect and not do_post:
        do_post = True

    asyncio.run(_run(do_collect=do_collect, do_post=do_post))


if __name__ == "__main__":
    main()

