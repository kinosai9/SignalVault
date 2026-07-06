"""P7-A: Error taxonomy tests — registry, creation, mapping, serialization."""

from __future__ import annotations

import pytest

from signalvault.diagnostics.errors import (
    ErrorCategory,
    ErrorCodeRegistry,
    ErrorRecord,
    ErrorSeverity,
    create_error_record,
    map_exception_to_error,
    review_item_to_error_record,
)

# ═════════════════════════════════════════════════════════════════════════════
# ErrorRecord tests
# ═════════════════════════════════════════════════════════════════════════════


class TestErrorRecord:
    def test_default_values(self):
        rec = ErrorRecord()
        assert rec.error_code == ""
        assert rec.severity == "warning"
        assert rec.suggested_actions == []
        assert rec.metadata == {}

    def test_to_dict_contains_all_fields(self):
        rec = ErrorRecord(
            error_code="TEST_001",
            category=ErrorCategory.CONFIG,
            severity=ErrorSeverity.ERROR,
            user_message="测试错误消息",
            suggested_actions=["操作1", "操作2"],
        )
        d = rec.to_dict()
        assert d["error_code"] == "TEST_001"
        assert d["category"] == "config_error"
        assert d["severity"] == "error"
        assert d["user_message"] == "测试错误消息"
        assert len(d["suggested_actions"]) == 2

    def test_to_dict_is_json_serializable(self):
        import json

        rec = ErrorRecord(error_code="T_001", metadata={"key": "value"})
        d = rec.to_dict()
        assert json.dumps(d, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════════════════
# ErrorCodeRegistry tests
# ═════════════════════════════════════════════════════════════════════════════


class TestErrorCodeRegistry:
    def test_registry_has_codes(self):
        count = ErrorCodeRegistry.count()
        assert count >= 20, f"Expected >= 20 codes, got {count}"

    def test_get_valid_code(self):
        rec = ErrorCodeRegistry.get("AUTH_ZSXQ_001")
        assert rec is not None
        assert rec.category == ErrorCategory.AUTH
        assert rec.severity == ErrorSeverity.ERROR
        assert "未登录" in rec.user_message
        assert len(rec.suggested_actions) > 0

    def test_get_invalid_code_returns_none(self):
        rec = ErrorCodeRegistry.get("NONEXISTENT_999")
        assert rec is None

    def test_all_codes_have_user_message_in_chinese(self):
        for rec in ErrorCodeRegistry.list_all():
            assert rec.user_message, f"{rec.error_code}: user_message is empty"
            assert any('一' <= ch <= '鿿' for ch in rec.user_message), \
                f"{rec.error_code}: user_message has no Chinese chars"

    def test_all_codes_have_unique_ids(self):
        codes = [r.error_code for r in ErrorCodeRegistry.list_all()]
        assert len(codes) == len(set(codes)), "Duplicate error_code found"

    def test_list_by_category(self):
        auth_codes = ErrorCodeRegistry.list_by_category(ErrorCategory.AUTH)
        assert len(auth_codes) >= 2
        for rec in auth_codes:
            assert rec.category == ErrorCategory.AUTH

    def test_list_by_severity(self):
        blockers = ErrorCodeRegistry.list_by_severity(ErrorSeverity.BLOCKER)
        assert len(blockers) >= 1
        for rec in blockers:
            assert rec.severity == ErrorSeverity.BLOCKER

    def test_register_duplicate_raises(self):
        rec = ErrorRecord(error_code="DUP_TEST_001", category=ErrorCategory.CONFIG)
        ErrorCodeRegistry.register(rec)
        with pytest.raises(ValueError, match="Duplicate"):
            ErrorCodeRegistry.register(rec)


# ═════════════════════════════════════════════════════════════════════════════
# create_error_record tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateErrorRecord:
    def test_create_from_valid_code(self):
        rec = create_error_record("AUTH_ZSXQ_001")
        assert rec is not None
        assert rec.error_code == "AUTH_ZSXQ_001"
        assert "未登录" in rec.user_message

    def test_create_with_overrides(self):
        rec = create_error_record(
            "AUTH_ZSXQ_001",
            trace_id="op_xyz",
            entity_ref="group:G001",
            technical_detail="CLI returned 'not logged in'",
        )
        assert rec is not None
        assert rec.trace_id == "op_xyz"
        assert rec.entity_ref == "group:G001"
        assert "not logged in" in rec.technical_detail

    def test_create_nonexistent_returns_none(self):
        rec = create_error_record("NONEXISTENT_999")
        assert rec is None

    def test_created_at_is_set(self):
        rec = create_error_record("AUTH_LLM_001")
        assert rec is not None
        assert rec.created_at != ""

    def test_severity_values_are_valid(self):
        for rec in ErrorCodeRegistry.list_all():
            assert rec.severity in ("info", "warning", "error", "blocker"), \
                f"{rec.error_code}: invalid severity '{rec.severity}'"

    def test_all_category_values_are_valid(self):
        valid_categories = {e.value for e in ErrorCategory}
        for rec in ErrorCodeRegistry.list_all():
            assert rec.category in valid_categories, \
                f"{rec.error_code}: invalid category '{rec.category}'"


# ═════════════════════════════════════════════════════════════════════════════
# map_exception_to_error tests
# ═════════════════════════════════════════════════════════════════════════════


class TestMapExceptionToError:
    def test_zsxq_cli_missing_maps_to_config_dep(self):
        from signalvault.sources.zsxq_cli import ZsxqCliMissingError
        exc = ZsxqCliMissingError("zsxq-cli not found")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "CONFIG_DEP_001"

    def test_zsxq_auth_maps_to_auth(self):
        from signalvault.sources.zsxq_cli import ZsxqAuthRequiredError
        exc = ZsxqAuthRequiredError("not logged in")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "AUTH_ZSXQ_001"

    def test_zsxq_permission_maps_to_perm(self):
        from signalvault.sources.zsxq_cli import ZsxqPermissionDeniedError
        exc = ZsxqPermissionDeniedError("access denied")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "PERM_ZSXQ_001"

    def test_zsxq_parse_maps_to_source_parse(self):
        from signalvault.sources.zsxq_cli import ZsxqParseError
        exc = ZsxqParseError("invalid JSON")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "SOURCE_PARSE_001"

    def test_value_error_maps_to_config_invalid(self):
        exc = ValueError("invalid config")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "CONFIG_INVALID_001"

    def test_oserror_maps_to_source_fetch(self):
        exc = OSError("connection refused")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "SOURCE_FETCH_001"

    def test_unknown_exception_maps_to_analysis(self):
        exc = RuntimeError("unexpected error")
        rec = map_exception_to_error(exc)
        assert rec is not None
        assert rec.error_code == "ANALYSIS_PIPELINE_001"


# ═════════════════════════════════════════════════════════════════════════════
# review_item_to_error_record tests
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewItemToError:
    def test_pdf_needs_ocr(self):
        item = {"item_type": "pdf_needs_ocr", "source_path": "test.pdf", "description": "needs OCR"}
        rec = review_item_to_error_record(item)
        assert rec is not None
        assert rec.error_code == "EXTRACT_PDF_003"

    def test_zsxq_cli_missing(self):
        item = {"item_type": "zsxq_cli_missing", "source_path": "zsxq:group:G001"}
        rec = review_item_to_error_record(item)
        assert rec is not None
        assert rec.error_code == "CONFIG_DEP_001"

    def test_zsxq_auth_required(self):
        item = {"item_type": "zsxq_auth_required"}
        rec = review_item_to_error_record(item)
        assert rec is not None
        assert rec.error_code == "AUTH_ZSXQ_001"

    def test_unknown_item_type_returns_none(self):
        item = {"item_type": "lint_frontmatter_invalid"}
        rec = review_item_to_error_record(item)
        assert rec is None
