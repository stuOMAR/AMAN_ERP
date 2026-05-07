"""
Transactional outbox relay.

Pairs with the ``event_outbox`` table (created in Phase 6). The typical
flow is:

  1. A DB transaction posts business data AND inserts an outbox row in
     the same commit. This guarantees the event is never lost (unlike
     a best-effort in-process publish).
  2. A background worker picks up ``delivered_at IS NULL`` rows and
     publishes them via the in-process event bus (and, if enabled, the
     Redis bridge forwards to downstream consumers).
  3. On success we set ``delivered_at = now()``; on failure we bump
     ``attempts`` and store ``last_error``.

This module exposes:

  * :func:`enqueue`      — insert an outbox row (call inside your txn).
  * :func:`drain_once`   — process up to ``batch_size`` pending rows.
  * :func:`start_worker` — APScheduler-compatible periodic job.

It intentionally does **not** auto-start; wire it from your scheduler
(``services/scheduler.py``) or from an out-of-band worker process.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from .event_bus import publish as _bus_publish

logger = logging.getLogger(__name__)

_DEFAULT_BATCH = 100
_MAX_ATTEMPTS = 10


def enqueue(db, event_name: str, payload: Optional[Dict[str, Any]] = None) -> int:
    """
    Insert an outbox row. Call INSIDE the caller's transaction so the
    event is committed atomically with the business data.
    """
    row = db.execute(
        text(
            "INSERT INTO event_outbox (event_name, payload) "
            "VALUES (:n, CAST(:p AS JSONB)) RETURNING id"
        ),
        {"n": event_name, "p": json.dumps(payload or {}, default=str)},
    ).fetchone()
    return int(row[0])


def drain_once(db, batch_size: int = _DEFAULT_BATCH) -> Dict[str, int]:
    """
    Process up to ``batch_size`` undelivered rows. Returns a dict with
    ``attempted`` / ``delivered`` / ``failed`` counts. Must be called in
    its own transaction.
    """
    rows = db.execute(
        text(
            "SELECT id, event_name, payload, attempts FROM event_outbox "
            "WHERE delivered_at IS NULL AND attempts < :max_att "
            "ORDER BY id "
            "LIMIT :n FOR UPDATE SKIP LOCKED"
        ),
        {"n": batch_size, "max_att": _MAX_ATTEMPTS},
    ).fetchall()

    delivered = failed = 0
    for r in rows:
        ev_id, ev_name, payload, attempts = r[0], r[1], r[2], r[3]
        data = payload if isinstance(payload, dict) else (json.loads(payload) if payload else {})
        try:
            _bus_publish(ev_name, data)
            db.execute(
                text("UPDATE event_outbox SET delivered_at = :t WHERE id = :id"),
                {"t": datetime.now(timezone.utc), "id": ev_id},
            )
            delivered += 1
        except Exception as e:
            logger.exception("outbox relay: publish failed for id=%s", ev_id)
            new_attempts = (attempts or 0) + 1
            # T10.2 #142: when a row exhausts its attempts, prefix
            # last_error with ``DEAD:`` so operators can distinguish
            # "still retrying" from "gave up". Without this, dead rows
            # remain ``delivered_at IS NULL`` forever and look identical
            # to fresh rows in dashboards/queries.
            err_text = str(e)[:480]
            if new_attempts >= _MAX_ATTEMPTS:
                err_text = f"DEAD:max_attempts_exceeded: {err_text}"
            db.execute(
                text(
                    "UPDATE event_outbox "
                    "   SET attempts = attempts + 1, last_error = :err "
                    " WHERE id = :id"
                ),
                {"err": err_text, "id": ev_id},
            )
            if new_attempts >= _MAX_ATTEMPTS:
                db.execute(
                    text("""
                        INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                        SELECT u.id,
                               'outbox_dead_letter',
                               'Outbox event delivery failed',
                               :message,
                               '/settings/integrations/outbox',
                               FALSE,
                               NOW()
                        FROM company_users u
                        WHERE u.role IN ('admin', 'system_admin')
                           OR COALESCE(u.permissions::text, '') LIKE '%admin%'
                    """),
                    {"message": f"Event {ev_name} #{ev_id} reached max retry attempts."},
                )
            failed += 1
    db.commit()
    return {"attempted": len(rows), "delivered": delivered, "failed": failed}


def start_worker(get_db_callable, interval_seconds: int = 30, batch_size: int = _DEFAULT_BATCH):
    """
    Register a periodic drain job with APScheduler (imported lazily to
    avoid making scheduler a hard dependency of this module).

    ``get_db_callable`` must return a *fresh* DB session each time — the
    relay commits and discards the session between runs.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
    except Exception as e:   # pragma: no cover - scheduler missing
        logger.warning("outbox_relay: APScheduler unavailable (%s); worker not started", e)
        return None

    sched = BackgroundScheduler(timezone="UTC")

    def _tick():
        db = get_db_callable()
        try:
            result = drain_once(db, batch_size=batch_size)
            if result["attempted"]:
                logger.info("outbox_relay: %s", result)
        except Exception:
            logger.exception("outbox_relay: drain failed")
        finally:
            try:
                db.close()
            except Exception:
                pass

    sched.add_job(_tick, "interval", seconds=interval_seconds,
                  id="outbox_relay", max_instances=1, coalesce=True)
    sched.start()
    logger.info("📮 outbox_relay: worker started (every %ss, batch=%s)",
                interval_seconds, batch_size)
    return sched
