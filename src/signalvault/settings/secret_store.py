"""C1-B: SecretStore — secure local storage for sensitive configuration.

Stores API keys and other secrets in a separate file with restricted permissions.
Never included in diagnostic bundles, logs, or public config snapshots.

rc1:   Local file at ``<config_dir>/secrets`` with 0600 permissions (Unix).
       On Windows, relies on the user-profile default ACL (no custom DACL).
rc2:   Can migrate to OS keychain via the ``keyring`` library.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_SECRETS_FILENAME = "secrets"


class SecretStore:
    """Minimal secure key-value store backed by a local file.

    Creates ``<config_dir>/secrets`` on first write.  Never writes API keys
    into config.toml, logs, diagnostics, or error messages.
    """

    def __init__(self, config_dir: str | Path) -> None:
        self._path = Path(config_dir) / _SECRETS_FILENAME

    # ── Public API ───────────────────────────────────────────────────────

    def is_set(self, key: str) -> bool:
        """True if *key* has a non-empty value in the store."""
        try:
            data = self._read()
        except OSError:
            return False
        return bool(data.get(key, ""))

    def get_for_internal_use(self, key: str) -> str | None:
        """Return the stored value for *key*, or None.

        Callers MUST NOT log, display, or export the returned value.
        """
        try:
            data = self._read()
        except OSError:
            return None
        v = data.get(key, "")
        return v if v else None

    def set(self, key: str, value: str) -> None:
        """Persist *value* for *key*.  Empty values are rejected."""
        if not value or not value.strip():
            raise ValueError(
                f"SecretStore.set({key!r}): refusing to store empty value. "
                f"Use delete() to remove a key."
            )
        data = self._read()
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> None:
        """Remove *key* from the store.  No-op if absent."""
        data = self._read()
        if key in data:
            del data[key]
            self._write(data)

    def list_keys(self) -> list[str]:
        """Return stored key names only — never the values."""
        try:
            data = self._read()
        except OSError:
            return []
        return sorted(data.keys())

    # ── Internal ─────────────────────────────────────────────────────────

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("SecretStore: %s is not a JSON object — treating as empty", self._path)
                return {}
            return {k: str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            logger.warning("SecretStore: %s is corrupt — treating as empty", self._path)
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._path)
        self._restrict_permissions()

    def _restrict_permissions(self) -> None:
        """Set 0600 on Unix.  Windows: no-op (relies on user-profile ACL)."""
        if os.name == "nt":
            return
        try:
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.debug("SecretStore: could not chmod %s", self._path)
