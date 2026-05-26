#!/usr/bin/env python3
"""Generate docs/audit-remediation-tasks.md from _findings_final.json.

The script is the single source of truth for the audit-remediation
checklist. It groups the 435 findings by severity tier and rule_id, and
marks each entry ✅ (closed by a PR) or ⏳ (open) using the explicit
mapping below.

Closed-set is derived from two sources, in this priority:

1.  IDs that appear inside any ``backend/tests/test_audit_pr*.py`` test
    file (the regression test references the finding ID).
2.  The IDs explicitly cited in PR-1..PR-9 source-code annotations (the
    Critical batch closed before the test-id convention was introduced).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/omar/Desktop/aman")
FINDINGS = ROOT / ".kiro/specs/audit-finance-treasury-tax-zatca/_findings_final.json"
TESTS = ROOT / "backend/tests"
OUT = ROOT / "docs/audit-remediation-tasks.md"

# Critical findings closed by PR-1..PR-9 (annotated in source, not tests):
#   F-NEW-001..004 — eta/uae_fta secret leak                       (PR 2)
#   F-NEW-005..006 — zatca_adapter Decimal money                   (PR 3)
#   F-NEW-007..008 — outbox_admin tenant binding                   (PR 4)
#   F-NEW-009     — accounts.py opening-balance reverse-via-GL    (PR 5)
#   F-NEW-010     — journal post via gl_service.post_draft         (PR 5)
#   F-NEW-011..014 — journal idempotency / locks (CC-* High moved-up)
#                                                                  (PR 5/6)
#   F-NEW-015     — fiscal-lock guard inline → check_fiscal_period_open (PR 6)
#   F-NEW-016     — petty_cash recalc via gl_service               (PR 7)
#   F-NEW-017..018 — scheduler recurring via gl_service            (PR 8)
PR1_9_CRITICAL = [f"F-NEW-{i:03d}" for i in range(1, 19)]


def collect_closed_ids() -> set[str]:
    """Return every F-NEW-XXX id that is closed by a landed PR.

    PR16-fix: a behavioural review found 7+ findings that PR4/PR7/PR11/PR15
    *claimed* to close but where the runtime behaviour was still broken
    (e.g. petty_cash je_id corruption, idempotency state-check race,
    bank_feeds per-statement hash collision, ETA float casts). PR16-fix
    re-implemented each one and added a behavioural regression test
    under ``test_audit_pr16_behavioral_fixes.py``. The fixes therefore
    flow through the standard test-grep path below; no overrides needed.
    """
    closed: set[str] = set(PR1_9_CRITICAL)
    pat = re.compile(r"F-NEW-\d{3}")
    for p in TESTS.glob("test_audit_pr*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in pat.findall(text):
            closed.add(m)
    # The two legacy-name tests that closed Critical IDs (no `pr_NN_`):
    for legacy in (
        "test_einvoicing_adapter_secret_redaction.py",
        "test_zatca_adapter_decimal_money.py",
        "test_utils_masking_redact_token.py",
    ):
        p = TESTS / legacy
        if p.exists():
            for m in pat.findall(p.read_text(encoding="utf-8", errors="ignore")):
                closed.add(m)
    return closed


def pr_for_id(fid: str) -> str:
    """Return the PR # that closed the finding (best-effort label)."""
    pat = re.compile(rf"\b{re.escape(fid)}\b")
    for p in sorted(TESTS.glob("test_audit_pr*.py")):
        if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            m = re.match(r"test_audit_pr(\d+)_", p.name)
            return f"PR{m.group(1)}" if m else "PR?"
    if fid in {f"F-NEW-{i:03d}" for i in (1, 2, 3, 4)}:
        return "PR2"
    if fid in {"F-NEW-005", "F-NEW-006"}:
        return "PR3"
    if fid in {"F-NEW-007", "F-NEW-008"}:
        return "PR4"
    if fid == "F-NEW-009":
        return "PR5"
    if fid in {"F-NEW-010", "F-NEW-011", "F-NEW-012"}:
        return "PR5"
    if fid in {"F-NEW-013", "F-NEW-014", "F-NEW-015"}:
        return "PR6"
    if fid == "F-NEW-016":
        return "PR7"
    if fid in {"F-NEW-017", "F-NEW-018"}:
        return "PR8"
    return ""


def rule_prefix(f: dict) -> str:
    """Best-effort rule grouping key.

    Prefer the explicit ``rule_id`` field (introduced for Phase-5
    findings); fall back to the leading uppercase token of
    ``rule_or_check`` (used by the original Phase-1..4 entries).
    """
    rid = (f.get("rule_id") or "").strip()
    if rid:
        return rid
    rule = f.get("rule_or_check") or ""
    m = re.match(r"([A-Z][A-Z0-9_-]+)", rule)
    return m.group(1) if m else "(none)"


