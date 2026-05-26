"""
AMAN ERP — Duplicate Detection Utility
كشف التكرارات في العملاء والموردين والأصناف
"""

from sqlalchemy import text
from typing import List, Dict
import logging
import re

logger = logging.getLogger(__name__)


def normalize_text(s: str) -> str:
    """Normalize Arabic/English text for comparison"""
    if not s:
        return ""
    s = s.strip().lower()
    # Remove common Arabic articles
    s = re.sub(r'^(ال|مؤسسة|شركة|مصنع|محل)\s*', '', s)
    # Remove extra spaces
    s = re.sub(r'\s+', ' ', s)
    return s


def find_duplicate_parties(db, name: str, phone: str = None,
                           email: str = None, tax_number: str = None,
                           exclude_id: int = None) -> List[Dict]:
    """
    Find potential duplicate parties (customers/suppliers).
    Returns a list of matching records with similarity score.
    """
    duplicates = []
    params = {}

    conditions = []

    # 1. Exact tax number match (strongest signal)
    if tax_number and tax_number.strip():
        conditions.append("p.tax_number = :tax")
        params["tax"] = tax_number.strip()

    # 2. Exact phone match
    if phone and phone.strip():
        clean_phone = re.sub(r'[^\d+]', '', phone)
        if len(clean_phone) >= 7:
            conditions.append("REGEXP_REPLACE(p.phone, '[^0-9+]', '', 'g') = :phone")
            params["phone"] = clean_phone

    # 3. Exact email match
    if email and email.strip():
        conditions.append("LOWER(p.email) = LOWER(:email)")
        params["email"] = email.strip()

    # 4. Similar name (trigram if available, else LIKE)
    if name and name.strip():
        normalized = normalize_text(name)
        conditions.append("""(
            LOWER(p.name) = LOWER(:exact_name)
            OR LOWER(p.name) LIKE :like_name
            OR LOWER(p.name_en) = LOWER(:exact_name)
            OR LOWER(p.name_en) LIKE :like_name
        )""")
        params["exact_name"] = name.strip()
        params["like_name"] = f"%{normalized}%"

    if not conditions:
        return []

    exclude_clause = ""
    if exclude_id:
        exclude_clause = "AND p.id != :exclude_id"
        params["exclude_id"] = exclude_id

    query = f"""
        SELECT p.id, p.name, p.name_en, p.phone, p.email,
               p.tax_number, p.party_type, p.status
        FROM parties p
        WHERE ({' OR '.join(conditions)}) {exclude_clause}
        ORDER BY p.id
        LIMIT 10
    """

    try:
        rows = db.execute(text(query), params).fetchall()
        for row in rows:
            match_reasons = []
            score = 0

            r = dict(row._mapping)
            if tax_number and r.get('tax_number') == tax_number.strip():
                match_reasons.append("tax_number_match")
                score += 100
            if phone and r.get('phone'):
                if re.sub(r'[^\d+]', '', r['phone']) == re.sub(r'[^\d+]', '', phone):
                    match_reasons.append("phone_match")
                    score += 80
            if email and r.get('email') and r['email'].lower() == email.strip().lower():
                match_reasons.append("email_match")
                score += 90
            if name:
                if r.get('name', '').lower() == name.strip().lower():
                    match_reasons.append("exact_name_match")
                    score += 70
                elif normalize_text(name) in normalize_text(r.get('name', '')):
                    match_reasons.append("similar_name")
                    score += 40

            duplicates.append({
                **r,
                "match_reasons": match_reasons,
                "similarity_score": min(score, 100)
            })

        return sorted(duplicates, key=lambda x: x['similarity_score'], reverse=True)

    except Exception as e:
        logger.error(f"Duplicate detection error: {e}")
        return []


def find_duplicate_products(db, product_name: str = None, sku: str = None,
                            barcode: str = None, exclude_id: int = None) -> List[Dict]:
    """Find potential duplicate products"""
    conditions = []
    params = {}

    if sku and sku.strip():
        conditions.append("p.sku = :sku")
        params["sku"] = sku.strip()

    if barcode and barcode.strip():
        conditions.append("p.barcode = :barcode")
        params["barcode"] = barcode.strip()

    if product_name and product_name.strip():
        conditions.append("""(
            LOWER(p.product_name) = LOWER(:name)
            OR LOWER(p.product_name_en) = LOWER(:name)
            OR LOWER(p.product_name) LIKE :like_name
        )""")
        params["name"] = product_name.strip()
        params["like_name"] = f"%{normalize_text(product_name)}%"

    if not conditions:
        return []

    exclude_clause = ""
    if exclude_id:
        exclude_clause = "AND p.id != :exclude_id"
        params["exclude_id"] = exclude_id

    try:
        rows = db.execute(text(f"""
            SELECT p.id, p.product_name, p.product_name_en, p.sku,
                   p.barcode, p.category_id, p.status
            FROM products p
            WHERE ({' OR '.join(conditions)}) {exclude_clause}
            ORDER BY p.id LIMIT 10
        """), params).fetchall()

        results = []
        for row in rows:
            r = dict(row._mapping)
            reasons = []
            score = 0
            if sku and r.get('sku') == sku.strip():
                reasons.append("sku_match")
                score += 100
            if barcode and r.get('barcode') == barcode.strip():
                reasons.append("barcode_match")
                score += 100
            if product_name and r.get('product_name', '').lower() == product_name.strip().lower():
                reasons.append("exact_name")
                score += 70

            results.append({**r, "match_reasons": reasons, "similarity_score": min(score, 100)})

        return sorted(results, key=lambda x: x['similarity_score'], reverse=True)
    except Exception as e:
        logger.error(f"Product duplicate check error: {e}")
        return []
