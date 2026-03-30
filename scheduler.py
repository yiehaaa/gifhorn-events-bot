"""
Lokaler APScheduler: täglich Sammlung (19:00) und Meta-Posting (20:00), Europe/Berlin.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from config import CRON_COLLECT_TIME, POSTING_TIME, POSTING_TIMEZONE
from main import collect_and_approve_flow, post_approved_events

logger = logging.getLogger(__name__)


def _parse_hh_mm(value: str) -> tuple[int, int]:
    parts = value.replace(" ", "").split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def run_async(coro) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro())
    finally:
        loop.close()


def setup_scheduler() -> BackgroundScheduler:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    tz = timezone(POSTING_TIMEZONE)
    collect_h, collect_m = _parse_hh_mm(CRON_COLLECT_TIME)
    post_h, post_m = _parse_hh_mm(POSTING_TIME)

    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        lambda: run_async(collect_and_approve_flow),
        CronTrigger(hour=collect_h, minute=collect_m, timezone=tz),
        id="collect_job",
        name="Daily Event Collection",
    )
    scheduler.add_job(
        lambda: run_async(post_approved_events),
        CronTrigger(hour=post_h, minute=post_m, timezone=tz),
        id="posting_job",
        name="Daily Meta Posting",
    )
    scheduler.start()
    logger.info(
        "Scheduler läuft (Sammlung %s, Posting %s %s)",
        CRON_COLLECT_TIME,
        POSTING_TIME,
        POSTING_TIMEZONE,
    )
    return scheduler


def main() -> None:
    sched = setup_scheduler()

    def _shutdown(*_: object) -> None:
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sched.shutdown()


if __name__ == "__main__":
    main()
