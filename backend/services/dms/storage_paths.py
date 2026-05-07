"""DMS storage path centralization.

Contract: see specs/024-workforce-service-comms-integrity/contracts/dms-attachment-links.md
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_storage_root(conn: Any, *, tenant_id: int) -> str:
    """Get the storage root path for a tenant."""
    row = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'dms.storage_root'
        """),
    ).fetchone()
    return row[0] if row else "/var/aman/dms"


def compute_storage_path(
    tenant_id: int,
    document_id: int,
    filename: str,
    storage_root: str,
) -> str:
    """Compute the storage path for a document.

    Uses content-addressed storage: /root/<tenant>/<shard>/<hash>/<filename>
    """
    # Create sharding from document_id
    shard = document_id % 1000
    return os.path.join(storage_root, str(tenant_id), f"{shard:03d}", str(document_id))


def ensure_directory(path: str) -> None:
    """Ensure the storage directory exists."""
    os.makedirs(path, exist_ok=True)


def compute_checksum(file_path: str) -> str:
    """Compute SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
