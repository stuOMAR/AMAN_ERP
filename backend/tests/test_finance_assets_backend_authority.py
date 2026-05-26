from pathlib import Path
import re
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException, Request

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

def test_check_backend_authority_assets_configuration():
    """Verify check_backend_authority.py contains assets config and all files exist."""
    check_script_path = REPO_ROOT / "scripts/check_backend_authority.py"
    assert check_script_path.exists(), "check_backend_authority.py script does not exist"

    # Read check_backend_authority.py content to extract MODULES dict or load it dynamically
    namespace = {}
    with open(check_script_path, "r", encoding="utf-8") as f:
        # We can extract the MODULES dict by running the config portion of the script
        content = f.read()
        
        # Locate the MODULES block
        modules_match = re.search(r"MODULES\s*=\s*\{.*?\}\n\n", content, re.DOTALL)
        assert modules_match, "MODULES dictionary not found in check_backend_authority.py"
        
        # Safe eval or exec to load the dictionary
        exec(modules_match.group(0), namespace)

    modules = namespace.get("MODULES", {})
    assert "assets" in modules, "assets module configuration is missing in check_backend_authority.py"
    
    assets_cfg = modules["assets"]
    assert "schemas" in assets_cfg
    assert "routers" in assets_cfg
    assert "create_endpoints" in assets_cfg
    assert "preview_endpoints" in assets_cfg
    
    # Assert all configured files actually exist on disk
    for schema_file in assets_cfg["schemas"]:
        assert (REPO_ROOT / schema_file).exists(), f"Schema file {schema_file} does not exist"
        
    for router_file in assets_cfg["routers"]:
        assert (REPO_ROOT / router_file).exists(), f"Router file {router_file} does not exist"


class _Result:
    def __init__(self, *, one=None, all_rows=None, scalar_value=None):
        self._one = one
        self._all = all_rows or []
        self._scalar = scalar_value

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def scalar(self):
        return self._scalar


class _FakeAssetsDb:
    def __init__(self, asset_exists=True, status="active"):
        self.asset_exists = asset_exists
        self.status = status

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT * FROM assets" in sql:
            if self.asset_exists:
                return _Result(one=SimpleNamespace(
                    id=params.get("id", 1),
                    name="Test Asset",
                    code="AST-001",
                    status=self.status,
                    cost=Decimal("10000.00"),
                    residual_value=Decimal("1000.00"),
                    life_years=5,
                    branch_id=1,
                    currency="SAR"
                ))
            return _Result(one=None)
        return _Result(one=None)

    def begin(self):
        class FakeTrans:
            def commit(self): pass
            def rollback(self): pass
        return FakeTrans()

    def close(self): pass


def _request():
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/finance/assets/1/dispose",
        "headers": [(b"idempotency-key", b"asset-disposal-test-key")],
    })


def test_assets_preview_endpoints_and_idempotency_guards_are_wired():
    core_src = (BACKEND / "routers/finance/assets/core.py").read_text(encoding="utf-8")
    depreciation_src = (BACKEND / "routers/finance/assets/depreciation.py").read_text(encoding="utf-8")
    schemas_src = (BACKEND / "schemas/assets.py").read_text(encoding="utf-8")

    assert '@router.post("/{asset_id}/disposal/preview"' in core_src
    assert '"draft_journal_lines"' in core_src
    assert '@router.post("/depreciate/preview"' in depreciation_src
    assert '@router.post("/depreciate"' in depreciation_src
    assert '"draft_journal_lines"' in depreciation_src
    assert 'require_idempotency_key(request, operation="asset disposal")' in core_src
    assert 'require_idempotency_key(request, operation="asset depreciation run")' in depreciation_src
    assert "submitted_disposal_proceeds" in schemas_src


def test_assets_mutation_subrouters_require_idempotency_key():
    router_dir = BACKEND / "routers/finance/assets"
    for name in [
        "leases.py",
        "transfers.py",
        "impairment.py",
        "revaluations.py",
        "insurance.py",
        "maintenance.py",
    ]:
        src = (router_dir / name).read_text(encoding="utf-8")
        assert "require_idempotency_key" in src, f"{name} lacks idempotency enforcement"


