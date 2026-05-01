"""
TASK-028 — Dedicated scheduler worker process.

Run this as a separate service in production so scheduled jobs fire exactly
once regardless of how many web replicas are running.

Usage:
    SCHEDULER_MODE=dedicated python -m worker
    # or: python worker.py

In docker-compose:
    worker:
      build: ./backend
      command: python -m worker
      environment:
        SCHEDULER_MODE: dedicated
        # + same DB / Redis / SECRET_KEY env as the web service
      deploy:
        replicas: 1   # MUST be exactly 1 to avoid duplicate firings.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("aman.worker")

# T4.1 — Sentry init in worker process
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[SqlalchemyIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            environment=os.environ.get("APP_ENV", "production"),
            release="aman-erp@2.0.0",
        )
        logger.info("✅ Sentry initialized in scheduler worker")
    except ImportError:
        logger.warning("sentry-sdk not installed — Sentry disabled")


def main() -> int:
    # Force-enable the scheduler regardless of env default: this process's
    # sole purpose is to run scheduled jobs.
    from services.scheduler import start_scheduler, scheduler

    logger.info("🛠  AMAN ERP scheduler worker starting …")
    start_scheduler()
    logger.info("✅ Scheduler running. Press Ctrl-C to stop.")

    stop = {"requested": False}

    def _shutdown(signum, _frame):
        logger.info("Signal %s received, shutting down scheduler …", signum)
        stop["requested"] = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not stop["requested"]:
            time.sleep(1)
    finally:
        try:
            scheduler.shutdown(wait=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("Scheduler shutdown raised: %s", exc)
    logger.info("👋 Worker stopped cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
