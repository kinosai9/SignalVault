"""CLI mock 模式运行测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

from podcast_research.cli import app

SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"

runner = CliRunner()


def test_cli_mock_analyze(db_session, tmp_path) -> None:
    result = runner.invoke(app, ["--subtitle-file", str(SAMPLE_SRT), "-o", str(tmp_path)])
    assert result.exit_code == 0
    assert "分析完成" in result.output


def test_cli_missing_file() -> None:
    result = runner.invoke(app, ["--subtitle-file", "nonexistent.srt"])
    assert result.exit_code == 1


def test_cli_with_focus(db_session, tmp_path) -> None:
    result = runner.invoke(
        app,
        ["--subtitle-file", str(SAMPLE_SRT), "--focus", "新能源,港股,AI算力", "--mock", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "分析完成" in result.output
    assert "新能源" in result.output or "港股" in result.output or "AI算力" in result.output


def test_cli_with_depth(db_session, tmp_path) -> None:
    result = runner.invoke(
        app,
        ["--subtitle-file", str(SAMPLE_SRT), "--depth", "standard", "--mock", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "分析完成" in result.output


def test_cli_both_inputs_raises() -> None:
    """--subtitle-file 和 --youtube-url 不能同时使用。"""
    result = runner.invoke(
        app,
        ["--subtitle-file", str(SAMPLE_SRT), "--youtube-url", "https://youtu.be/abc"],
    )
    assert result.exit_code == 1
    assert "不能同时使用" in result.output


def test_cli_no_input_raises() -> None:
    """必须提供 --subtitle-file 或 --youtube-url。"""
    result = runner.invoke(app, [])
    assert result.exit_code == 1
    assert "请提供" in result.output


MOCK_TRANSCRIPT_DATA = [
    {"text": "大家好，今天我们来聊聊AI投资", "start": 0.0, "duration": 3.5},
    {"text": "NVIDIA的GPU在AI训练中非常重要", "start": 3.5, "duration": 4.0},
]


@patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
def test_cli_youtube_url_mock(mock_api_class: MagicMock, db_session, tmp_path) -> None:
    """--youtube-url + --mock 模式完整测试（不调用真实 API）。"""
    mock_transcript = MagicMock()
    mock_transcript.language_code = "zh-Hans"
    mock_transcript.is_generated = False
    mock_transcript.fetch.return_value = MOCK_TRANSCRIPT_DATA

    mock_list = MagicMock()
    mock_list.find_transcript.return_value = mock_transcript
    mock_list.__iter__ = MagicMock(return_value=iter([mock_transcript]))
    mock_api_instance = mock_api_class.return_value
    mock_api_instance.list.return_value = mock_list

    result = runner.invoke(
        app,
        ["--youtube-url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--mock", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "分析完成" in result.output