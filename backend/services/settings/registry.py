"""Canonical settings registry for AMAN ERP.

Every feature that introduces new company_settings keys MUST register them
here so that:
  1. CI `check_schema_sync.py` can diff against the DDL seed.
  2. Settings UI can display labels/defaults without hard-coding.
  3. Documentation stays in one place.

Convention: dotted key names, JSON-serialised values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingDef:
    key: str
    default: Any
    description: str
    value_type: str = "string"  # string | int | bool | json
    min_value: int | float | None = None
    max_value: int | float | None = None


# ── Feature 025: Reports / Cache / KPI / Scheduler / Backup / Search ──────

FEATURE_025_SETTINGS: tuple[SettingDef, ...] = (
    # Cache
    SettingDef("cache.backend", "redis", "Cache backend: redis | memory", "string"),
    SettingDef("cache.circuit_breaker.failures", 5, "Open breaker after N consecutive failures", "int", min_value=1),
    SettingDef("cache.circuit_breaker.cool_down_seconds", 30, "Cool-down before re-probe (seconds)", "int", min_value=5),
    # Reports MVs
    SettingDef("reports.mv.refresh_interval_minutes", 15, "MV refresh cadence (minutes)", "int", min_value=1),
    # Reports cache
    SettingDef("reports.warmup_keys", '["coa:summary","kpi:operating_margin","dashboard:home"]',
               "Keys warmed on boot", "json"),
    # KPI
    SettingDef("reports.kpi.evaluation_interval_minutes", 15, "KPI evaluator cadence (minutes)", "int", min_value=5),
    # Income statement
    SettingDef("reports.income_statement.include_headers", "true",
               "Include header rows in income statement", "bool"),
    # Trial balance
    SettingDef("reports.trial_balance.tolerance", "0.01",
               "Trial balance balance tolerance", "string"),
    # Audit retention
    SettingDef("audit.retention_months", 36, "Partition retention (months)", "int", min_value=1),
    # Search
    SettingDef("search.autocomplete_debounce_ms", 300, "UI debounce (ms)", "int", min_value=100),
    SettingDef("search.query_logs_retention_days", 90, "Search-log retention (days)", "int", min_value=7),
    # FX
    SettingDef("fx.cache_ttl_minutes", 30, "FX cache TTL (minutes)", "int", min_value=1),
    SettingDef("fx.stale_tolerance_minutes", 120, "Acceptable stale window for useExchangeRate (minutes)", "int", min_value=1),
    # Backup
    SettingDef("backup.local_time", "02:00", "Daily backup time (HH:MM server tz)", "string"),
    SettingDef("backup.retention_days", 30, "Backup retention (days)", "int", min_value=1),
    SettingDef("backup.min_retained", 3, "Minimum backups never deleted", "int", min_value=1),
    SettingDef("backup.max_consecutive_failures", 3, "Dead-letter threshold", "int", min_value=1),
    SettingDef("backup.offsite_provider", "s3", "Provider key (vault holds creds)", "string"),
)

# ── Aggregate ────────────────────────────────────────────────────────────

ALL_SETTINGS: tuple[SettingDef, ...] = FEATURE_025_SETTINGS

SETTINGS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in ALL_SETTINGS}


def get_default(key: str) -> Any | None:
    """Return the registered default for *key*, or None if unregistered."""
    sd = SETTINGS_BY_KEY.get(key)
    return sd.default if sd else None


def seed_sql() -> str:
    """Return an INSERT … ON CONFLICT SQL block for all registered keys."""
    rows = []
    for s in ALL_SETTINGS:
        val = s.default
        if isinstance(val, bool):
            val = "true" if val else "false"
        elif isinstance(val, (list, dict)):
            import json as _json
            val = _json.dumps(val)
        else:
            val = str(val)
        rows.append(f"    ('{s.key}', '{val}')")
    values = ",\n".join(rows)
    return f"""INSERT INTO company_settings (setting_key, setting_value)
VALUES
{values}
ON CONFLICT (setting_key) DO NOTHING;
"""
