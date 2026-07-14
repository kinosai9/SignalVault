"""Tests for utils/ modules: hash, timestamp, display, file_io, perf."""

import pytest


# ── hash.py ──────────────────────────────────────────────────────────────────

class TestFileHash:
    def test_deterministic(self, tmp_path):
        from signalvault.utils.hash import file_hash
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h1 = file_hash(f)
        h2 = file_hash(f)
        assert h1 == h2
        assert len(h1) == 32

    def test_different_content(self, tmp_path):
        from signalvault.utils.hash import file_hash
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert file_hash(f1) != file_hash(f2)


# ── timestamp.py ────────────────────────────────────────────────────────────

class TestFormatTimestamp:
    def test_srt_with_milliseconds(self):
        from signalvault.utils.timestamp import format_timestamp
        assert format_timestamp("00:12:34,567") == "00:12:34"

    def test_no_comma(self):
        from signalvault.utils.timestamp import format_timestamp
        assert format_timestamp("01:23:45") == "01:23:45"

    def test_empty_string(self):
        from signalvault.utils.timestamp import format_timestamp
        assert format_timestamp("") == ""


# ── display.py ──────────────────────────────────────────────────────────────

class TestCleanDisplayText:
    def test_strips_markdown_bold(self):
        from signalvault.utils.display import clean_display_text
        assert "hello" in clean_display_text("**hello**")

    def test_strips_backticks(self):
        from signalvault.utils.display import clean_display_text
        result = clean_display_text("`code here`")
        assert "code here" in result

    def test_truncates_long_text(self):
        from signalvault.utils.display import clean_display_text
        long_text = "a" * 500
        result = clean_display_text(long_text, max_len=100)
        assert len(result) <= 103  # max_len + "..."

    def test_cjk_text_preserved(self):
        from signalvault.utils.display import clean_display_text
        result = clean_display_text("中文字幕测试内容")
        assert "中文字幕测试内容" in result

    def test_empty_string(self):
        from signalvault.utils.display import clean_display_text
        assert clean_display_text("") == ""


class TestStripMarkdownInline:
    def test_strips_all_patterns(self):
        from signalvault.utils.display import strip_markdown_inline
        result = strip_markdown_inline("**bold** `code` *italic* # heading")
        assert "bold" in result
        assert "code" in result


# ── file_io.py ──────────────────────────────────────────────────────────────

class TestReadTextSafe:
    def test_utf8(self, tmp_path):
        from signalvault.utils.file_io import read_text_safe
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_text_safe(f) == "hello world"

    def test_gb18030(self, tmp_path):
        from signalvault.utils.file_io import read_text_safe
        f = tmp_path / "test.txt"
        text = "中文字幕测试"
        f.write_bytes(text.encode("gb18030"))
        result = read_text_safe(f)
        assert text in result

    def test_utf8_bom(self, tmp_path):
        from signalvault.utils.file_io import read_text_safe
        f = tmp_path / "test.txt"
        f.write_bytes(b'\xef\xbb\xbfhello')
        result = read_text_safe(f)
        assert "hello" in result

    def test_missing_file(self, tmp_path):
        from signalvault.utils.file_io import read_text_safe
        with pytest.raises(FileNotFoundError):
            read_text_safe(tmp_path / "nonexistent.txt")


class TestWriteTextUtf8:
    def test_roundtrip(self, tmp_path):
        from signalvault.utils.file_io import write_text_utf8, read_text_safe
        f = tmp_path / "test.txt"
        write_text_utf8(f, "hello 中文")
        assert read_text_safe(f) == "hello 中文"


# ── perf.py ─────────────────────────────────────────────────────────────────

class TestPerf:
    def test_measure_stage_context(self):
        from signalvault.utils.perf import measure_stage, get_stage_report
        import signalvault.utils.perf as pm
        pm._stage_timings.clear()
        with measure_stage("test_stage"):
            pass
        report = get_stage_report()
        assert "test_stage" in report
        assert report["test_stage"]["samples"] == 1

    def test_get_stage_report_empty(self):
        from signalvault.utils.perf import get_stage_report
        import signalvault.utils.perf as pm
        pm._stage_timings.clear()
        report = get_stage_report()
        assert report == {}

    def test_multiple_samples(self):
        from signalvault.utils.perf import measure_stage, get_stage_report
        import signalvault.utils.perf as pm
        pm._stage_timings.clear()
        for _ in range(3):
            with measure_stage("multi"):
                pass
        report = get_stage_report()
        assert report["multi"]["samples"] == 3
        assert "avg" in report["multi"]
        assert "max" in report["multi"]
        assert "min" in report["multi"]
