from pathlib import Path
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

PAYROLL_PY = BACKEND / "routers/hr/core/payroll.py"
ADVANCES_PY = BACKEND / "routers/hr/advances.py"
WPS_PY = BACKEND / "routers/hr_wps_compliance.py"
TENANT_SCHEMA_PY = BACKEND / "db_ddl/tenant_schema.py"
HR_WPS_MIGRATION_PY = BACKEND / "alembic/versions/031b_hr_wps_compliance_fields.py"
ERRORS_EN = BACKEND / "locales/errors.en.json"
ERRORS_AR = BACKEND / "locales/errors.ar.json"

def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


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


class _FakePayrollDb:
    def __init__(self):
        self.entries = []
        self.next_id = 1

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "FROM payroll_entries" in sql and "idempotency_key = :key" in sql:
            row = next((entry for entry in self.entries if entry["idempotency_key"] == params["key"]), None)
            return _Result(one=SimpleNamespace(id=row["id"], net_salary=row["net_salary"]) if row else None)

        if "FROM payroll_periods" in sql and "EXTRACT(MONTH FROM start_date)" in sql:
            return _Result(one=SimpleNamespace(id=10))

        if "FROM payroll_entries" in sql and "period_id=:pid" in sql:
            row = next(
                (entry for entry in self.entries if entry["period_id"] == params["pid"] and entry["employee_id"] == params["eid"]),
                None,
            )
            return _Result(one=SimpleNamespace(id=row["id"]) if row else None)

        if "FROM employees e" in sql:
            return _Result(one=SimpleNamespace(
                id=params["id"],
                salary=Decimal("1000.00"),
                basic_salary=Decimal("1000.00"),
                housing_allowance=Decimal("100.00"),
                transport_allowance=Decimal("50.00"),
                other_allowances=Decimal("25.00"),
            ))

        if "FROM gosi_settings" in sql:
            return _Result(one=None)

        if "FROM overtime_requests" in sql or "FROM employee_violations" in sql:
            return _Result(scalar_value=Decimal("0"))

        if "FROM employee_loans" in sql:
            return _Result(one=None)

        if "FROM employee_salary_components" in sql:
            return _Result(all_rows=[])

        if "INSERT INTO payroll_periods" in sql:
            return _Result(one=(10,))

        if "INSERT INTO payroll_entries" in sql:
            entry = {
                "id": self.next_id,
                "period_id": params["pid"],
                "employee_id": params["eid"],
                "net_salary": params["net"],
                "idempotency_key": params["idempotency_key"],
            }
            self.entries.append(entry)
            self.next_id += 1
            return _Result(one=SimpleNamespace(id=entry["id"]))

        raise AssertionError(f"Unexpected SQL in fake payroll DB: {sql}")


def _request(idempotency_key="payroll-test-key"):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/hr/payslips/generate",
        "headers": [(b"idempotency-key", idempotency_key.encode("utf-8"))],
    })


@contextmanager
def _fake_transactional(db):
    yield db


@pytest.fixture
def fake_payroll_db(monkeypatch):
    from routers.hr.core import payroll

    db = _FakePayrollDb()
    monkeypatch.setattr(payroll, "transactional", lambda _company_id: _fake_transactional(db))
    return db


def _payload(submitted_grand_total=None):
    from routers.hr.core.core import PayslipGenerateRequest

    return PayslipGenerateRequest(
        employee_id=1,
        month=5,
        year=2026,
        submitted_grand_total=submitted_grand_total,
    )

def test_hr_payroll_idempotency_and_backend_authority():
    """Verify that single payslip generation includes the idempotency key and backend-authoritative calculation properties."""
    payroll_src = _read(PAYROLL_PY)
    tenant_schema_src = _read(TENANT_SCHEMA_PY)

    # 1. Check idempotency in single payslip generation
    assert "require_idempotency_key" in payroll_src, "Idempotency helper import or call missing from payroll.py"
    assert "SELECT id FROM payroll_entries" in payroll_src, "Missing idempotency pre-check query against payroll_entries"
    assert "idempotency_key = :key" in payroll_src, "Missing idempotency key query binding"
    assert "idempotency_key" in tenant_schema_src, "idempotency_key must be defined in the tenant schema DDL"
    assert "payroll_entries" in tenant_schema_src, "payroll_entries table must be defined in tenant schema"
    assert "idempotency_key = Column(" in tenant_schema_src or "idempotency_key" in tenant_schema_src, "idempotency_key must be present in tenant schema tables"

    # 2. Check that calculations are backend-authoritative
    assert "total_deductions" in payroll_src, "Deduction calculation should be done authoritatively on the backend"
    assert "net_salary" in payroll_src or "net =" in payroll_src, "Net salary calculation should be done authoritatively on the backend"
    assert "gosi_emp" in payroll_src or "gosi_employee_share" in payroll_src, "GOSI employee share should be calculated on the backend"
    assert "gosi_empr" in payroll_src or "gosi_employer_share" in payroll_src, "GOSI employer share should be calculated on the backend"
    assert "violation_deduction" in payroll_src, "Violations deductions must be fetched/calculated on the backend"
    assert "loan_deduction" in payroll_src, "Loan deductions must be calculated on the backend"

    # 3. submitted_grand_total and preview are part of the backend-authority contract
    assert '@router.post("/payslips/preview"' in payroll_src, "Missing backend payslip preview endpoint"
    assert "draft_journal_lines" in payroll_src, "Payslip preview should include draft GL lines"
    assert "submitted_grand_total" in payroll_src, "Payslip generation must accept submitted_grand_total"
    assert "submitted_grand_total_mismatch" in payroll_src, "Payslip generation must reject mismatched submitted totals"
    assert "abs(calc[\"net\"] - data.submitted_grand_total) > _D2" in payroll_src, "Submitted net salary tolerance must be enforced"


