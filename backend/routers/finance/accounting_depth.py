"""
Phase 5 accounting-depth REST surface.

Thin HTTP layer over the scaffolded services:
  * IFRS 9 ECL provision compute.
  * IAS 2 NRV write-down test.
  * IAS 36 CGU impairment test.
  * IFRS 15 revenue contracts + recognition.
  * E-invoicing submissions (EG ETA / UAE FTA adapters).

All routes are guarded by `finance.*` permissions so integrations cannot
spin up provisions or submit invoices without explicit grants.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text

from database import get_db_connection
from integrations.einvoicing import get_adapter
from routers.auth import get_current_user
from services import ecl_service, ifrs15_revenue_service, impairment_service, nrv_service
from utils.fiscal_lock import check_fiscal_period_open
from utils.i18n import http_error
from utils.permissions import require_permission
from utils.tx import transactional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/finance/accounting-depth", tags=["accounting-depth"])


def _close(db):
    try:
        db.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# IFRS 9 — Expected Credit Loss
# ═══════════════════════════════════════════════════════════════════════════

class ECLComputeRequest(BaseModel):
    as_of_date: Optional[date] = None
    post_journal: bool = False
    provision_account_id: Optional[int] = None
    expense_account_id: Optional[int] = None


@router.post(
    "/ecl/compute",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def ecl_compute(body: ECLComputeRequest, request: Request, current_user=Depends(get_current_user)):
    """Ecl Compute."""
    db = get_db_connection(current_user.company_id)
    try:
        return ecl_service.compute_ecl_provision(
            db,
            company_id=current_user.company_id,
            as_of_date=body.as_of_date,
            post_journal=body.post_journal,
            provision_account_id=body.provision_account_id,
            expense_account_id=body.expense_account_id,
            user_id=current_user.id,
            username=getattr(current_user, "username", None),
        )
    except ValueError:
        db.rollback()
        raise HTTPException(**http_error(400, "invalid_request", request))
    except RuntimeError:
        db.rollback()
        raise HTTPException(**http_error(412, "invalid_request", request))
    except Exception:
        db.rollback()
        logger.exception("ECL compute failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


@router.get(
    "/ecl/provisions",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def ecl_list(current_user=Depends(get_current_user), limit: int = 50):
    """Ecl List."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT id, as_of_date, total_exposure, provision_amount,
                   journal_entry_id, created_at
            FROM ecl_provisions ORDER BY as_of_date DESC, id DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# IAS 2 — NRV
# ═══════════════════════════════════════════════════════════════════════════

class NRVRunRequest(BaseModel):
    as_of_date: Optional[date] = None
    selling_cost_rate: Decimal = Decimal("0.05")
    post_journal: bool = False
    inventory_account_id: Optional[int] = None
    writedown_expense_account_id: Optional[int] = None


