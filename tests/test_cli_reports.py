"""CLI reports 子命令测试（P1-A）。"""

from typer.testing import CliRunner

from signalvault.cli import app

runner = CliRunner()


def test_cli_reports_list(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "list"])
    assert result.exit_code == 0
    assert "ID" in result.output
    assert "来源" in result.output


def test_cli_reports_list_with_source_filter(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "list", "--source", "youtube"])
    assert result.exit_code == 0
    assert "youtube" in result.output


def test_cli_reports_list_with_limit(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "list", "--limit", "1"])
    assert result.exit_code == 0


def test_cli_reports_show(seeded_db) -> None:
    # 先拿一个真实存在的 report ID
    from signalvault.db.repository import list_reports
    rows = list_reports(seeded_db)
    rid = str(rows[0]["id"])

    result = runner.invoke(app, ["reports", "show", rid])
    assert result.exit_code == 0
    assert "报告" in result.output


def test_cli_reports_show_full(seeded_db) -> None:
    from signalvault.db.repository import list_reports
    rows = list_reports(seeded_db)
    rid = str(rows[0]["id"])

    result = runner.invoke(app, ["reports", "show", rid, "--full"])
    assert result.exit_code == 0


def test_cli_reports_show_not_found(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "show", "9999"])
    assert result.exit_code == 1
    assert "未找到" in result.output


def test_cli_reports_search(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "search", "宁德时代"])
    assert result.exit_code == 0
    assert "报告ID" in result.output or "宁德时代" in result.output


def test_cli_reports_search_no_match(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "search", "ZZZZNOTFOUND"])
    assert result.exit_code == 0
    assert "未找到" in result.output


def test_cli_reports_targets(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "targets"])
    assert result.exit_code == 0
    assert "标的" in result.output


def test_cli_reports_sources(seeded_db) -> None:
    result = runner.invoke(app, ["reports", "sources"])
    assert result.exit_code == 0
    assert "来源" in result.output


def test_cli_reports_empty_db(db_session) -> None:
    """空数据库时各命令不崩溃。"""
    result = runner.invoke(app, ["reports", "list"])
    assert result.exit_code == 0
    assert "暂无" in result.output

    result = runner.invoke(app, ["reports", "targets"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["reports", "sources"])
    assert result.exit_code == 0
