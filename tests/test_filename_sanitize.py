"""P2-N.4.1: Filename sanitization tests."""

from podcast_research.exporters.markdown_utils import (
    sanitize_filename,
    unique_filename,
)

# ── Basic sanitization ─────────────────────────────────────────────


def test_pipe_character_filtered():
    result = sanitize_filename("Why Markets | IPO Panel")
    assert "|" not in result


def test_colon_question_asterisk_filtered():
    result = sanitize_filename("Test: is this? *really*")
    assert ":" not in result
    assert "?" not in result
    assert "*" not in result


def test_angle_brackets_filtered():
    result = sanitize_filename("foo <bar> baz")
    assert "<" not in result
    assert ">" not in result


def test_quotes_filtered():
    result = sanitize_filename('hello "world"')
    assert '"' not in result


def test_slash_backslash_filtered():
    result = sanitize_filename("path/to\\file")
    assert "/" not in result
    assert "\\" not in result


def test_control_characters_removed():
    result = sanitize_filename("hello\x00\x01\x02world")
    assert "\x00" not in result
    assert "\x01" not in result
    assert "hello" in result


def test_chinese_title_preserved():
    result = sanitize_filename("AI投资研究报告 2024")
    assert "AI投资研究报告" in result


def test_empty_title_fallback():
    result = sanitize_filename("", fallback="report_42")
    assert result == "report_42"


def test_whitespace_only_fallback():
    result = sanitize_filename("   ", fallback="video_abc123")
    assert result == "video_abc123"


def test_very_long_title_truncated():
    long_name = "A" * 300 + " End"
    result = sanitize_filename(long_name)
    assert len(result) <= 150
    assert result.endswith("A")


def test_leading_trailing_dots_stripped():
    result = sanitize_filename("...hello world...")
    assert not result.startswith(".")
    assert not result.endswith(".")


def test_emoji_removed():
    result = sanitize_filename("Hello ⚡ World 🎃 Test")
    assert "⚡" not in result
    assert "🎃" not in result


def test_windows_reserved_name_handled():
    result = sanitize_filename("CON")
    assert result == "_CON"


def test_multiple_hyphens_collapsed():
    result = sanitize_filename("foo---bar   baz")
    assert "---" not in result
    assert "  " not in result


def test_normal_title_preserved():
    result = sanitize_filename("AI Investment Research Report 2024")
    assert result == "AI Investment Research Report 2024"


# ── Unique filename (collision) ────────────────────────────────────


def test_unique_filename_no_collision(tmp_path):
    name = unique_filename(tmp_path, "test_report", "_extraction.json")
    assert name == "test_report_extraction.json"


def test_unique_filename_with_video_id(tmp_path):
    (tmp_path / "test_report_extraction.json").write_text("{}")
    name = unique_filename(tmp_path, "test_report", "_extraction.json",
                           video_id="abc123")
    assert "abc123" in name


# ── Real-world examples ────────────────────────────────────────────


def test_title_with_pipe_uses_fallback():
    """Title with | should have | replaced by -."""
    result = sanitize_filename(
        "Why Secondary Markets Are Eating the IPO | All-In Liquidity Panel",
        fallback="V0lFjTWx36I",
    )
    assert "|" not in result
    assert len(result) > 0


def test_title_with_colon():
    result = sanitize_filename("Palo Alto Networks CEO: AI Found Bugs")
    assert ":" not in result
    assert "Palo Alto Networks CEO" in result