def test_assets_backend_authority_no_float_casts_in_assets_money_paths():
    router_dir = BACKEND / "routers/finance/assets"
    for path in sorted(router_dir.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "float(" not in src, f"{path.name} contains float() in assets authority path"


def test_submitted_grand_total_mismatch_assets(monkeypatch):
    """Test that dispose_asset rejects mismatched submitted_grand_total."""
    from routers.finance.assets import core
    from schemas.assets import AssetDisposal

    db = _FakeAssetsDb(asset_exists=True)
    monkeypatch.setattr(core, "get_db_connection", lambda _company_id: db)

    # Test Mismatch on submitted_grand_total
    disposal_data = AssetDisposal(
        disposal_date="2026-05-24",
        disposal_price=Decimal("5000.00"),
        submitted_grand_total=Decimal("4900.00")  # Mismatch by 100.00
    )

    user = SimpleNamespace(company_id=1, id=1, branch_id=1)

    with pytest.raises(HTTPException) as exc:
        core.dispose_asset(
            request=_request(),
            asset_id=1,
            disposal=disposal_data,
            current_user=user
        )
    
    assert exc.value.status_code == 400
    assert "submitted grand total" in exc.value.detail.lower()


def test_submitted_disposal_proceeds_mismatch_assets(monkeypatch):
    """Test that dispose_asset rejects mismatched submitted_disposal_proceeds."""
    from routers.finance.assets import core
    from schemas.assets import AssetDisposal

    db = _FakeAssetsDb(asset_exists=True)
    monkeypatch.setattr(core, "get_db_connection", lambda _company_id: db)

    # Test Mismatch on submitted_disposal_proceeds
    disposal_data = AssetDisposal(
        disposal_date="2026-05-24",
        disposal_price=Decimal("5000.00"),
        submitted_disposal_proceeds=Decimal("5000.05")  # Mismatch by 0.05
    )

    user = SimpleNamespace(company_id=1, id=1, branch_id=1)

    with pytest.raises(HTTPException) as exc:
        core.dispose_asset(
            request=_request(),
            asset_id=1,
            disposal=disposal_data,
            current_user=user
        )
    
    assert exc.value.status_code == 400
    assert "submitted grand total" in exc.value.detail.lower()


def test_matching_submitted_totals_assets(monkeypatch):
    """Test that dispose_asset proceeds when submitted totals match within tolerance."""
    from routers.finance.assets import core
    from schemas.assets import AssetDisposal

    db = _FakeAssetsDb(asset_exists=True)
    monkeypatch.setattr(core, "get_db_connection", lambda _company_id: db)

    # Mock other DB calls within core.dispose_asset so it runs past authority check
    def mock_execute(stmt, params=None):
        sql = str(stmt)
        if "SELECT * FROM assets" in sql:
            return _Result(one=SimpleNamespace(
                id=params.get("id", 1),
                name="Test Asset",
                code="AST-001",
                status="active",
                cost=Decimal("10000.00"),
                residual_value=Decimal("1000.00"),
                life_years=5,
                branch_id=1,
                currency="SAR"
            ))
        elif "SELECT COALESCE" in sql:
            return _Result(scalar_value=Decimal("2000.00"))
        elif "SELECT date, accumulated_amount" in sql:
            return _Result(one=SimpleNamespace(date="2025-12-31", accumulated_amount=Decimal("2000.00")))
        elif "SELECT 1 FROM journal_entries" in sql:
            return _Result(one=None)
        return _Result(one=None)

    monkeypatch.setattr(db, "execute", mock_execute)

    # Mock external helpers
    monkeypatch.setattr(core, "get_mapped_account_id", lambda *args: 101)
    monkeypatch.setattr(core, "check_fiscal_period_open", lambda *args: True)
    
    # Mock GL Service
    from services import gl_service
    monkeypatch.setattr(gl_service, "create_journal_entry", lambda **kwargs: (42, "JE-001"))

    # Test exact match
    disposal_data = AssetDisposal(
        disposal_date="2026-05-24",
        disposal_price=Decimal("5000.00"),
        submitted_grand_total=Decimal("5000.00")
    )

    user = SimpleNamespace(company_id=1, id=1, branch_id=1)

    result = core.dispose_asset(
        request=_request(),
        asset_id=1,
        disposal=disposal_data,
        current_user=user
    )

    assert result["status"] == "disposed"
    assert result["journal_entry"] == "JE-001"
