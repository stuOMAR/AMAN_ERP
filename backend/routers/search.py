"""T7.2 — Unified search across multiple entities.

Single endpoint ``GET /search?q=...&entities=...&limit=N`` that runs the
same query against five entity types in parallel UNION ALL fashion,
ranking results with ``ts_rank_cd`` over the ``search_vector`` GIN-indexed
tsvector columns added by alembic 0022. For partial / typo-tolerant
matches it also OR-joins against the pg_trgm GIN indexes added by
0020.

DoD: search "محمد" returns matches across 5 entities in < 200ms.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from utils.i18n import http_error
from utils.tx import transactional
from utils.permissions import require_permission
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


# entity_key -> (table, label_expr, secondary_expr, ts_filter_expr, trgm_or_clause)
# label_expr  → human-readable display string
# secondary   → optional secondary identifier (e.g. code, number)
# ts_filter   → search_vector @@ plainto_tsquery('simple', :q)
# trgm_clause → OR fallback using existing trgm-indexed columns for partial /
#               substring matches that don't tokenise (e.g. "12345" inside a
#               phone or invoice number).
_ENTITY_QUERIES: Dict[str, Dict[str, str]] = {
    "parties": {
        "table": "parties",
        "select": (
            "SELECT 'parties'::text AS entity, id, "
            "       name AS label, "
            "       coalesce(tax_number, phone, email) AS secondary, "
            "       ts_rank_cd(search_vector, q) AS rank "
            "FROM parties, plainto_tsquery('simple', :q) q "
            "WHERE search_vector @@ q "
            "   OR name ILIKE :like_q "
            "   OR phone ILIKE :like_q "
            "   OR tax_number ILIKE :like_q "
        ),
    },
    "products": {
        "table": "products",
        "select": (
            "SELECT 'products'::text AS entity, id, "
            "       product_name AS label, "
            "       coalesce(product_code, barcode) AS secondary, "
            "       ts_rank_cd(search_vector, q) AS rank "
            "FROM products, plainto_tsquery('simple', :q) q "
            "WHERE search_vector @@ q "
            "   OR product_name ILIKE :like_q "
            "   OR product_code ILIKE :like_q "
            "   OR barcode ILIKE :like_q "
        ),
    },
    "invoices": {
        "table": "invoices",
        "select": (
            "SELECT 'invoices'::text AS entity, id, "
            "       invoice_number AS label, "
            "       coalesce(notes, '') AS secondary, "
            "       ts_rank_cd(search_vector, q) AS rank "
            "FROM invoices, plainto_tsquery('simple', :q) q "
            "WHERE search_vector @@ q "
            "   OR invoice_number ILIKE :like_q "
        ),
    },
    "sales_orders": {
        "table": "sales_orders",
        "select": (
            "SELECT 'sales_orders'::text AS entity, id, "
            "       so_number AS label, "
            "       coalesce(notes, '') AS secondary, "
            "       ts_rank_cd(search_vector, q) AS rank "
            "FROM sales_orders, plainto_tsquery('simple', :q) q "
            "WHERE search_vector @@ q "
            "   OR so_number ILIKE :like_q "
        ),
    },
    "purchase_orders": {
        "table": "purchase_orders",
        "select": (
            "SELECT 'purchase_orders'::text AS entity, id, "
            "       po_number AS label, "
            "       coalesce(notes, '') AS secondary, "
            "       ts_rank_cd(search_vector, q) AS rank "
            "FROM purchase_orders, plainto_tsquery('simple', :q) q "
            "WHERE search_vector @@ q "
            "   OR po_number ILIKE :like_q "
        ),
    },
}

ALL_ENTITIES = list(_ENTITY_QUERIES.keys())


def _table_exists_with_search_vector(db, table: str) -> bool:
    """Skip entities whose tenant DB hasn't applied 0022 yet."""
    try:
        res = db.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name='search_vector' "
                "LIMIT 1"
            ),
            {"t": table},
        ).fetchone()
        return res is not None
    except Exception:
        return False


@router.get(
    "",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_permission(["parties.view", "sales.view", "buying.view", "inventory.view"]))],
)
async def unified_search(
    q: str,
    entities: Optional[str] = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """بحث موحَّد عبر الأطراف والمنتجات والفواتير وأوامر البيع/الشراء.

    Query params
    ------------
    q : str        النص المراد البحث عنه (مدعوم العربية والإنجليزية).
    entities       اختياري — قائمة مفصولة بفواصل من الكيانات المرغوبة:
                   parties, products, invoices, sales_orders, purchase_orders.
                   إذا لم يُمرَّر، يُبحث في الجميع.
    limit          عدد النتائج الأقصى لكل كيان (افتراضي 20).
    """
    q_clean = (q or "").strip()
    if not q_clean:
        return {"query": "", "items": [], "total": 0}

    if entities:
        wanted = [e.strip() for e in entities.split(",") if e.strip()]
        wanted = [e for e in wanted if e in _ENTITY_QUERIES]
    else:
        wanted = ALL_ENTITIES
    if not wanted:
        return {"query": q_clean, "items": [], "total": 0}

    # Cap per-entity limit to keep p99 < 200ms.
    per_entity = max(1, min(limit, 50))

    items: List[Dict[str, Any]] = []
    with transactional(current_user.company_id) as db:
        for ent in wanted:
            if not _table_exists_with_search_vector(db, _ENTITY_QUERIES[ent]["table"]):
                continue
            sql = _ENTITY_QUERIES[ent]["select"] + " ORDER BY rank DESC, id DESC LIMIT :limit"
            try:
                res = db.execute(
                    text(sql),
                    {"q": q_clean, "like_q": f"%{q_clean}%", "limit": per_entity},
                ).fetchall()
                for r in res:
                    items.append(dict(r._mapping))
            except Exception as e:
                # Schema variations between tenants — log and continue with
                # the rest of the entities so a partial failure doesn't kill
                # the whole search.
                logger.warning(f"search/{ent} skipped: {e}")
                continue

    # Stable sort: by rank desc, then entity, then id.
    items.sort(key=lambda x: (-(x.get("rank") or 0.0), x.get("entity", ""), -(x.get("id") or 0)))
    return {"query": q_clean, "entities": wanted, "items": items, "total": len(items)}