@router.post(
    "/nrv/run",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def nrv_run(body: NRVRunRequest, request: Request, current_user=Depends(get_current_user)):
    """Nrv Run."""
    db = get_db_connection(current_user.company_id)
    try:
        return nrv_service.run_nrv_test(
            db,
            company_id=current_user.company_id,
            as_of_date=body.as_of_date,
            selling_cost_rate=body.selling_cost_rate,
            post_journal=body.post_journal,
            inventory_account_id=body.inventory_account_id,
            writedown_expense_account_id=body.writedown_expense_account_id,
            user_id=current_user.id,
            username=getattr(current_user, "username", None),
        )
    except ValueError:
        db.rollback()
        raise HTTPException(**http_error(400, "invalid_request", request))
    except Exception:
        db.rollback()
        logger.exception("NRV run failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


@router.get(
    "/nrv/tests",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def nrv_list(current_user=Depends(get_current_user), limit: int = 100):
    """Nrv List."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT id, as_of_date, product_id, warehouse_id,
                   cost_value, nrv_value, writedown_amount, journal_entry_id
            FROM inventory_nrv_tests ORDER BY as_of_date DESC, id DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# IAS 36 — Impairment
# ═══════════════════════════════════════════════════════════════════════════

class CGUCreateRequest(BaseModel):
    code: str
    name: str


class ImpairmentTestRequest(BaseModel):
    cgu_id: int
    carrying_amount: Decimal
    value_in_use: Optional[Decimal] = None
    fair_value_less_costs: Optional[Decimal] = None
    as_of_date: Optional[date] = None
    post_journal: bool = False
    impairment_expense_account_id: Optional[int] = None
    accumulated_impairment_account_id: Optional[int] = None
    details: Optional[dict] = None


@router.post(
    "/cgu",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def cgu_create(body: CGUCreateRequest, current_user=Depends(get_current_user)):
    """Cgu Create."""
    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            INSERT INTO cash_generating_units (code, name)
            VALUES (:c, :n)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id, code, name, is_active
        """), {"c": body.code, "n": body.name}).fetchone()
        return dict(row._mapping)


@router.get(
    "/cgu",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def cgu_list(current_user=Depends(get_current_user)):
    """Cgu List."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text(
            "SELECT id, code, name, is_active FROM cash_generating_units ORDER BY code"
        )).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        _close(db)


@router.post(
    "/impairment/test",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def impairment_test(body: ImpairmentTestRequest,
                    request: Request,
                    current_user=Depends(get_current_user)):
    """Impairment Test."""
    db = get_db_connection(current_user.company_id)
    try:
        return impairment_service.record_impairment_test(
            db,
            cgu_id=body.cgu_id,
            carrying_amount=body.carrying_amount,
            company_id=current_user.company_id,
            value_in_use=body.value_in_use,
            fair_value_less_costs=body.fair_value_less_costs,
            as_of_date=body.as_of_date,
            post_journal=body.post_journal,
            impairment_expense_account_id=body.impairment_expense_account_id,
            accumulated_impairment_account_id=body.accumulated_impairment_account_id,
            user_id=current_user.id,
            username=getattr(current_user, "username", None),
            details=body.details,
        )
    except ValueError:
        db.rollback()
        raise HTTPException(**http_error(400, "invalid_request", request))
    except Exception:
        db.rollback()
        logger.exception("Impairment test failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# IFRS 15 — Revenue contracts & recognition
# ═══════════════════════════════════════════════════════════════════════════

class POPayload(BaseModel):
    description: str
    standalone_selling_price: Decimal
    recognition_method: str = "point_in_time"  # | over_time


class ContractCreateRequest(BaseModel):
    contract_number: str
    customer_id: Optional[int] = None
    total_transaction_price: Decimal
    currency: str = "SAR"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    obligations: list[POPayload] = []


class RevenueRecogniseRequest(BaseModel):
    po_id: int
    as_of_date: Optional[date] = None
    new_satisfied_pct: Optional[Decimal] = None
    post_journal: bool = False
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None


@router.post(
    "/ifrs15/contracts",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def ifrs15_create_contract(body: ContractCreateRequest,
                           request: Request,
                           current_user=Depends(get_current_user)):
    """Ifrs15 Create Contract."""
    db = get_db_connection(current_user.company_id)
    try:
        contract_id = ifrs15_revenue_service.create_contract(
            db,
            contract_number=body.contract_number,
            customer_id=body.customer_id,
            total_transaction_price=body.total_transaction_price,
            currency=body.currency,
            start_date=body.start_date,
            end_date=body.end_date,
            obligations=[ob.model_dump() for ob in body.obligations],
        )
        return {"contract_id": contract_id}
    except ValueError:
        db.rollback()
        raise HTTPException(**http_error(400, "invalid_request", request))
    except Exception:
        db.rollback()
        logger.exception("IFRS15 contract create failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


@router.get(
    "/ifrs15/contracts/{contract_id}",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def ifrs15_get_contract(contract_id: int, request: Request, current_user=Depends(get_current_user)):
    """Ifrs15 Get Contract."""
    db = get_db_connection(current_user.company_id)
    try:
        c = db.execute(text(
            "SELECT * FROM revenue_contracts WHERE id = :id"
        ), {"id": contract_id}).fetchone()
        if not c:
            raise HTTPException(**http_error(404, "contract_not_found", request))
        pos = db.execute(text("""
            SELECT * FROM performance_obligations WHERE contract_id = :id ORDER BY id
        """), {"id": contract_id}).fetchall()
        return {
            "contract": dict(c._mapping),
            "performance_obligations": [dict(p._mapping) for p in pos],
        }
    finally:
        _close(db)


@router.post(
    "/ifrs15/recognise",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def ifrs15_recognise(body: RevenueRecogniseRequest,
                     request: Request,
                     current_user=Depends(get_current_user)):
    """Ifrs15 Recognise."""
    db = get_db_connection(current_user.company_id)
    try:
        return ifrs15_revenue_service.recognise_revenue(
            db,
            po_id=body.po_id,
            company_id=current_user.company_id,
            as_of_date=body.as_of_date,
            new_satisfied_pct=body.new_satisfied_pct,
            post_journal=body.post_journal,
            debit_account_id=body.debit_account_id,
            credit_account_id=body.credit_account_id,
            user_id=current_user.id,
            username=getattr(current_user, "username", None),
        )
    except ValueError:
        db.rollback()
        raise HTTPException(**http_error(400, "invalid_request", request))
    except Exception:
        db.rollback()
        logger.exception("IFRS15 recognise failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# E-Invoicing submissions
# ═══════════════════════════════════════════════════════════════════════════

class EInvoiceSubmitRequest(BaseModel):
    jurisdiction: str   # EG | AE | SA
    invoice_type: str   # sales | credit_note
    invoice_id: int
    invoice_payload: dict = {}


@router.post(
    "/einvoice/submit",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def einvoice_submit(body: EInvoiceSubmitRequest,
                    request: Request,
                    current_user=Depends(get_current_user)):
    """Einvoice Submit."""
    try:
        adapter = get_adapter(body.jurisdiction)
    except ValueError:
        raise HTTPException(**http_error(400, "invalid_request", request))

    # Fiscal-lock check needs DB access; do it in a short read-only block
    # so we fail fast (and *before* any network round-trip) when the
    # period is closed. The check is idempotent and side-effect free.
    inv_date = (body.invoice_payload or {}).get("invoice_date") or date.today()
    with transactional(current_user.company_id) as db:
        check_fiscal_period_open(db, inv_date, request=request)

    # PR19-fix (F-NEW-052): the ZATCA/ETA submit() is an HTTPS round-trip
    # that can take seconds. Holding a tenant DB connection open across
    # the network call starved the connection pool under load, and any
    # adapter error mid-flight rolled back unrelated DB writes. We now
    # do the network call *outside* the transaction and only enter
    # ``transactional(...)`` to persist the recorded result + (optional)
    # outbox row. Both writes still land atomically — if either fails,
    # neither is committed and the caller can safely retry.
    payload = {"id": body.invoice_id, **(body.invoice_payload or {})}
    try:
        result = adapter.submit(payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("einvoice submit failed at adapter")
        raise HTTPException(**http_error(500, "internal_error", request))

    resp = result.response or {}
    is_offline = bool(resp.get("offline"))
    outcome = (result.status or "").lower()
    needs_outbox = outcome in ("failed", "error", "rejected") or is_offline

    with transactional(current_user.company_id) as db:
        try:
            db.execute(text("""
                SELECT id FROM invoices
                WHERE id = :id
                FOR UPDATE
            """), {"id": body.invoice_id}).fetchone()

            row = db.execute(text("""
                INSERT INTO e_invoice_submissions (jurisdiction, invoice_type, invoice_id,
                    document_uuid, submission_status, submitted_at, response_payload, error_message)
                VALUES (:j, :t, :iid, :u, :s, CURRENT_TIMESTAMP, CAST(:r AS JSONB), :err)
                RETURNING id
            """), {
                "j": body.jurisdiction.upper(),
                "t": body.invoice_type,
                "iid": body.invoice_id,
                "u": result.document_uuid,
                "s": result.status,
                "r": json.dumps(result.response or {}, default=str, ensure_ascii=False),
                "err": result.error_message,
            }).fetchone()

            # EINV-F2: enqueue submissions for automatic retry via outbox.
            # T1.5a (#419z): treat "offline" success the same as a transient failure —
            # the adapter built local artifacts but never reached ZATCA, so the
            # payload MUST be persisted for later relay or the invoice is lost.
            if needs_outbox:
                err_msg = result.error_message or (
                    "offline: adapter unconfigured (no PCSID/secret) — payload saved for retry"
                    if is_offline else "submission failed"
                )
                db.execute(text("""
                    INSERT INTO einvoice_outbox
                        (invoice_id, adapter, payload, status, attempts,
                         idempotency_key, last_error, last_attempt_at, next_attempt_at)
                    VALUES (:iid, :adp, CAST(:pl AS JSONB), 'pending', 1,
                            :idem, :err, CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP + INTERVAL '5 minutes')
                    ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                    DO UPDATE SET payload = EXCLUDED.payload,
                                  last_error = EXCLUDED.last_error,
                                  next_attempt_at = EXCLUDED.next_attempt_at,
                                  updated_at = CURRENT_TIMESTAMP
                """), {
                    "iid": body.invoice_id,
                    "adp": body.jurisdiction.upper(),
                    "pl": json.dumps(payload, default=str, ensure_ascii=False),
                    "idem": f"einvoice:{body.jurisdiction.upper()}:{body.invoice_id}",
                    "err": err_msg,
                })

            return {
                "submission_id": row.id,
                "status": result.status,
                "document_uuid": result.document_uuid,
                "error_message": result.error_message,
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("einvoice submit persistence failed")
            raise HTTPException(**http_error(500, "internal_error", request))


@router.get(
    "/einvoice/submissions",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def einvoice_list(current_user=Depends(get_current_user), limit: int = 50,
                  jurisdiction: Optional[str] = None):
    """Einvoice List."""
    db = get_db_connection(current_user.company_id)
    try:
        if jurisdiction:
            rows = db.execute(text("""
                SELECT id, jurisdiction, invoice_type, invoice_id, document_uuid,
                       submission_status, submitted_at, error_message
                FROM e_invoice_submissions
                WHERE jurisdiction = :j
                ORDER BY id DESC LIMIT :lim
            """), {"j": jurisdiction.upper(), "lim": limit}).fetchall()
        else:
            rows = db.execute(text("""
                SELECT id, jurisdiction, invoice_type, invoice_id, document_uuid,
                       submission_status, submitted_at, error_message
                FROM e_invoice_submissions
                ORDER BY id DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        _close(db)


@router.post(
    "/einvoice/{submission_id}/refresh",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def einvoice_refresh(submission_id: int, request: Request, current_user=Depends(get_current_user)):
    """Einvoice Refresh."""
    db = get_db_connection(current_user.company_id)
    try:
        sub = db.execute(text("""
            SELECT id, jurisdiction, document_uuid
            FROM e_invoice_submissions WHERE id = :id
        """), {"id": submission_id}).fetchone()
        if not sub:
            raise HTTPException(**http_error(404, "einvoice_submission_not_found", request))
        if not sub.document_uuid:
            raise HTTPException(**http_error(400, "einvoice_no_document_uuid", request))
        adapter = get_adapter(sub.jurisdiction)
        result = adapter.fetch_status(sub.document_uuid)
        db.execute(text("""
            UPDATE e_invoice_submissions
               SET submission_status = :s,
                   response_payload = CAST(:r AS JSONB),
                   error_message = :err
             WHERE id = :id
        """), {
            "s": result.status,
            "r": json.dumps(result.response or {}, default=str, ensure_ascii=False),
            "err": result.error_message,
            "id": submission_id,
        })
        db.commit()
        return {"submission_id": submission_id, "status": result.status,
                "error_message": result.error_message}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("einvoice refresh failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# EINV-F2 — E-invoice outbox relay (Phase-11 Sprint-4)
# ═══════════════════════════════════════════════════════════════════════════

MAX_OUTBOX_ATTEMPTS = 6  # exponential back-off caps out at ~5.3 hours


@router.post(
    "/einvoice/outbox/relay",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def einvoice_outbox_relay(
    limit: int = 20,
    request: Request = None,
    current_user=Depends(get_current_user),
):
    """Retry pending e-invoice submissions from the outbox.

    Picks up to ``limit`` rows whose ``next_attempt_at`` is due, re-invokes
    the configured adapter, and records the outcome. Rows that exceed
    ``MAX_OUTBOX_ATTEMPTS`` are marked ``giveup`` for manual review.
    """
    with transactional(current_user.company_id) as db:
        processed, succeeded, failed, giveup = 0, 0, 0, 0
        try:
            rows = db.execute(
                text(
                    """
                SELECT id, invoice_id, adapter, payload, attempts, idempotency_key
                FROM einvoice_outbox
                WHERE status = 'pending'
                  AND next_attempt_at <= CURRENT_TIMESTAMP
                ORDER BY next_attempt_at
                LIMIT :lim
                FOR UPDATE SKIP LOCKED
                """
                ),
                {"lim": int(max(1, min(limit, 100)))},
            ).fetchall()

            # PR19-fix (F-NEW-053): each row gets its own SAVEPOINT via
            # ``db.begin_nested()``. The outer transaction still holds
            # the FOR UPDATE SKIP LOCKED lease on the claimed rows, but
            # if a DB exception fires while persisting one row's outcome
            # (e.g. constraint violation on the UPDATE), only that row's
            # savepoint rolls back — the rows that ZATCA has already
            # accepted in earlier iterations stay committed at outer
            # commit. Without the savepoint, a single DB error on row N
            # would roll back the success UPDATEs for rows 1..N-1, but
            # ZATCA would still hold those submissions, producing
            # duplicate clearance attempts on the next relay.
            for r in rows:
                processed += 1
                payload = r.payload if isinstance(r.payload, dict) else {}
                payload.setdefault("id", r.invoice_id)
                attempts = int(r.attempts or 0) + 1
                payload["idempotency_key"] = r.idempotency_key or f"einvoice-outbox:{r.id}"
                try:
                    adapter = get_adapter(r.adapter or "SA")
                    result = adapter.submit(payload)
                except Exception as exc:
                    # Network / adapter error — record failure inside
                    # its own savepoint so a subsequent DB error during
                    # the failure UPDATE itself doesn't poison sibling
                    # rows.
                    with db.begin_nested():
                        if attempts >= MAX_OUTBOX_ATTEMPTS:
                            db.execute(
                                text(
                                    "UPDATE einvoice_outbox SET status = 'giveup', "
                                    "attempts = :a, last_attempt_at = CURRENT_TIMESTAMP, "
                                    "last_error = :err, updated_at = CURRENT_TIMESTAMP "
                                    "WHERE id = :id"
                                ),
                                {"a": attempts, "err": str(exc)[:500], "id": r.id},
                            )
                            giveup += 1
                        else:
                            db.execute(
                                text(
                                    "UPDATE einvoice_outbox SET attempts = :a, "
                                    "last_attempt_at = CURRENT_TIMESTAMP, "
                                    "next_attempt_at = CURRENT_TIMESTAMP + "
                                    "    (INTERVAL '5 minutes' * POWER(2, :a - 1)), "
                                    "last_error = :err, updated_at = CURRENT_TIMESTAMP "
                                    "WHERE id = :id"
                                ),
                                {"a": attempts, "err": str(exc)[:500], "id": r.id},
                            )
                            failed += 1
                    continue

                # Adapter returned. Persist outcome inside a savepoint
                # so any DB error here cannot roll back sibling rows
                # whose ZATCA submission is already accepted.
                outcome = (result.status or "").lower()
                # T1.5a (#419z): offline responses must NOT be marked submitted —
                # the adapter built artifacts but did not reach ZATCA.
                is_offline = bool((result.response or {}).get("offline"))
                try:
                    with db.begin_nested():
                        if outcome in ("success", "accepted", "ok", "cleared", "reported") and not is_offline:
                            db.execute(
                                text(
                                    "UPDATE einvoice_outbox SET status = 'submitted', "
                                    "attempts = :a, last_attempt_at = CURRENT_TIMESTAMP, "
                                    "response = CAST(:r AS JSONB), last_error = NULL, "
                                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                                ),
                                {
                                    "a": attempts,
                                    "r": json.dumps(result.response or {}, default=str, ensure_ascii=False),
                                    "id": r.id,
                                },
                            )
                            succeeded += 1
                        else:
                            err = result.error_message or outcome or "unknown failure"
                            if attempts >= MAX_OUTBOX_ATTEMPTS:
                                db.execute(
                                    text(
                                        "UPDATE einvoice_outbox SET status = 'giveup', "
                                        "attempts = :a, last_attempt_at = CURRENT_TIMESTAMP, "
                                        "last_error = :err, updated_at = CURRENT_TIMESTAMP "
                                        "WHERE id = :id"
                                    ),
                                    {"a": attempts, "err": str(err)[:500], "id": r.id},
                                )
                                giveup += 1
                            else:
                                db.execute(
                                    text(
                                        "UPDATE einvoice_outbox SET attempts = :a, "
                                        "last_attempt_at = CURRENT_TIMESTAMP, "
                                        "next_attempt_at = CURRENT_TIMESTAMP + "
                                        "    (INTERVAL '5 minutes' * POWER(2, :a - 1)), "
                                        "last_error = :err, updated_at = CURRENT_TIMESTAMP "
                                        "WHERE id = :id"
                                    ),
                                    {"a": attempts, "err": str(err)[:500], "id": r.id},
                                )
                                failed += 1
                except Exception:
                    logger.exception(
                        "outbox-relay: per-row persistence failed for id=%s "
                        "(adapter outcome=%s); savepoint rolled back, sibling rows preserved",
                        r.id, outcome,
                    )
            return {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "giveup": giveup,
            }
        except Exception:
            logger.exception("einvoice outbox relay failed")
            raise HTTPException(**http_error(500, "internal_error", request))


@router.get(
    "/einvoice/outbox",
    dependencies=[Depends(require_permission("finance.accounting_view"))],
)
def einvoice_outbox_list(
    status_filter: Optional[str] = None,
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """List outbox entries (for monitoring and manual retry UIs)."""
    db = get_db_connection(current_user.company_id)
    try:
        if status_filter:
            rows = db.execute(
                text(
                    "SELECT id, invoice_id, adapter, status, attempts, "
                    "last_error, last_attempt_at, next_attempt_at, created_at "
                    "FROM einvoice_outbox WHERE status = :s "
                    "ORDER BY id DESC LIMIT :lim"
                ),
                {"s": status_filter, "lim": limit},
            ).fetchall()
        else:
            rows = db.execute(
                text(
                    "SELECT id, invoice_id, adapter, status, attempts, "
                    "last_error, last_attempt_at, next_attempt_at, created_at "
                    "FROM einvoice_outbox ORDER BY id DESC LIMIT :lim"
                ),
                {"lim": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        _close(db)
