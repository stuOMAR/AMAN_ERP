"""022h: Create device_fingerprints and login_geo_events tables.

Revision: 022h_device_fingerprints_login_geo
Revises: 022b_integration_credentials
Create Date: 2026-05-02

Privacy-safe device fingerprint registry and coarse geo event log
for login risk scoring and impossible-travel detection.
"""
from alembic import op


revision = "022h_device_fingerprints_login_geo"
down_revision = "022e_employee_receipt_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- ── device_fingerprints ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS device_fingerprints (
            id                BIGSERIAL     PRIMARY KEY,
            tenant_id         BIGINT        NOT NULL,
            user_id           BIGINT        NOT NULL,
            fingerprint_hash  VARCHAR(64)   NOT NULL,
            first_seen_at     TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            last_seen_at      TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            trust_level       VARCHAR(16)   NOT NULL DEFAULT 'unknown'
        );

        CREATE INDEX IF NOT EXISTS ix_device_fp_tenant_user_hash
            ON device_fingerprints (tenant_id, user_id, fingerprint_hash);

        -- ── login_geo_events ─────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS login_geo_events (
            id                BIGSERIAL     PRIMARY KEY,
            tenant_id         BIGINT        NOT NULL,
            user_id           BIGINT        NOT NULL,
            occurred_at       TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            country_code      CHAR(2)       NULL,
            region_code       VARCHAR(8)    NULL,
            risk_decision     VARCHAR(16)   NOT NULL DEFAULT 'ok',
            decision_reason   VARCHAR(64)   NULL
        );

        CREATE INDEX IF NOT EXISTS ix_login_geo_tenant_user_time
            ON login_geo_events (tenant_id, user_id, occurred_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_login_geo_tenant_user_time;
        DROP TABLE IF EXISTS login_geo_events;
        DROP INDEX IF EXISTS ix_device_fp_tenant_user_hash;
        DROP TABLE IF EXISTS device_fingerprints;
        """
    )
