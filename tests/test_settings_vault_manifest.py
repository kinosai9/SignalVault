"""C1-C tests: Vault Manifest CRUD, idempotent init, conflict protection."""

from __future__ import annotations

import json

import pytest

from signalvault.settings.vault_manifest import (
    CURRENT_SCHEMA_VERSION,
    MANAGED_BY,
    ManifestConflictError,
    ensure_manifest,
    read_manifest,
    repair_manifest,
)


def _vault_with_system_dir(tmp_path, name="test_vault"):
    vault = tmp_path / name
    (vault / "99_System").mkdir(parents=True)
    return vault


class TestReadManifest:
    def test_returns_none_when_no_manifest(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        assert read_manifest(vault) is None

    def test_returns_manifest_when_present(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        ensure_manifest(vault)
        m = read_manifest(vault)
        assert m is not None
        assert m.managed_by == MANAGED_BY


class TestEnsureManifest:
    def test_creates_new_manifest(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        m = ensure_manifest(vault, app_version="1.0.0")
        assert m.managed_by == MANAGED_BY
        assert m.vault_schema_version == CURRENT_SCHEMA_VERSION
        assert m.initialized_at != ""
        assert m.app_version == "1.0.0"

    def test_idempotent_init_same_initialized_at(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        m1 = ensure_manifest(vault)
        m2 = ensure_manifest(vault)
        assert m1.initialized_at == m2.initialized_at

    def test_file_created_on_disk(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        ensure_manifest(vault)
        assert (vault / "99_System" / "signalvault_manifest.json").is_file()

    def test_file_is_valid_json(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        ensure_manifest(vault, app_version="2.0.0")
        raw = json.loads(
            (vault / "99_System" / "signalvault_manifest.json").read_text(encoding="utf-8")
        )
        assert raw["managed_by"] == MANAGED_BY
        assert raw["vault_schema_version"] == CURRENT_SCHEMA_VERSION
        assert raw["app_version"] == "2.0.0"

    def test_backfill_for_existing_vault(self, tmp_path):
        """Existing vault without manifest should get a manifest (backfill)."""
        vault = _vault_with_system_dir(tmp_path)
        # Pre-create some vault content but no manifest
        (vault / "01_Reports").mkdir(exist_ok=True)
        (vault / "Home.md").write_text("# Home")
        # Now ensure — should backfill
        m = ensure_manifest(vault)
        assert m.managed_by == MANAGED_BY
        assert m.initialized_at != ""

    def test_conflict_refused(self, tmp_path):
        """Manifest with different managed_by must not be overwritten."""
        vault = _vault_with_system_dir(tmp_path)
        manifest_path = vault / "99_System" / "signalvault_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "managed_by": "other_tool",
            "vault_schema_version": 1,
            "initialized_at": "2024-01-01T00:00:00Z",
        }))
        with pytest.raises(ManifestConflictError, match="other_tool"):
            ensure_manifest(vault)


class TestRepairManifest:
    def test_repair_updates_last_repaired_at(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        ensure_manifest(vault)
        m = repair_manifest(vault)
        assert m is not None
        assert m.last_repaired_at != ""
        assert m.initialized_at != ""  # preserved

    def test_repair_backfills_if_missing(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        m = repair_manifest(vault)
        assert m is not None
        assert m.managed_by == MANAGED_BY

    def test_repair_skips_foreign_manifest(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        manifest_path = vault / "99_System" / "signalvault_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "managed_by": "other_tool",
            "vault_schema_version": 1,
            "initialized_at": "2024-01-01T00:00:00Z",
        }))
        result = repair_manifest(vault)
        assert result is None  # skipped, not ours


class TestAtomicWrite:
    def test_no_tmp_file_left_behind(self, tmp_path):
        vault = _vault_with_system_dir(tmp_path)
        ensure_manifest(vault)
        tmp_files = list(vault.glob("99_System/*.tmp"))
        assert len(tmp_files) == 0

    def test_reading_unfinished_write_returns_none(self, tmp_path):
        """If the file is half-written (empty), read_manifest returns None."""
        vault = _vault_with_system_dir(tmp_path)
        manifest_path = vault / "99_System" / "signalvault_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("", encoding="utf-8")
        assert read_manifest(vault) is None  # corrupt → None
