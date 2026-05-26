from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_stock_frontend_uses_backend_available_quantities():
    stock_reports = _read("frontend/src/pages/Stock/StockReports.jsx")
    transfer_form = _read("frontend/src/pages/Stock/StockTransferForm.jsx")
    product_list = _read("frontend/src/pages/Stock/ProductList.jsx")

    assert "item.available_quantity" in stock_reports
    assert "item.stock_status" in stock_reports
    assert "item.has_negative_available" in stock_reports
    assert "available_quantity <" not in stock_reports
    assert "available_quantity <=" not in stock_reports
    assert "item.quantity <" not in stock_reports
    assert "item.quantity <=" not in stock_reports

    assert "p.available_quantity ?? p.quantity" in transfer_form

    assert "row.available_stock ?? val" in product_list
    assert "wh.available_quantity ?? wh.quantity" in product_list


def test_costing_frontend_uses_backend_returned_values():
    cost_layers = _read("frontend/src/pages/Costing/CostLayerList.jsx")
    valuation = _read("frontend/src/pages/Costing/ValuationReport.jsx")

    assert "row.total_value" in cost_layers
    assert "remaining_quantity *" not in cost_layers
    assert "unit_cost *" not in cost_layers

    assert "report.grand_total_quantity" in valuation
    assert "report.grand_total_value" in valuation
    assert "weighted_unit_cost" in valuation
    assert "weighted_avg_cost" not in valuation


def test_stock_transfer_payload_sends_raw_inputs_only():
    source = _read("frontend/src/pages/Stock/StockTransferForm.jsx")
    payload_block = re.search(
        r"const payload = \{(?P<body>.*?)\n\s*\};\n\n\s*await inventoryAPI\.transferStock",
        source,
        re.S,
    )

    assert payload_block is not None
    payload = payload_block.group("body")

    assert "quantity: String(item.quantity)" in payload
    forbidden_authoritative_fields = [
        "available_quantity",
        "available_stock",
        "reserved_quantity",
        "damaged_quantity",
        "unit_cost",
        "total_cost",
        "total_value",
        "valuation",
        "cogs",
    ]
    offenders = [field for field in forbidden_authoritative_fields if field in payload]

    assert offenders == []


def test_inventory_backend_exposes_authoritative_stock_fields():
    sources = {
        "backend/routers/inventory/reports.py": [
            "reserved_quantity",
            "damaged_quantity",
            "available_quantity",
            "stock_status",
            "quantity_direction",
        ],
        "backend/routers/inventory/warehouses.py": [
            "reserved_quantity",
            "damaged_quantity",
            "available_quantity",
            "stock_status",
        ],
        "backend/routers/inventory/products.py": [
            "available_quantity",
            "available_stock",
            "reserved_quantity",
            "damaged_quantity",
        ],
        "backend/repositories/product_repo.py": [
            "reserved_qty",
            "damaged_qty",
            "available_qty",
            "available_stock",
        ],
    }

    missing = []
    for relative_path, expected_tokens in sources.items():
        source = _read(relative_path)
        for token in expected_tokens:
            if token not in source:
                missing.append(f"{relative_path}: {token}")

    assert missing == []


def test_inventory_frontend_uses_backend_cycle_batch_serial_and_profit_flags():
    cycle_counts = _read("frontend/src/pages/Stock/CycleCounts.jsx")
    batch_list = _read("frontend/src/pages/Stock/BatchList.jsx")
    serial_list = _read("frontend/src/pages/Stock/SerialList.jsx")
    profitability = _read("frontend/src/pages/Stock/ProfitabilityReport.jsx")
    movements = _read("frontend/src/pages/Stock/StockMovements.jsx")
    quality = _read("frontend/src/pages/Stock/QualityInspections.jsx")

    assert "res.data.summary" in cycle_counts
    assert "cc.has_variance" in cycle_counts
    assert "item.variance_prefix" in cycle_counts
    assert ".filter(c => c.status" not in cycle_counts
    assert "total_variance !== 0" not in cycle_counts
    assert "startsWith('-')" not in cycle_counts

    assert "row.expiry_status" in batch_list
    assert "summary.near_expiry_count" in batch_list
    assert "new Date(b.expiry_date)" not in batch_list
    assert ".filter(b => b.status" not in batch_list

    assert "summary.available_count" in serial_list
    assert ".filter(s => s.status" not in serial_list

    assert "gross_profit_direction" in profitability
    assert "margin_direction" in profitability
    assert "gross_profit >= 0" not in profitability
    assert "margin_pct >= 0" not in profitability

    assert "move.quantity_direction" in movements
    assert "move.quantity > 0" not in movements

    assert "summary.pending_count" in quality
    assert "summary.passed_count" in quality
    assert "summary.failed_count" in quality
    assert ".filter(i => i.status" not in quality
    assert ".filter(i => i.result" not in quality


