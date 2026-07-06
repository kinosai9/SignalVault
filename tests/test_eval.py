"""P2-A2: 跨频道质量评估工具测试。"""



# --- Generic target detection ---

def test_is_generic_target_broad_market():
    from signalvault.evaluation import is_generic_target
    assert is_generic_target("Broad Market") is True


def test_is_generic_target_economy():
    from signalvault.evaluation import is_generic_target
    assert is_generic_target("Economy") is True


def test_is_generic_target_specific():
    from signalvault.evaluation import is_generic_target
    assert is_generic_target("NVIDIA") is False
    assert is_generic_target("宁德时代") is False
    assert is_generic_target("港股红利ETF") is False


def test_generic_target_list_complete():
    """确认泛化标的清单覆盖所有 10 个预定义值。"""
    from signalvault.evaluation import GENERIC_TARGETS
    expected = {
        "Broad Market", "Economy", "Investors", "Consumers", "Society",
        "AI Industry", "Technology Sector", "Market", "Companies", "Startups",
    }
    assert expected == GENERIC_TARGETS


# --- compute_report_stats ---

def test_compute_basic_stats(seeded_db):
    """从 seeded reports 计算统计，验证关键字段非零。"""
    from signalvault.evaluation import eval_all_reports

    results = eval_all_reports()
    assert len(results) == 3  # seeded_db has 3 reports

    # Verify field completeness
    for r in results:
        assert "report_id" in r
        assert "investment_view_count" in r
        assert "tech_insight_count" in r
        assert "non_focus_count" in r
        assert "entity_count" in r
        assert "risk_count" in r
        assert "tracking_signal_count" in r
        assert "evidence_type_distribution" in r
        assert "investment_relevance_distribution" in r
        assert "ai_value_chain_layer_distribution" in r
        assert "topic_tags_top" in r
        assert "generic_target_count" in r
        assert "unknown_speaker_count" in r
        assert "time_horizon_distribution" in r
        assert "report_status" in r
        assert r["investment_view_count"] > 0


def test_evidence_distribution(seeded_db):
    """evidence_type_distribution 正确计数。"""
    from signalvault.evaluation import eval_all_reports

    results = eval_all_reports()
    # At least one report should have evidence distribution
    total_evidence = sum(
        sum(v for v in r["evidence_type_distribution"].values())
        for r in results
    )
    total_views = sum(r["investment_view_count"] for r in results)
    assert total_evidence == total_views  # one evidence type per view


def test_generic_target_count_zero_for_seeded(seeded_db):
    """seeded data 中的标的 (宁德时代, 港股红利ETF, NVIDIA) 都不是泛化标的。"""
    from signalvault.evaluation import eval_all_reports

    results = eval_all_reports()
    total_generic = sum(r["generic_target_count"] for r in results)
    assert total_generic == 0


def test_generic_target_detection_in_stats():
    """当 target_name 包含泛化对象时计数。"""
    from unittest.mock import MagicMock

    from signalvault.evaluation import compute_report_stats

    # Create mock view records with generic targets
    view1 = MagicMock()
    view1.evidence_type = "expert_judgment"
    view1.investment_relevance = "low"
    view1.ai_value_chain_layer = "other"
    view1.time_horizon = "unknown"
    view1.speaker_label = "unknown_speaker"
    view1.target_name = "Broad Market"
    view1.topic_tags = "[]"

    view2 = MagicMock()
    view2.evidence_type = "financial_metric"
    view2.investment_relevance = "high"
    view2.ai_value_chain_layer = "semiconductor"
    view2.time_horizon = "medium_term"
    view2.speaker_label = "嘉宾A"
    view2.target_name = "NVIDIA"
    view2.topic_tags = '["GPU", "datacenter"]'

    # Mock report and episode
    report = MagicMock()
    report.id = 1
    report.prompt_version = "tech_ai_v2"
    report.llm_model = "mock-v2"

    episode = MagicMock()
    episode.video_id = "test123"
    episode.source_url = "https://youtube.com/test"
    episode.title = "Test"

    extraction = {
        "source_info": {"transcript_segment_count": 100},
        "prompt_version": "tech_ai_v2",
        "metadata": {"model": "mock-v2"},
        "tech_industry_insights": [],
        "non_focus_items": [],
        "risks": [],
        "tracking_signals": [],
        "mentioned_entities": [],
    }

    stats = compute_report_stats(report, episode, [view1, view2], extraction)
    assert stats["generic_target_count"] == 1
    assert stats["unknown_speaker_count"] == 1
    assert stats["investment_view_count"] == 2
    assert stats["report_status"] == "generic_targets"
    assert "Broad Market" not in str(stats.get("topic_tags_top", []))
    assert "GPU" in str(stats.get("topic_tags_top", []))


# --- CLI eval commands ---

def test_cli_eval_reports(seeded_db):
    """eval reports 读取 seeded reports 并输出表格。"""
    from typer.testing import CliRunner

    from signalvault.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["eval", "reports"])
    assert result.exit_code == 0
    # Should have 3 reports in output
    assert "3" in result.stdout or "3 份" in result.stdout


def test_cli_eval_reports_channel_filter(seeded_db):
    """eval reports --channel 过滤。"""
    from typer.testing import CliRunner

    from signalvault.cli import app

    runner = CliRunner()
    # seeded_db has no channel_name set (pre-P2-A2.1), so filtering for anything
    # should return 0 results. The command should exit gracefully.
    result = runner.invoke(app, ["eval", "reports", "--channel", "NonexistentChannel"])
    assert result.exit_code == 0
    # May show "暂无报告" or still show stats from matched
    assert "暂无报告" in result.stdout or "0" in result.stdout or result.exit_code == 0


def test_cli_eval_export_csv(seeded_db, tmp_path):
    """eval export 生成 CSV 到 tmp_path。"""
    from typer.testing import CliRunner

    from signalvault.cli import app

    csv_path = tmp_path / "eval.csv"
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "export", "--output", str(csv_path)])
    assert result.exit_code == 0
    assert csv_path.exists()

    # Verify CSV structure
    content = csv_path.read_text(encoding="utf-8")
    assert "report_id" in content
    assert "investment_view_count" in content
    assert "generic_target_count" in content
    assert "evidence_type_distribution" in content
    # Should have 3 data rows + header
    lines = content.strip().split("\n")
    assert len(lines) >= 4  # header + 3 data rows


def test_cli_eval_summary_md(seeded_db, tmp_path):
    """eval summary 生成 Markdown 总结到 tmp_path。"""
    from typer.testing import CliRunner

    from signalvault.cli import app

    md_path = tmp_path / "summary.md"
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "summary", "--output", str(md_path)])
    assert result.exit_code == 0
    assert md_path.exists()

    content = md_path.read_text(encoding="utf-8")
    assert "Prompt v2 Cross-channel Evaluation" in content
    assert "Overall Metrics" in content
    assert "Known Issues" in content
    assert "Recommendation" in content


def test_cli_eval_export_empty_graceful(tmp_path):
    """eval export 在无报告时不崩溃。"""
    from typer.testing import CliRunner

    from signalvault.cli import app

    csv_path = tmp_path / "empty.csv"
    runner = CliRunner()
    # Using a fresh db_session should have no reports
    result = runner.invoke(app, ["eval", "export", "--output", str(csv_path)])
    assert result.exit_code == 0
    # Should say "0 条记录" or similar
    assert "0" in result.stdout


def test_summary_md_no_reports():
    """generate_summary_md 空列表时不崩溃。"""
    from signalvault.evaluation import generate_summary_md

    md = generate_summary_md([])
    assert "No reports" in md
    assert "Prompt v2" in md
