"""C1-B: ConfigService — unified configuration with priority chain and source tracking.

Priority (highest to lowest):
    1. Runtime override   (set_runtime_override / clear_runtime_override)
    2. CLI arguments       (injected via set_cli_overrides)
    3. Environment variables (os.environ, including .env loaded by dotenv)
    4. User config.toml     (<AppPaths.config_dir>/config.toml)
    5. Schema defaults

Source tracking: every get_with_source() returns a ConfigValue that records
*which* layer provided the value, so future settings pages can explain why
a saved value appears not to take effect.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalvault.settings.app_paths import AppPaths
from signalvault.settings.schema import (
    RUNTIME_SCHEMA,
    ConfigItem,
    get_defaults,
    get_sensitive_keys,
)
from signalvault.settings.secret_store import SecretStore

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "config.toml"


# ═══════════════════════════════════════════════════════════════════════════
# ConfigValue — resolved value + provenance
# ═══════════════════════════════════════════════════════════════════════════

class Source:
    RUNTIME = "runtime_override"
    CLI = "cli"
    ENV = "env"
    USER = "user_config"
    DEFAULT = "default"


@dataclass(frozen=True)
class ConfigValue:
    """A resolved configuration value with its provenance."""
    key: str
    value: Any
    source: str
    is_overridden: bool = False  # True when a higher-priority source shadows user_config

    @property
    def is_default(self) -> bool:
        return self.source == Source.DEFAULT


# ═══════════════════════════════════════════════════════════════════════════
# ConfigService
# ═══════════════════════════════════════════════════════════════════════════

class ConfigService:
    """Unified configuration service.

    Create via ``ConfigService(app_paths)``.  A module-level convenience
    accessor ``get_config_service()`` is provided for singleton use, but
    tests should construct isolated instances.
    """

    def __init__(
        self,
        app_paths: AppPaths,
        *,
        env: dict[str, str] | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._app_paths = app_paths
        # When env is None, read live os.environ (so monkeypatch.setenv works).
        # When env is a dict (tests), use that snapshot for isolation.
        self._env_source = env  # None = use live os.environ
        self._secret_store = secret_store or SecretStore(app_paths.config_dir)

        # Mutable layers
        self._runtime: dict[str, Any] = {}
        self._cli: dict[str, Any] = {}
        self._user_config: dict[str, Any] = {}
        self._user_config_dirty: bool = False

        # Load user config.toml
        self._load_user_config()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _resolve_env(self) -> dict[str, str]:
        """Return the env dict — live os.environ or test snapshot."""
        if self._env_source is None:
            return dict(os.environ)
        return self._env_source

    def _env_has(self, var_name: str) -> bool:
        """Check if an environment variable is set (non-empty)."""
        if self._env_source is None:
            return bool(os.environ.get(var_name, ""))
        return bool(self._env_source.get(var_name, ""))

    def _env_get(self, var_name: str, default: str = "") -> str:
        """Get an environment variable value."""
        if self._env_source is None:
            return os.environ.get(var_name, default)
        return self._env_source.get(var_name, default)

    # ── Public read API ──────────────────────────────────────────────────

    def get(self, key: str) -> Any:
        """Return the resolved value for *key*."""
        return self.get_with_source(key).value

    def get_with_source(self, key: str) -> ConfigValue:
        """Return the resolved value AND its provenance."""
        item = RUNTIME_SCHEMA.get(key)
        if item is None:
            raise KeyError(f"Unknown config key: {key!r}")

        # 1. Runtime override
        if key in self._runtime:
            return ConfigValue(key, self._runtime[key], Source.RUNTIME,
                               is_overridden=(key in self._user_config))

        # 2. CLI
        if key in self._cli:
            return ConfigValue(key, self._cli[key], Source.CLI,
                               is_overridden=(key in self._user_config))

        # 3. Environment variable (by schema env_var name)
        env_name = item.env_var
        if env_name and self._env_has(env_name):
            raw = self._env_get(env_name)
            val = self._coerce(raw, item)
            return ConfigValue(key, val, Source.ENV,
                               is_overridden=(key in self._user_config))

        # 4. User config.toml
        if key in self._user_config:
            return ConfigValue(key, self._user_config[key], Source.USER)

        # 5. Schema default
        return ConfigValue(key, item.default, Source.DEFAULT)

    def get_string(self, key: str) -> str:
        return str(self.get(key))

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_bool(self, key: str) -> bool:
        val = self.get(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def get_float(self, key: str) -> float:
        return float(self.get(key))

    # ── Secret access ────────────────────────────────────────────────────

    def get_secret(self, key: str) -> str | None:
        """Return a secret value.  Never logged or exported.

        Priority: SecretStore > env var (backward compat fallback).
        """
        item = RUNTIME_SCHEMA.get(key)
        # 1. SecretStore (explicitly saved)
        stored = self._secret_store.get_for_internal_use(key)
        if stored:
            return stored
        # 2. Environment variable (backward compat — .env, os.environ)
        if item and item.env_var:
            env_val = self._env_get(item.env_var, "")
            if env_val:
                return env_val
        return None

    def is_secret_set(self, key: str) -> bool:
        """True if the secret is configured (env or store)."""
        return self.get_secret(key) is not None

    # ── Write API ────────────────────────────────────────────────────────

    def set_user_value(self, key: str, value: Any) -> None:
        """Persist a user configuration value to config.toml.

        Raises ValueError for unknown keys or sensitive keys (use SecretStore).
        """
        item = RUNTIME_SCHEMA.get(key)
        if item is None:
            raise KeyError(f"Unknown config key: {key!r}")
        if item.sensitive:
            raise ValueError(
                f"Cannot store sensitive key {key!r} in config.toml. "
                f"Use SecretStore.set() instead."
            )
        # Validate
        coerced = self._coerce(value, item)
        if item.validator and not item.validator(coerced):
            raise ValueError(f"Invalid value for {key}: {value!r}")

        # Only persist if different from default
        if coerced == item.default:
            self.delete_user_value(key)
            return

        self._user_config[key] = coerced
        self._write_user_config()

    def delete_user_value(self, key: str) -> None:
        """Remove a user-set value, reverting to env/default."""
        if key in self._user_config:
            del self._user_config[key]
            self._write_user_config()

    def set_secret(self, key: str, value: str) -> None:
        """Persist a secret value."""
        if not value or not value.strip():
            self._secret_store.delete(key)
        else:
            self._secret_store.set(key, value)

    def delete_secret(self, key: str) -> None:
        self._secret_store.delete(key)

    # ── Runtime / CLI overrides ──────────────────────────────────────────

    def set_runtime_override(self, key: str, value: Any) -> None:
        """Set a temporary runtime override (highest priority, not persisted)."""
        if key not in RUNTIME_SCHEMA:
            raise KeyError(f"Unknown config key: {key!r}")
        self._runtime[key] = value

    def clear_runtime_override(self, key: str) -> None:
        self._runtime.pop(key, None)

    def set_cli_overrides(self, **kwargs: Any) -> None:
        """Apply CLI argument values (second-highest priority)."""
        for key, value in kwargs.items():
            if key in RUNTIME_SCHEMA:
                self._cli[key] = value

    # ── Lifecycle ────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read config.toml from disk.  Keeps runtime/CLI overrides."""
        self._load_user_config()

    def get_public_snapshot(self) -> dict[str, Any]:
        """Return all non-sensitive config values for diagnostics / display.

        Secret keys are reported as ``{"configured": true/false}``.
        """
        sensitive = frozenset(get_sensitive_keys())
        snapshot: dict[str, Any] = {}
        for key in RUNTIME_SCHEMA:
            if key in sensitive:
                snapshot[key] = {"configured": self.is_secret_set(key)}
            else:
                cv = self.get_with_source(key)
                snapshot[key] = {
                    "value": cv.value,
                    "source": cv.source,
                }
        return snapshot

    # ── Internal ─────────────────────────────────────────────────────────

    def _coerce(self, raw: Any, item: ConfigItem) -> Any:
        """Cast *raw* to the schema-declared type."""
        if raw is None:
            return item.default
        if item.type is bool and isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes")
        try:
            return item.type(raw)
        except (ValueError, TypeError):
            return item.default

    # ── config.toml I/O ──────────────────────────────────────────────────

    @property
    def _config_path(self) -> Path:
        return self._app_paths.config_dir / _CONFIG_FILENAME

    def _load_user_config(self) -> None:
        """Read config.toml; on corruption rename & fall back."""
        path = self._config_path
        if not path.exists():
            self._user_config = {}
            return
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = tomllib.loads(raw)
            self._user_config = self._normalise_toml(parsed)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            # Corrupt — rename, don't overwrite
            ts = _timestamp_str()
            corrupt_path = path.with_name(f"{_CONFIG_FILENAME}.corrupt.{ts}")
            with contextlib.suppress(OSError):
                path.rename(corrupt_path)
            logger.warning(
                "config.toml is corrupt (%s), renamed to %s. Falling back to env/defaults.",
                exc, corrupt_path,
            )
            self._user_config = {}

    def _normalise_toml(self, parsed: dict) -> dict[str, Any]:
        """Convert TOML section-key structure into flat dot-separated keys."""
        flat: dict[str, Any] = {}
        for section, items in parsed.items():
            if isinstance(items, dict):
                for k, v in items.items():
                    full_key = f"{section}.{k}"
                    if full_key in RUNTIME_SCHEMA:
                        flat[full_key] = v
        return flat

    def _write_user_config(self) -> None:
        """Atomically write user_config to config.toml.

        Only saves values that differ from defaults.
        """
        path = self._config_path
        defaults = get_defaults()

        # Build TOML section structure
        sections: dict[str, dict[str, Any]] = {}
        for key, value in sorted(self._user_config.items()):
            if value == defaults.get(key):
                continue  # don't persist default values
            if "." not in key:
                continue
            section, name = key.split(".", 1)
            sections.setdefault(section, {})[name] = value

        if not sections:
            # All values are defaults — remove file
            if path.exists():
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text("", encoding="utf-8")
                tmp.replace(path)  # atomic delete via empty replace
                with contextlib.suppress(OSError):
                    path.unlink()
            return

        # Render TOML
        lines: list[str] = [
            "# SignalVault user configuration",
            "# Written by ConfigService — do not edit while app is running",
            "",
        ]
        for section in sorted(sections):
            lines.append(f"[{section}]")
            for name in sorted(sections[section]):
                val = sections[section][name]
                lines.append(f"{name} = {_toml_value(val)}")
            lines.append("")

        payload = "\n".join(lines)

        # Atomic write
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


# ═══════════════════════════════════════════════════════════════════════════
# TOML helpers (stdlib tomllib reads; manual writer avoids new dependency)
# ═══════════════════════════════════════════════════════════════════════════

def _toml_value(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        # Simple strings (no embedded quotes or newlines in our config)
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (int, float)):
        return str(val)
    return f'"{val}"'


def _timestamp_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ═══════════════════════════════════════════════════════════════════════════
# Module-level singleton accessor
# ═══════════════════════════════════════════════════════════════════════════

_config_service: ConfigService | None = None


def get_config_service() -> ConfigService:
    """Return the module-level ConfigService singleton.

    Created lazily on first call using the AppPaths from ``config.py``.
    Tests can replace this via ``_override_config_service()``.
    """
    global _config_service
    if _config_service is None:
        from signalvault.config import get_app_paths
        _config_service = ConfigService(get_app_paths())
    return _config_service


def _override_config_service(svc: ConfigService | None) -> None:
    """For testing: replace the singleton."""
    global _config_service
    _config_service = svc
