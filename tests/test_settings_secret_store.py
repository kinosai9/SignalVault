"""C1-B: SecretStore tests."""

import json
from pathlib import Path

import pytest

from signalvault.settings.secret_store import SecretStore


class TestSecretStoreBasic:
    def test_set_and_get(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("api_key", "sk-secret-123")
        assert store.is_set("api_key") is True
        assert store.get_for_internal_use("api_key") == "sk-secret-123"

    def test_not_set_returns_false(self, tmp_path):
        store = SecretStore(tmp_path)
        assert store.is_set("nonexistent") is False

    def test_get_nonexistent_returns_none(self, tmp_path):
        store = SecretStore(tmp_path)
        assert store.get_for_internal_use("nonexistent") is None

    def test_delete(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("key1", "val1")
        assert store.is_set("key1") is True
        store.delete("key1")
        assert store.is_set("key1") is False

    def test_delete_nonexistent_noop(self, tmp_path):
        store = SecretStore(tmp_path)
        store.delete("nonexistent")  # should not raise

    def test_list_keys(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("b", "val2")
        store.set("a", "val1")
        keys = store.list_keys()
        assert keys == ["a", "b"]  # sorted

    def test_list_keys_empty(self, tmp_path):
        store = SecretStore(tmp_path)
        assert store.list_keys() == []


class TestSecretStoreSafety:
    def test_empty_value_rejected(self, tmp_path):
        store = SecretStore(tmp_path)
        with pytest.raises(ValueError, match="empty"):
            store.set("key", "")

    def test_whitespace_only_rejected(self, tmp_path):
        store = SecretStore(tmp_path)
        with pytest.raises(ValueError, match="empty"):
            store.set("key", "   ")

    def test_overwrite_existing(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("key", "old")
        store.set("key", "new")
        assert store.get_for_internal_use("key") == "new"

    def test_file_not_readable_as_empty(self, tmp_path):
        """Corrupt secrets file isn't a dict — treated as empty."""
        store = SecretStore(tmp_path)
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text("[1, 2, 3]", encoding="utf-8")  # list, not dict
        assert store.list_keys() == []
        assert store.is_set("anything") is False

    def test_corrupt_json_treated_as_empty(self, tmp_path):
        store = SecretStore(tmp_path)
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text("not json {{{", encoding="utf-8")
        assert store.list_keys() == []
        assert store.is_set("anything") is False


class TestSecretStorePersistence:
    def test_survives_new_instance(self, tmp_path):
        store1 = SecretStore(tmp_path)
        store1.set("token", "abc123")

        store2 = SecretStore(tmp_path)
        assert store2.is_set("token") is True
        assert store2.get_for_internal_use("token") == "abc123"

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("key", "value")
        tmp_files = list(Path(tmp_path).glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_directory_auto_created(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        store = SecretStore(deep)
        store.set("key", "val")
        assert store._path.exists()


class TestSecretStorePermissions:
    def test_file_is_created(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("key", "val")
        assert store._path.exists()

    def test_file_readable_by_owner(self, tmp_path):
        store = SecretStore(tmp_path)
        store.set("key", "val")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert data["key"] == "val"
