"""DMS streaming MIME validator — libmagic-based MIME detection.

Contract: see specs/024-workforce-service-comms-integrity/contracts/dms-streaming-mime-validator.md
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Allowed MIME groups (from company_settings dms.allowed_mime_groups)
DEFAULT_ALLOWED_MIMES = [
    "image/*",
    "application/pdf",
    "application/zip",
    "application/vnd.openxmlformats-officedocument*",
    "text/plain",
    "text/csv",
]


def detect_mime(file_path: str) -> Optional[str]:
    """Detect MIME type of a file using libmagic."""
    try:
        import magic
        mime = magic.Magic(mime=True)
        return mime.from_file(file_path)
    except ImportError:
        logger.warning("python-magic not available; falling back to extension-based detection")
        return _detect_by_extension(file_path)
    except Exception as e:
        logger.error("MIME detection failed: %s", e)
        return None


def _detect_by_extension(file_path: str) -> Optional[str]:
    """Fallback MIME detection by file extension."""
    import mimetypes
    mime, _ = mimetypes.guess_type(file_path)
    return mime


def validate_mime(
    file_path: str,
    allowed_groups: list[str] = None,
) -> dict:
    """Validate that a file's MIME type is in the allowed list.

    Returns dict with validation result.
    """
    if allowed_groups is None:
        allowed_groups = DEFAULT_ALLOWED_MIMES

    detected = detect_mime(file_path)
    if detected is None:
        return {
            "valid": False,
            "reason": "dms.mime_undetected",
            "detected_mime": None,
        }

    # Check against allowed groups
    for pattern in allowed_groups:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if detected.startswith(prefix):
                return {"valid": True, "detected_mime": detected}
        elif detected == pattern:
            return {"valid": True, "detected_mime": detected}

    return {
        "valid": False,
        "reason": "dms.mime_rejected",
        "detected_mime": detected,
        "allowed_groups": allowed_groups,
    }
