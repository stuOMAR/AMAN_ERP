import asyncio
from fastapi import Request
from pydantic import BaseModel
from database import get_system_db
from sqlalchemy import text
from decimal import Decimal, ROUND_HALF_UP

_D4 = Decimal('0.0001')
def _dec(v): return Decimal(str(v or 0))

async def test():
    from utils.tx import transactional
    try:
        with transactional("a23679c0") as db:
            rows = db.execute(text("""
                SELECT id, group_code, group_name, group_name_en, description, tax_ids, is_active, created_at
                FROM tax_groups ORDER BY created_at DESC
            """)).fetchall()

            result = []
            for r in rows:
                item = dict(r._mapping)
                tax_ids = item.get("tax_ids") or []
                if tax_ids:
                    safe_ids = [tid for tid in tax_ids if isinstance(tid, int)]
                    if safe_ids:
                        placeholders = ",".join([f":tid_{i}" for i in range(len(safe_ids))])
                        id_params = {f"tid_{i}": tid for i, tid in enumerate(safe_ids)}
                        taxes = db.execute(text(f"SELECT id, tax_name, rate_value FROM tax_rates WHERE id IN ({placeholders})"), id_params).fetchall()
                        item["taxes"] = [dict(t._mapping) for t in taxes]
                        combined_rate = sum((_dec(t.rate_value) for t in taxes), Decimal("0"))
                        item["combined_rate"] = float(combined_rate.quantize(_D4, ROUND_HALF_UP))
                    else:
                        item["taxes"] = []
                        item["combined_rate"] = 0
                else:
                    item["taxes"] = []
                    item["combined_rate"] = 0
                result.append(item)
            print(result)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())