def test_inventory_backend_exposes_authoritative_cycle_batch_serial_and_profit_flags():
    batches = _read("backend/routers/inventory/batches.py")
    profitability = _read("backend/routers/reports/inventory.py")
    transfers = _read("backend/routers/inventory/transfers.py")
    shipments = _read("backend/routers/inventory/shipments.py")

    expected_batch_tokens = [
        "expiry_status",
        "near_expiry_count",
        "available_count",
        "total_variance",
        "has_variance",
        "variance_direction",
        "variance_prefix",
        "pending_count",
        "passed_count",
        "failed_count",
    ]
    missing_batches = [token for token in expected_batch_tokens if token not in batches]

    expected_profit_tokens = [
        "gross_profit_direction",
        "margin_direction",
        "_gross_profit_sort",
    ]
    missing_profit = [token for token in expected_profit_tokens if token not in profitability]

    expected_availability_tokens = [
        "damaged_quantity",
        "available_quantity",
    ]
    missing_transfer = [token for token in expected_availability_tokens if token not in transfers]
    missing_shipments = [token for token in expected_availability_tokens if token not in shipments]

    assert missing_batches == []
    assert missing_profit == []
    assert missing_transfer == []
    assert missing_shipments == []


def test_inventory_costing_backend_exposes_authoritative_values():
    service = _read("backend/services/costing_service.py")
    schemas = _read("backend/schemas/costing.py")

    expected_service_tokens = [
        "reserved_quantity, damaged_quantity, available_quantity",
        "remaining_quantity * cl.unit_cost AS total_value",
        "grand_total_value",
        "grand_total_quantity",
        "weighted_unit_cost",
    ]
    missing_service = [token for token in expected_service_tokens if token not in service]

    expected_schema_tokens = [
        "total_value",
        "weighted_unit_cost",
        "grand_total_value",
        "grand_total_quantity",
    ]
    missing_schema = [token for token in expected_schema_tokens if token not in schemas]

    assert missing_service == []
    assert missing_schema == []


def test_inventory_cleanup_markers_removed():
    files = [
        "backend/routers/inventory/reports.py",
        "backend/routers/inventory/warehouses.py",
        "backend/routers/inventory/products.py",
        "backend/repositories/product_repo.py",
        "backend/services/costing_service.py",
        "backend/schemas/costing.py",
        "frontend/src/pages/Stock/StockReports.jsx",
        "frontend/src/pages/Stock/StockTransferForm.jsx",
        "frontend/src/pages/Stock/StockShipmentForm.jsx",
        "frontend/src/pages/Stock/StockMovements.jsx",
        "frontend/src/pages/Stock/BatchList.jsx",
        "frontend/src/pages/Stock/SerialList.jsx",
        "frontend/src/pages/Stock/CycleCounts.jsx",
        "frontend/src/pages/Stock/ProfitabilityReport.jsx",
        "frontend/src/pages/Stock/QualityInspections.jsx",
        "frontend/src/pages/Stock/ProductList.jsx",
        "frontend/src/pages/Costing/CostLayerList.jsx",
        "frontend/src/pages/Costing/ValuationReport.jsx",
    ]
    forbidden = [
        "TODO" + "(backend-authority)",
        "Phase " + "B",
        "Phase " + "C",
        "tempor" + "ary",
        "مرحلة " + "B",
        "مرحلة " + "C",
    ]

    offenders = []
    for relative_path in files:
        source = _read(relative_path)
        for token in forbidden:
            if token in source:
                offenders.append(f"{relative_path}: {token}")

    assert offenders == []
