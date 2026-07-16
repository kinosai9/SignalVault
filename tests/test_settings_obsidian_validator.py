"""C1-C tests: Obsidian Validator."""

from __future__ import annotations

from signalvault.settings.obsidian_validator import (
    validate_obsidian_vault_path,
)


class TestObsidianValidator:
    def test_empty_path(self):
        result = validate_obsidian_vault_path("")
        assert result.error_message != ""
        assert "不能为空" in result.error_message

    def test_relative_path_rejected(self):
        result = validate_obsidian_vault_path("relative/path")
        assert result.is_absolute is False
        assert "绝对路径" in result.error_message

    def test_nonexistent_path(self, tmp_path):
        result = validate_obsidian_vault_path(str(tmp_path / "nonexistent"))
        assert result.exists is False
        assert "不存在" in result.error_message

    def test_path_is_file_not_directory(self, tmp_path):
        f = tmp_path / "a_file.txt"
        f.write_text("hello")
        result = validate_obsidian_vault_path(str(f))
        assert result.is_directory is False
        assert "不是" in result.error_message

    def test_valid_empty_directory(self, tmp_path):
        """An empty existing directory passes basic checks but fails structure."""
        result = validate_obsidian_vault_path(str(tmp_path))
        assert result.exists is True
        assert result.is_directory is True
        assert result.is_absolute is True
        assert result.is_readable is True
        assert result.test_write_ok is True
        # But not initialized (no manifest)
        assert result.is_signalvault_initialized is False

    def test_has_obsidian_metadata(self, tmp_path):
        (tmp_path / ".obsidian").mkdir()
        result = validate_obsidian_vault_path(str(tmp_path))
        assert result.has_obsidian_metadata is True

    def test_no_obsidian_dir(self, tmp_path):
        result = validate_obsidian_vault_path(str(tmp_path))
        assert result.has_obsidian_metadata is False

    def test_with_manifest_init(self, tmp_path):
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text("{}")
        result = validate_obsidian_vault_path(str(tmp_path))
        assert result.is_signalvault_initialized is True

    def test_checks_missing_dirs(self, tmp_path):
        """validate_obsidian_vault_path delegates to workspace/setup.py validate_vault."""
        result = validate_obsidian_vault_path(str(tmp_path))
        # A fresh directory will have many missing dirs
        assert len(result.missing_dirs) > 0

    def test_path_valid_without_obsidian_dir(self, tmp_path):
        """A writable directory is path_valid even without .obsidian/."""
        result = validate_obsidian_vault_path(str(tmp_path))
        assert result.path_valid is True
        assert result.has_obsidian_metadata is False

    def test_path_valid_not_set_on_error(self, tmp_path):
        """path_valid is False when basic checks fail."""
        result = validate_obsidian_vault_path(str(tmp_path / "nonexistent"))
        assert result.path_valid is False
