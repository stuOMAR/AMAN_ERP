"""
Uniform report-view audit decorator for FastAPI endpoints.

Wraps report GET endpoints so every successful request writes a
uniform audit row via ``log_activity`` with:
  {report_key, filters, period, generated_at}

Works as a FastAPI ``Depends``-compatible callable.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, Request

logger = logging.getLogger(__name__)


def audit_report_view(report_key: str):
    """Return a FastAPI dependency that audits report access.

    Usage::

        @router.get(
            "/reports/balance-sheet",
            dependencies=[Depends(audit_report_view("balance_sheet"))],
        )
        def balance_sheet(...): ...

    Or as a standalone dependency inside the handler::

        def handler(request: Request, _audit=Depends(audit_report_view("kpi"))):
            ...
    """

    async def _dependency(request: Request, current_user: Any = None):
        try:
            from services.audit_writer import log_activity
            from database import get_db_connection

            company_id = (
                current_user.get("company_id")
                if isinstance(current_user, dict)
                else getattr(current_user, "company_id", None)
            )
            actor_id = (
                current_user.get("id")
                if isinstance(current_user, dict)
                else getattr(current_user, "id", None)
            )

            # Extract common query params for the audit payload
            params = dict(request.query_params)
            filters = {k: v for k, v in params.items() if k not in ("token", "sig", "exp")}
            period = filters.get("period") or filters.get("date_range") or filters.get("as_of")

            if company_id:
                conn = get_db_connection(str(company_id))
                try:
                    log_activity(
                        conn,
                        action="report.view",
                        entity_type="report",
                        entity_id=None,
                        actor_id=actor_id,
                        details={
                            "report_key": report_key,
                            "filters": filters,
                            "period": period,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        critical=False,
                    )
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.debug("audit_report_view: log_activity failed for %s", report_key, exc_info=True)
                finally:
                    conn.close()
        except Exception:
            logger.debug("audit_report_view: outer error for %s", report_key, exc_info=True)

        return True  # dependency return value is unused by callers

    return _dependency
