"""Mock LLM pipeline 全流程测试。"""

from pathlib import Path

from podcast_research.analysis.pipeline import analyze

SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"


def test_pipeline_mock_mode(db_session, tmp_path) -> None:
    result = analyze(SAMPLE_SRT, provider_name="mock", output_dir=tmp_path)
    assert result["view_count"] > 0
    assert result["entity_count"] > 0
    assert result["report_id"] > 0
    assert result["episode_id"] > 0


def test_pipeline_output_files_exist(db_session, tmp_path) -> None:
    result = analyze(SAMPLE_SRT, provider_name="mock", output_dir=tmp_path)
    report_path = Path(result["report_path"])
    json_path = Path(result["extraction_path"])
    assert report_path.exists()
    assert json_path.exists()


def test_pipeline_report_content(db_session, tmp_path) -> None:
    result = analyze(SAMPLE_SRT, provider_name="mock", output_dir=tmp_path)
    report_path = Path(result["report_path"])
    content = report_path.read_text(encoding="utf-8")
    assert "免责声明" in content
    assert "核心观点矩阵" in content
    assert "风险提示" in content
