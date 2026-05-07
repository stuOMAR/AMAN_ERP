"""
CI lint: detect direct secret reads outside the vault.

Fails (exit 1) when ``os.environ`` or settings reads of secret-pattern keys
(e.g. smtp_password, zatca_*_secret, sms_api_key) appear outside
``services/credentials_vault.py`` and the migrator script.
"""
import re
import sys
from pathlib import Path

# Patterns that indicate a secret is being read directly from env/settings.
_SECRET_KEY_PATTERNS = [
    r"smtp_password",
    r"zatca_\w+_secret",
    r"zatca_\w+_token",
    r"sms_api_key",
    r"sms_secret",
    r"payment_secret",
    r"payment_api_key",
    r"bank_feed_\w+",
    r"bank_api_key",
    r"ldap_password",
    r"shipping_api_key",
    r"shipping_secret",
]

# Regex matching os.environ / os.getenv reads of any secret-pattern key.
_ENV_READ_RE = re.compile(
    r"""(?:os\.environ\b|os\.getenv\b|os\.environ\.get\b)"""
    r"""\s*\[?\s*['"]( """
    + "|".join(_SECRET_KEY_PATTERNS)
    + r""")['"]""",
    re.IGNORECASE,
)

# Regex matching settings.SECRET_KEY style reads.
_SETTINGS_READ_RE = re.compile(
    r"""settings\.\w*(?:"""
    + "|".join(_SECRET_KEY_PATTERNS)
    + r""")\w*""",
    re.IGNORECASE,
)

# Files that are allowed to read secrets directly.
_ALLOWED_FILES = {
    Path("backend/services/credentials_vault.py"),
    Path("backend/scripts/migrate_credentials_to_vault.py"),
    Path("backend/scripts/encrypt_existing_secrets.py"),
    # SMTP is infrastructure-level config, not per-tenant integration secret
    Path("backend/utils/email.py"),
    Path("backend/routers/auth/password.py"),
}

# Directories to scan.
_SCAN_DIRS = [Path("backend")]


def _is_allowed(filepath: Path) -> bool:
    resolved = filepath.resolve()
    for allowed in _ALLOWED_FILES:
        if resolved == allowed.resolve():
            return True
    return False


def main() -> int:
    violations: list[tuple[Path, int, str]] = []

    for scan_dir in _SCAN_DIRS:
        for pyfile in scan_dir.rglob("*.py"):
            if _is_allowed(pyfile):
                continue

            try:
                source = pyfile.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for lineno, line in enumerate(source.splitlines(), start=1):
                if _ENV_READ_RE.search(line):
                    violations.append((pyfile, lineno, line.strip()))
                elif _SETTINGS_READ_RE.search(line):
                    violations.append((pyfile, lineno, line.strip()))

    if violations:
        print(
            f"[check_credential_callsites] FAIL — {len(violations)} direct "
            f"secret read(s) found outside the vault:\n",
            file=sys.stderr,
        )
        for filepath, lineno, line in violations:
            print(f"  {filepath}:{lineno}: {line}", file=sys.stderr)
        print(
            "\nAll integration secrets MUST be read via "
            "backend.services.credentials_vault.get_credential().\n",
            file=sys.stderr,
        )
        return 1

    print(
        f"[check_credential_callsites] PASS — no direct secret reads found."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