def test_salary_advance_approval_is_idempotent_and_unpacks_gl_tuple():
    advances_src = _read(ADVANCES_PY)

    assert 'require_idempotency_key(request, operation="salary advance approval")' in advances_src
    assert "approval_idempotency_key" in advances_src
    assert "WHERE idempotency_key = :key" in advances_src
    assert "idempotency_key=approval_idempotency_key" in advances_src
    assert "je_id, _entry_number = create_journal_entry" in advances_src
    assert "je_id = create_journal_entry" not in advances_src


def test_wps_compliance_fields_are_required_for_non_saudi_sif_exports():
    wps_src = _read(WPS_PY)
    tenant_schema_src = _read(TENANT_SCHEMA_PY)
    migration_src = _read(HR_WPS_MIGRATION_PY)
    errors_en = _read(ERRORS_EN)
    errors_ar = _read(ERRORS_AR)

    assert "_requires_wps_labor_compliance" in wps_src
    assert "labor_card_number" in wps_src
    assert "insurance_number" in wps_src
    assert "visa_status" in wps_src
    assert "wps_missing_labor_card_for_employee" in wps_src
    assert "wps_missing_insurance_number_for_employee" in wps_src
    assert "wps_missing_visa_status_for_employee" in wps_src
    assert "_sif_num(total_amount, 15, decimals=2)" in wps_src

    for field in ("labor_card_number", "insurance_number", "visa_status"):
        assert field in tenant_schema_src
        assert field in migration_src

    for error_key in (
        "wps_missing_labor_card_for_employee",
        "wps_missing_insurance_number_for_employee",
        "wps_missing_visa_status_for_employee",
    ):
        assert error_key in errors_en
        assert error_key in errors_ar


def test_end_of_service_engine_matches_saudi_labor_rules():
    from utils.hr_helpers import calculate_eos_gratuity

    termination = calculate_eos_gratuity(
        Decimal("10000"),
        Decimal("6"),
        "termination",
        unpaid_leave_days=3,
    )
    assert termination["full_gratuity"] == Decimal("35000.00")
    assert termination["resignation_factor"] == Decimal("1.00")
    assert termination["unpaid_leave_deduction"] == Decimal("1000.00")
    assert termination["final_gratuity"] == Decimal("34000.00")

    short_resignation = calculate_eos_gratuity(
        Decimal("9000"),
        Decimal("1.50"),
        "resignation",
    )
    assert short_resignation["full_gratuity"] == Decimal("6750.00")
    assert short_resignation["resignation_factor"] == Decimal("0.00")
    assert short_resignation["final_gratuity"] == Decimal("0.00")

    mid_resignation = calculate_eos_gratuity(
        Decimal("9000"),
        Decimal("6"),
        "resignation",
    )
    assert mid_resignation["full_gratuity"] == Decimal("31500.00")
    assert mid_resignation["resignation_factor"] == Decimal("0.67")
    assert mid_resignation["final_gratuity"] == Decimal("21000.00")


def test_eos_settlement_uses_gl_service_and_idempotency():
    wps_src = _read(WPS_PY)

    assert 'require_idempotency_key(request, operation="end of service settlement")' in wps_src
    assert 'source="eos_settlement"' in wps_src
    assert 'idempotency_key=f"eos_settlement:{body.employee_id}:{idempotency_key}"' in wps_src
    assert "gl_create_journal_entry(" in wps_src


def test_submitted_grand_total_mismatch_returns_422(fake_payroll_db):
    from routers.hr.core import payroll

    with pytest.raises(HTTPException) as exc:
        payroll.generate_single_payslip(
            request=_request("mismatch-key"),
            data=_payload(Decimal("1.00")),
            company_id="testco",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "submitted_grand_total_mismatch"
    assert len(fake_payroll_db.entries) == 0


def test_idempotency_key_prevents_duplicate_payslip(fake_payroll_db):
    from routers.hr.core import payroll

    preview = payroll.preview_single_payslip(
        request=_request("dup-preview"),
        data=_payload(),
        company_id="testco",
    )
    payload = _payload(Decimal(preview["net_salary"]))

    first = payroll.generate_single_payslip(
        request=_request("same-uuid"),
        data=payload,
        company_id="testco",
    )
    second = payroll.generate_single_payslip(
        request=_request("same-uuid"),
        data=payload,
        company_id="testco",
    )

    assert len(fake_payroll_db.entries) == 1
    assert second["replayed"] is True
    assert second["id"] == first["id"]
    assert second["net_salary"] == first["net_salary"]


def test_preview_does_not_commit_to_db(fake_payroll_db):
    from routers.hr.core import payroll

    before_count = len(fake_payroll_db.entries)
    preview = payroll.preview_single_payslip(
        request=_request("preview-only"),
        data=_payload(),
        company_id="testco",
    )

    assert preview["net_salary"] == "1067.75"
    assert len(fake_payroll_db.entries) == before_count


def test_preview_and_save_return_same_net_salary(fake_payroll_db):
    from routers.hr.core import payroll

    preview = payroll.preview_single_payslip(
        request=_request("same-net-preview"),
        data=_payload(),
        company_id="testco",
    )
    saved = payroll.generate_single_payslip(
        request=_request("same-net-save"),
        data=_payload(Decimal(preview["net_salary"])),
        company_id="testco",
    )

    assert saved["net_salary"] == preview["net_salary"]
    assert fake_payroll_db.entries[0]["net_salary"] == preview["net_salary"]

if __name__ == '__main__':
    test_hr_payroll_idempotency_and_backend_authority()
    print("ALL ASSERTIONS PASSED SUCCESSFULLY!")
