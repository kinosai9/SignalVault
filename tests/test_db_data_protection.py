"""M3-C-0: 数据升级保护测试。

覆盖：
- 迁移前 DB 自动备份（首次启动不备份、已有 DB 备份、超出上限清理）
- 真实 schema 版本探测（_get_db_status 真查表）
- _track_schema_version 记录 codebase 基线版本
- check_db_integrity 正常返回

测试隔离：备份目录通过 monkeypatch _resolve_backup_dir 指向 tmp_path，
永不写入真实平台用户目录。
"""

from __future__ import annotations

import os
import time

from sqlalchemy import text

from signalvault.analysis.models import (
    Entity,
    ExtractionResult,
    InvestmentView,
    TrackingSignal,
)
from signalvault.db.models import Episode
from signalvault.db.repository import (
    save_episode,
    save_investment_views,
    save_report,
)
from signalvault.db.session import (
    CURRENT_SCHEMA_VERSION,
    MAX_DB_BACKUPS,
    check_db_integrity,
    get_session,
    init_db,
    reset_engine,
)


def _seed_report(db_path: str) -> None:
    """初始化 DB 并写入一条 episode，让 DB 文件非空。"""
    init_db(db_path)
    session = get_session()
    try:
        save_episode(session, "测试播客", "test.srt", "srt", "hash123")
        extraction = ExtractionResult(
            investment_views=[
                InvestmentView(
                    target_name="宁德时代",
                    target_type="stock",
                    view_direction="bullish",
                    logic_chain="储能需求",
                    source_quote="原文",
                    timestamp_start="00:32:10",
                )
            ],
            mentioned_entities=[Entity(name="宁德时代", entity_type="stock")],
            tracking_signals=[
                TrackingSignal(signal="关注储能", target_name="宁德时代")
            ],
        )
        save_report(session, 1, extraction, "# report")
        session.commit()
    finally:
        session.close()
        reset_engine()


# ── 备份行为 ──────────────────────────────────────────────────────────────────


def test_first_run_creates_no_backup(tmp_path, monkeypatch) -> None:
    """首次启动（DB 不存在）不应产生备份。"""
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir", lambda: backup_dir
    )
    db_path = tmp_path / "fresh.db"

    init_db(str(db_path))
    try:
        pass
    finally:
        reset_engine()

    # backup_dir 可能根本没被创建（无备份则不 mkdir）
    assert not backup_dir.exists() or not any(backup_dir.iterdir())


def test_empty_db_creates_no_backup(tmp_path, monkeypatch) -> None:
    """空 DB 文件（size == 0，如测试 fixture mkstemp）不应备份。"""
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir", lambda: backup_dir
    )
    db_path = tmp_path / "empty.db"
    db_path.touch()  # 存在但 size == 0

    init_db(str(db_path))
    try:
        pass
    finally:
        reset_engine()

    assert not backup_dir.exists() or not any(backup_dir.iterdir())


def test_existing_db_gets_backed_up(tmp_path, monkeypatch) -> None:
    """已有数据的 DB，再次 init_db 时应在迁移前生成一份备份。"""
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir", lambda: backup_dir
    )
    db_path = tmp_path / "hasdata.db"

    # 第一次：建库 + 写数据（首次启动无备份）
    _seed_report(str(db_path))
    original_bytes = db_path.read_bytes()
    assert original_bytes  # 确认非空

    # 第二次：DB 已存在且有数据 → 应备份
    init_db(str(db_path))
    try:
        pass
    finally:
        reset_engine()

    backups = list(backup_dir.glob("signalvault-*.db"))
    assert len(backups) == 1
    # 备份内容应等于迁移前的 DB（在 create_all/migrate 之前 copy）
    assert backups[0].read_bytes() == original_bytes


