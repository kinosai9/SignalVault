"""CLI mock 模式运行测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from signalvault.cli import app

SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"

runner = CliRunner()


def test_cli_mock_analyze(db_session, tmp_path) -> None:
    """--mock 模式完整分析（P2-A1.1: 显式 --mock 防止 .env 污染）。"""
    result = runner.invoke(app, ["--subtitle-file", str(SAMPLE_SRT), "--mock", "-o", str(tmp_path)])
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


@patch("signalvault.adapters.youtube_transcript.YouTubeTranscriptApi")
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


# ---------------------------------------------------------------------------
# P2-A1.1 回归测试：--mock 必须覆盖 .env 中的真实 LLM 配置
# ---------------------------------------------------------------------------

def test_cli_mock_overrides_env_openai_compatible(monkeypatch, db_session, tmp_path) -> None:
    """即使 os.environ 中 LLM_PROVIDER=openai-compatible，--mock 仍使用 mock。

    验证 --mock 优先级高于 .env / os.environ 配置，不会触发真实 LLM API。
    """
    # 模拟用户在 .env 中配置了真实 LLM
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_KEY", "sk-fake-but-would-trigger-api-call")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4")

    result = runner.invoke(
        app,
        ["--subtitle-file", str(SAMPLE_SRT), "--mock", "-o", str(tmp_path)],
    )
    # 即使 env 配置了 openai-compatible，--mock 也应该强制使用 mock
    assert result.exit_code == 0
    assert "分析完成" in result.output
    # 不应该出现真实 LLM 的错误信息
    assert "API" not in result.output
    assert "timeout" not in result.output.lower()
    assert "connection" not in result.output.lower()
