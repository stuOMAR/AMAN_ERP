from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_manufacturing_costing_frontend_uses_backend_variance_fields():
    costing = _read("frontend/src/pages/Manufacturing/ManufacturingCosting.jsx")
    reports = _read("backend/routers/manufacturing/core/reports.py")

    assert "variance_direction" in costing
    assert "variance_prefix" in costing
    assert "o.variance_pct" in costing
    assert "decimal.js" not in costing
    assert "new Decimal" not in costing
    assert ".minus(" not in costing
    assert ".div(" not in costing
    assert ".times(" not in costing

    for token in [
        '"estimated_cost"',
        '"actual_cost"',
        '"variance"',
        '"variance_pct"',
        '"variance_direction"',
        '"variance_prefix"',
    ]:
        assert token in reports


def test_work_order_status_progress_is_backend_authoritative():
    report = _read("frontend/src/pages/Manufacturing/WorkOrderStatusReport.jsx")
    orders = _read("backend/routers/manufacturing/core/orders.py")
    schemas = _read("backend/schemas/manufacturing_advanced.py")
    reports = _read("backend/routers/manufacturing/core/reports.py")

    assert "o.completion_percent" in report
    assert "o.completion_status" in report
    assert "o.is_overdue" in report
    assert "summary?.completion_rate_pct" in report
    assert "produced_quantity || 0) / o.quantity" not in report
    assert "Math.min" not in report
    assert "Math.round" not in report
    assert ".filter(o => o.status" not in report

    for token in [
        "completion_percent",
        "completion_status",
        "completion_direction",
        "is_overdue",
    ]:
        assert token in orders
        assert token in schemas

    assert "status: Optional[str]" in orders
    assert "start_date: Optional[date]" in orders
    assert "end_date: Optional[date]" in orders
    assert "completion_rate_pct" in reports
    assert "share_pct" in reports


def test_capacity_and_analytics_use_backend_percentages_and_directions():
    analytics = _read("frontend/src/pages/Manufacturing/ProductionAnalytics.jsx")
    capacity = _read("frontend/src/pages/Manufacturing/CapacityPlanning.jsx")
    reports = _read("backend/routers/manufacturing/core/reports.py")

    assert "data.share_pct" in analytics
    assert "wc.utilization_direction" in analytics
    assert "data.count / totalOrders" not in analytics
    assert "utilization_percent >= 70" not in analytics

    for token in [
        "availability_direction",
        "performance_direction",
        "quality_direction",
        "oee_direction",
        "utilization_direction",
    ]:
        assert token in reports
        assert token in capacity or token == "utilization_direction"

    assert "val >= 85" not in capacity
    assert "val >= 60" not in capacity


def test_partial_completion_sends_raw_inputs_and_backend_validates_qty():
    partial = _read("frontend/src/pages/manufacturing/ProductionPartialCompletion.jsx")
    production = _read("backend/routers/manufacturing/production.py")

    assert "qty," in partial
    assert "decimal.js" not in partial
    assert "new Decimal" not in partial
    assert ".lte(" not in partial
    assert ".gt(" not in partial
    assert "Field(gt=0)" in production


def test_manufacturing_frontend_no_targeted_authoritative_calculations():
    files = [
        "frontend/src/pages/Manufacturing/ManufacturingCosting.jsx",
        "frontend/src/pages/Manufacturing/WorkOrderStatusReport.jsx",
        "frontend/src/pages/Manufacturing/ProductionAnalytics.jsx",
        "frontend/src/pages/Manufacturing/CapacityPlanning.jsx",
        "frontend/src/pages/manufacturing/ProductionPartialCompletion.jsx",
        "frontend/src/pages/Manufacturing/JobCards.jsx",
    ]
    forbidden = [
        re.compile(r"new Decimal"),
        re.compile(r"\.minus\("),
        re.compile(r"\.div\("),
        re.compile(r"\.times\("),
        re.compile(r"parseFloat"),
        re.compile(r"(?<!format)Number\("),
        re.compile(r"toFixed"),
        re.compile(r"Math\.min"),
        re.compile(r"Math\.round"),
        re.compile(r"produced_quantity.*\/.*quantity"),
        re.compile(r"data\.count\s*\/\s*totalOrders"),
        re.compile(r"utilization_percent\s*>="),
    ]

    offenders = []
    for relative_path in files:
        source = _read(relative_path)
        for pattern in forbidden:
            if pattern.search(source):
                offenders.append(f"{relative_path}: {pattern.pattern}")

    assert offenders == []