def test_backups_pruned_beyond_max(tmp_path, monkeypatch) -> None:
    """备份数超过 MAX_DB_BACKUPS 时，最旧的被自动清理。"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir", lambda: backup_dir
    )
    db_path = tmp_path / "prune.db"
    _seed_report(str(db_path))

    # 预放 MAX_DB_BACKUPS 份「旧」备份，mtime 递增（old0 最旧）
    base_ts = time.time() - 1_000_000
    for i in range(MAX_DB_BACKUPS):
        f = backup_dir / f"signalvault-old{i}.db"
        f.write_bytes(b"stale")
        ts = base_ts + i
        os.utime(f, (ts, ts))

    # 触发一次新备份
    init_db(str(db_path))
    try:
        pass
    finally:
        reset_engine()

    backups = list(backup_dir.glob("signalvault-*.db"))
    assert len(backups) == MAX_DB_BACKUPS
    # 最旧的 old0 应被删除，新备份（带当前时间戳）应存在
    assert not (backup_dir / "signalvault-old0.db").exists()
    # 新备份不是 stale 占位
    new_backups = [b for b in backups if b.read_bytes() != b"stale"]
    assert len(new_backups) == 1


def test_backup_failure_does_not_block_startup(tmp_path, monkeypatch) -> None:
    """备份函数抛异常时不得阻塞 init_db（返回 None，启动继续）。"""
    db_path = tmp_path / "robust.db"
    _seed_report(str(db_path))

    def _boom() -> None:
        raise OSError("disk full simulation")

    monkeypatch.setattr("signalvault.db.session._resolve_backup_dir", _boom)

    # 即使备份目录解析失败，init_db 必须成功完成
    init_db(str(db_path))
    try:
        session = get_session()
        # 表结构应正常可用
        assert session.query(Episode).count() >= 1
        session.close()
    finally:
        reset_engine()


# ── 真实版本探测 ──────────────────────────────────────────────────────────────


def test_track_schema_version_records_baseline(tmp_path) -> None:
    """init_db 后 schema_version 表应记录 codebase 基线版本。"""
    db_path = tmp_path / "version.db"
    init_db(str(db_path))
    try:
        session = get_session()
        result = session.execute(
            text("SELECT MAX(version) FROM schema_version")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == CURRENT_SCHEMA_VERSION
        session.close()
    finally:
        reset_engine()


def test_get_db_status_reads_real_version(tmp_path) -> None:
    """_get_db_status 应返回真实 schema 版本，而非硬编码 1。"""
    db_path = tmp_path / "status.db"
    init_db(str(db_path))
    try:
        from signalvault.services.settings_overview_service import _get_db_status

        status, version = _get_db_status()
        assert status == "正常"
        assert version == CURRENT_SCHEMA_VERSION
        assert version != 1  # 关键：不再是硬编码的 1
    finally:
        reset_engine()


def test_get_db_status_uninit_engine() -> None:
    """engine 未初始化时返回 ('未初始化', 0)。"""
    reset_engine()
    from signalvault.services.settings_overview_service import _get_db_status

    status, version = _get_db_status()
    assert status == "未初始化"
    assert version == 0


# ── 完整性检查 ────────────────────────────────────────────────────────────────


def test_check_db_integrity_ok(tmp_path) -> None:
    """正常 DB 的 integrity_check 应返回 ok。"""
    db_path = tmp_path / "integrity.db"
    init_db(str(db_path))
    try:
        status, detail = check_db_integrity()
        assert status == "ok"
        assert "通过" in detail
    finally:
        reset_engine()


def test_check_db_integrity_uninit_engine() -> None:
    """engine 未初始化时 integrity_check 返回 error。"""
    reset_engine()
    status, detail = check_db_integrity()
    assert status == "error"
    assert "未初始化" in detail


# ── M3-C-0.5 数据健康展示：辅助函数 ─────────────────────────────────────────


def test_get_backup_info_no_backups(tmp_path, monkeypatch) -> None:
    """无备份时 _get_backup_info 返回 ('从未备份', 0)。"""
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir",
        lambda: tmp_path / "empty_backups",
    )
    from signalvault.services.settings_overview_service import _get_backup_info

    latest, count = _get_backup_info()
    assert latest == "从未备份"
    assert count == 0


def test_get_backup_info_with_backups(tmp_path, monkeypatch) -> None:
    """有备份时返回最新时间戳和数量。"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(
        "signalvault.db.session._resolve_backup_dir", lambda: backup_dir
    )
    (backup_dir / "signalvault-20260101-120000.db").write_bytes(b"x")
    (backup_dir / "signalvault-20260102-120000.db").write_bytes(b"y")
    from signalvault.services.settings_overview_service import _get_backup_info

    latest, count = _get_backup_info()
    assert count == 2


def test_get_data_stats_counts_rows(tmp_path) -> None:
    """_get_data_stats 返回各核心表行数。"""
    db_path = tmp_path / "stats.db"
    init_db(str(db_path))
    try:
        session = get_session()
        ep_id = save_episode(session, "ep", "t.srt", "srt", "h")
        extraction = ExtractionResult(
            investment_views=[
                InvestmentView(
                    target_name="X",
                    target_type="stock",
                    view_direction="bullish",
                    logic_chain="l",
                    source_quote="q",
                    timestamp_start="00:00:10",
                )
            ],
            mentioned_entities=[Entity(name="X", entity_type="stock")],
            tracking_signals=[TrackingSignal(signal="s", target_name="X")],
        )
        rep_id = save_report(session, ep_id, extraction, "# r")
        save_investment_views(session, rep_id, extraction.investment_views)
        session.commit()
        session.close()

        from signalvault.services.settings_overview_service import _get_data_stats

        stats = _get_data_stats()
        assert stats.get("reports", 0) >= 1
        assert stats.get("investment_views", 0) >= 1
        # 所有核心表键都应存在（即使为 0）
        for key in (
            "reports",
            "investment_views",
            "tracking_signals",
            "entities",
            "source_documents",
        ):
            assert key in stats
    finally:
        reset_engine()


def test_get_integrity_status_ok(tmp_path) -> None:
    """正常 DB 的 _get_integrity_status 返回中文 '正常' 标签。"""
    db_path = tmp_path / "integrity.db"
    init_db(str(db_path))
    try:
        from signalvault.services.settings_overview_service import (
            _get_integrity_status,
        )

        label, detail = _get_integrity_status()
        assert label == "正常"
    finally:
        reset_engine()