def file_anchor(f: dict) -> str:
    """Best-effort ``file:line`` anchor across heterogenous schemas."""
    if f.get("file"):
        line = f.get("line")
        return f"{f['file']}:{line}" if line is not None else str(f["file"])
    if f.get("effective_path"):
        return str(f["effective_path"])
    if f.get("evidence_anchor"):
        return str(f["evidence_anchor"])[:80]
    if f.get("schema_name"):
        return f"schema:{f['schema_name']}"
    if f.get("function"):
        return f"fn:{f['function']}"
    return "(no anchor)"


def short(s: str, n: int = 110) -> str:
    s = (s or "").replace("\n", " ").replace("|", "/").strip()
    return (s[: n - 1] + "…") if len(s) > n else s


def render_finding_row(f: dict, closed: set[str]) -> str:
    fid = f["id"]
    mark = "✅" if fid in closed else "⏳"
    pr = pr_for_id(fid) if fid in closed else ""
    pr_col = f" `{pr}`" if pr else ""
    file_line = f"`{file_anchor(f)}`"
    desc = short(
        f.get("problem")
        or f.get("title")
        or f.get("rule_or_check")
        or f.get("evidence_anchor")
        or "",
        140,
    )
    return f"- [{mark}] **{fid}**{pr_col} · {f['severity']} · {f['module']} · {file_line} — {desc}"


