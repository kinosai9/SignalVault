"""Vault scanner result cache with mtime-based invalidation.

Avoids re-scanning the entire vault filesystem on every dashboard request.
Uses directory + file mtime to detect changes; falls back to a short TTL
and a maximum cache age to prevent stale data.

Usage:
    from signalvault.workspace.scanner_cache import scan_with_cache
    snapshot = scan_with_cache(vault_path)
"""

from __future__ import annotations

import time
from pathlib import Path

from signalvault.workspace.scanner import VaultScanner, WorkspaceSnapshot

# Directories that contribute to scan freshness
_SCAN_DIRS = [
    "01_Reports",
    "02_Topics",
    "03_Companies",
    "05_Channels",
    "06_Claims",
    "07_Signals",
    "00_Inbox/LLM_Patches",
]

# Short TTL: within this window, skip even the mtime check
_DEFAULT_TTL_SECONDS = 30

# Maximum cache age: force a rescan after this, even if mtime is unchanged
_MAX_CACHE_AGE_SECONDS = 300

# In-process cache: {cache_key: (cached_at, snapshot)}
_CACHE: dict[str, tuple[float, WorkspaceSnapshot]] = {}


def _get_vault_mtime_max(vault_path: Path) -> float:
    """Return the max mtime across all watched vault directories and files.

    Used to detect any change (new file, deleted file, modified content).
    """
    max_mtime = 0.0
    for rel_dir in _SCAN_DIRS:
        d = vault_path / rel_dir
        if not d.exists():
            continue
        try:
            dir_stat = d.stat()
            max_mtime = max(max_mtime, dir_stat.st_mtime)
            for f in d.glob("*.md"):
                try:
                    max_mtime = max(max_mtime, f.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            pass
    return max_mtime


def scan_with_cache(vault_path: Path) -> WorkspaceSnapshot:
    """Scan the vault, returning a cached result when nothing has changed.

    Cache policy:
    - Within _DEFAULT_TTL_SECONDS (30s): return cached immediately
    - After TTL but within _MAX_CACHE_AGE_SECONDS (5min): check mtime,
      return cached if unchanged, rescan if changed
    - After max age: force rescan

    The cache is in-process only (not shared across workers). This is
    appropriate for SignalVault's single-user local deployment model.
    """
    global _CACHE
    cache_key = str(vault_path.resolve())

    if cache_key in _CACHE:
        cached_at, cached_snapshot = _CACHE[cache_key]
        age = time.time() - cached_at

        if age < _DEFAULT_TTL_SECONDS:
            return cached_snapshot

        current_mtime = _get_vault_mtime_max(vault_path)
        if current_mtime <= cached_at and age < _MAX_CACHE_AGE_SECONDS:
            # mtime hasn't advanced since we cached → no changes
            return cached_snapshot

    # Cache miss or expired — rescan
    scanner = VaultScanner(vault_path)
    snapshot = scanner.scan()
    _CACHE[cache_key] = (time.time(), snapshot)
    return snapshot


def invalidate_cache(vault_path: Path | None = None) -> None:
    """Clear the scan cache for testing or forced refresh.

    If vault_path is None, clears all cached entries.
    """
    global _CACHE
    if vault_path is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(vault_path.resolve()), None)