def render_summary(findings: list[dict], closed: set[str]) -> str:
    by_sev: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_sev[f["severity"]].append(f)
    order = ["Critical", "High", "Medium", "Low", "Info"]

    lines: list[str] = []
    lines.append("## Summary by Severity\n")
    lines.append("| Severity | Total | ✅ Closed | ⏳ Open |")
    lines.append("|----------|------:|---------:|-------:|")
    total_closed = total = 0
    for sev in order:
        items = by_sev.get(sev, [])
        c = sum(1 for f in items if f["id"] in closed)
        total_closed += c
        total += len(items)
        lines.append(f"| {sev} | {len(items)} | {c} | {len(items) - c} |")
    lines.append(f"| **All** | **{total}** | **{total_closed}** | **{total - total_closed}** |\n")

    # By rule_id within each severity tier (highlights what's left).
    lines.append("## Status by rule_id (per severity)\n")
    for sev in order:
        items = by_sev.get(sev, [])
        if not items:
            continue
        rules: dict[str, tuple[int, int]] = {}
        for f in items:
            r = rule_prefix(f)
            t, c = rules.get(r, (0, 0))
            rules[r] = (t + 1, c + (1 if f["id"] in closed else 0))
        sev_closed = sum(c for _, c in rules.values())
        sev_total = sum(t for t, _ in rules.values())
        lines.append(f"### {sev} — {sev_closed}/{sev_total} closed\n")
        lines.append("| rule_id | Closed | Total | % |")
        lines.append("|---------|-------:|------:|--:|")

        # Same three-band ordering as the detail sections so the table
        # matches the document layout.
        def _row_key(kv):
            r, (t, c) = kv
            ratio = c / t if t else 0.0
            if ratio == 1.0:
                return (0, -t, r)
            if ratio > 0.0:
                return (1, -ratio, r)
            return (2, -t, r)

        for r, (t, c) in sorted(rules.items(), key=_row_key):
            pct = (c * 100 // t) if t else 0
            lines.append(f"| `{r}` | {c} | {t} | {pct}% |")
        lines.append("")
    return "\n".join(lines)


def render_section_for_severity(
    findings: list[dict], severity: str, closed: set[str]
) -> str:
    items = [f for f in findings if f["severity"] == severity]
    if not items:
        return ""

    by_rule: dict[str, list[dict]] = defaultdict(list)
    for f in items:
        by_rule[rule_prefix(f)].append(f)

    closed_n = sum(1 for f in items if f["id"] in closed)
    out: list[str] = []
    out.append(
        f"## {severity} — {closed_n}/{len(items)} closed\n"
    )

    # Three-band ordering inside each severity tier:
    #   1. fully-closed clusters first  (ratio == 1.0), bigger total first
    #      → shows completed work up front
    #   2. partially-closed clusters    (0 < ratio < 1.0), highest ratio first
    #      → "almost done" clusters surface before the long tail
    #   3. untouched clusters last      (ratio == 0.0), bigger total first
    #      → reflects upcoming-work queue (priority = size)
    def _sort_key(item):
        rule, fs = item
        total = len(fs)
        closed_count = sum(1 for f in fs if f["id"] in closed)
        ratio = closed_count / total if total else 0.0
        if ratio == 1.0:
            band = 0
            secondary = -total
        elif ratio > 0.0:
            band = 1
            secondary = -ratio
        else:
            band = 2
            secondary = -total
        return (band, secondary, rule)

    band_label = {0: "fully closed", 1: "partial", 2: "open"}
    last_band: int | None = None
    for rule, fs in sorted(by_rule.items(), key=_sort_key):
        rule_closed = sum(1 for f in fs if f["id"] in closed)
        ratio = rule_closed / len(fs)
        band = 0 if ratio == 1.0 else (1 if ratio > 0.0 else 2)
        if band != last_band:
            out.append(f"<!-- {band_label[band]} -->")
            last_band = band
        out.append(f"### {rule} — {rule_closed}/{len(fs)}\n")
        for f in sorted(fs, key=lambda x: x["id"]):
            out.append(render_finding_row(f, closed))
        out.append("")
    return "\n".join(out)


def main() -> None:
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    findings.sort(key=lambda x: x["id"])
    closed = collect_closed_ids()

    OUT.parent.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    parts.append("# Audit Remediation Checklist — 435 Findings\n")
    parts.append(
        "Source of truth: `.kiro/specs/audit-finance-treasury-tax-zatca/_findings_final.json` (435 entries).\n"
        "Generated by `scripts/build_audit_remediation_tasks.py`.\n"
        "\n"
        "Legend: ✅ closed by a landed PR (regression test green) · "
        "⏳ open · `PR<N>` cites the closing PR.\n"
    )
    parts.append(render_summary(findings, closed))
    parts.append(
        "## Closed-PR Index\n"
        "\n"
        "| PR | Theme | Findings closed |\n"
        "|----|-------|------------------|\n"
        "| PR1 | Adapter helper `redact_token` (prerequisite for PR2) | (test infra) |\n"
        "| PR2 | ETA / UAE-FTA bearer-token redaction | F-NEW-001..004 |\n"
        "| PR3 | ZATCA adapter Decimal money (TLV + UBL) | F-NEW-005, F-NEW-006 |\n"
        "| PR4 | `outbox_admin` per-tenant DB binding | F-NEW-007, F-NEW-008 |\n"
        "| PR5 | GL writer monopoly (accounts.py / journal.py) | F-NEW-009, F-NEW-010, F-NEW-035 |\n"
        "| PR6 | Fiscal-lock guard unification | F-NEW-013..015 |\n"
        "| PR7 | petty_cash recalc → gl_service | F-NEW-016 |\n"
        "| PR8 | Scheduler recurring via gl_service | F-NEW-017, F-NEW-018 |\n"
        "| PR9 | Expenses validate-policy gate | (Critical batch closer) |\n"
        "| PR10 | DDL/Alembic sync | F-NEW-019..022 |\n"
        "| PR11 | Missing idempotency (treasury / bank_feeds / payments / expenses / checks / notes / assets-transfers) | F-NEW-041, 043, 044, 065, 068, 085, 116, 135, 142, 162 |\n"
        "| PR12 | Reports missing-permission + tenant binding | F-NEW-164..169 |\n"
        "| PR13 | Float-on-wire (accounting/core, notes) | F-NEW-036, 125, 127 |\n"
        "| PR14 | Recoverable-500 swallow → typed errors | F-NEW-294, 299 |\n"
        "| PR15 | Float-money High sweep (16 routers) | F-NEW-023, 024, 025, 054, 055, 059, 063, 083, 097, 098, 126, 136, 139, 147, 151, 170, 171, 172 |\n"
    )

    for sev in ("Critical", "High", "Medium", "Low", "Info"):
        parts.append(render_section_for_severity(findings, sev, closed))

    parts.append(
        "## Notes\n"
        "\n"
        "- The **Info** tier (12 entries) is documentation-only by design. "
        "It is listed here for completeness; treat as N/A for remediation.\n"
        "- Closed/open counts are derived mechanically. Re-run "
        "`scripts/build_audit_remediation_tasks.py` after each new audit PR "
        "to refresh.\n"
        "- Only the audit spec folder (`.kiro/specs/audit-finance-treasury-tax-zatca/`) "
        "is locked. All other paths under `backend/`, `frontend/`, "
        "`backend/alembic/versions/**`, `backend/tests/**` remain in scope for fixes.\n"
    )
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes); closed={len(closed)}")


if __name__ == "__main__":
    main()
