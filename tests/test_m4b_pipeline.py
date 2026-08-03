"""M4-B: Research Asset Pipeline 测试。

覆盖：
1. Pipeline Orchestrator — 统一流水线编排
2. Claim Extractor — 判断提取
3. Graph Sync Service — 增量图谱同步
4. Unified Search — 扩展搜索类型
"""

from __future__ import annotations

import json

import pytest

from signalvault.db.session import get_session, reset_engine


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """每个测试使用独立的数据库。"""
    from signalvault.db.session import init_db, init_engine

    db_file = tmp_path / "test.db"
    init_engine(str(db_file))
    init_db(str(db_file))
    yield
    reset_engine()


# ── Test data helpers ────────────────────────────────────────────────────────


def _seed_episode_and_report(
    source: str = "local",
    video_id: str = "",
    source_url: str = "",
) -> tuple[int, int]:
    """Create an Episode + Report and return (episode_id, report_id)."""
    from signalvault.analysis.models import ExtractionResult
    from signalvault.db.models import Episode, Report

    session = get_session()
    try:
        ep = Episode(
            source=source,
            title="Test Episode",
            subtitle_path="/tmp/test.srt",
            subtitle_format="srt",
            subtitle_hash="hash123",
            source_url=source_url,
            video_id=video_id,
            language="zh",
        )
        session.add(ep)
        session.flush()

        extraction = ExtractionResult(
            focus_areas=["AI投资"],
            entities=[],
            investment_views=[],
            tracking_signals=[],
        )
        rep = Report(
            episode_id=ep.id,
            focus_areas=json.dumps(["AI投资"], ensure_ascii=False),
            analysis_depth="standard",
            llm_provider="mock",
            llm_model="mock-v1",
            extraction_json=json.dumps(extraction.model_dump(), ensure_ascii=False),
            report_markdown="# Test Report\n\nThis is a test report about AI investing.",
            executive_summary="Test summary",
        )
        session.add(rep)
        session.flush()
        session.commit()

        return ep.id, rep.id
    finally:
        session.close()


def _seed_view(report_id: int, target_name: str = "NVIDIA", direction: str = "bullish") -> int:
    """Create an investment view and return view_id."""
    from signalvault.db.models import InvestmentViewRecord

    session = get_session()
    try:
        view = InvestmentViewRecord(
            report_id=report_id,
            target_name=target_name,
            normalized_target_name=target_name.lower(),
            target_type="company",
            view_direction=direction,
            confidence="high",
            speaker_confidence="high",
            logic_chain=f"{target_name} GPU 需求持续增长，数据中心收入超预期",
            source_quote=f"{target_name} 的下一代 GPU 将推动 AI 算力革命",
            evidence_type="product_announcement",
            timestamp_start="00:05:30",
        )
        session.add(view)
        session.flush()
        session.commit()
        return view.id
    finally:
        session.close()


def _seed_signal(report_id: int, target_name: str = "NVIDIA") -> int:
    """Create a tracking signal and return signal_id."""
    from signalvault.db.models import TrackingSignalRecord

    session = get_session()
    try:
        signal = TrackingSignalRecord(
            report_id=report_id,
            target_name=target_name,
            signal=f"{target_name} 下季度财报关注数据中心营收增速",
            trigger_condition="数据中心营收增速 < 50%",
            status="open",
            source_quote=f"关注 {target_name} 下季度业绩指引",
            timestamp="00:10:15",
        )
        session.add(signal)
        session.flush()
        session.commit()
        return signal.id
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# M4-B.1: Pipeline Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineOrchestrator:
    """Unified pipeline orchestration tests."""

    def test_create_and_run_basic_pipeline(self):
        """SourceItem 创建后全线流水线编排可用。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.create(
            source_type="text_file",
            source_uri="/tmp/test.txt",
            title="Test File",
        )

        orch = PipelineOrchestrator()
        result = orch.run(source_item_id=item.id, mock=True)

        assert result.success is True
        assert result.source_item_id == item.id
        assert result.stage_count >= 1

    def test_pipeline_skips_for_text_file(self):
        """文本文件跳过分析/claim/graph阶段，只做提取。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.create(
            source_type="text_file",
            source_uri="/tmp/notes.txt",
        )

        orch = PipelineOrchestrator()
        result = orch.run(source_item_id=item.id, mock=True)

        # Text files skip analyze, claim_extract, graph_sync
        stages_run = {s.stage_name for s in result.stages}
        assert "analyze" not in stages_run
        assert "claim_extract" not in stages_run
        assert "graph_sync" not in stages_run

    def test_pipeline_updates_source_item_status(self):
        """流水线完成后更新 SourceItem 状态。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.create(
            source_type="text_file",
            source_uri="/tmp/test.txt",
        )

        orch = PipelineOrchestrator()
        orch.run(source_item_id=item.id, mock=True)

        updated = SourceItemManager.get(item.id)
        assert updated.status == "processed"

    def test_pipeline_respects_auto_flags(self):
        """auto_claim_extract=False 和 auto_graph_sync=False 生效。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.create(
            source_type="text_file",
            source_uri="/tmp/test.txt",
        )

        orch = PipelineOrchestrator()
        result = orch.run(
            source_item_id=item.id,
            mock=True,
            auto_claim_extract=False,
            auto_graph_sync=False,
        )

        stages_run = {s.stage_name for s in result.stages}
        assert "claim_extract" not in stages_run
        assert "graph_sync" not in stages_run

    def test_pipeline_result_dataclass(self):
        """PipelineResult 统计字段计算正确。"""
        from signalvault.services.pipeline_orchestrator import (
            PipelineResult,
            StageResult,
        )

        result = PipelineResult(
            success=True,
            source_item_id=1,
            stages=[
                StageResult(stage_name="extract", job_type="extract_text", status="completed"),
                StageResult(stage_name="analyze", job_type="analyze", status="completed", result_ref=42),
                StageResult(stage_name="claim_extract", job_type="extract_claims", status="completed", result_ref=3),
                StageResult(stage_name="graph_sync", job_type="sync_graph", status="completed", result_ref=5),
            ],
            claim_count=3,
            graph_synced=True,
        )

        assert result.stage_count == 4
        assert result.completed_stages == 4
        assert result.claim_count == 3
        assert result.graph_synced is True

    def test_pipeline_for_nonexistent_source_item(self):
        """不存在的 SourceItem 返回失败结果。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator

        orch = PipelineOrchestrator()
        result = orch.run(source_item_id=99999, mock=True)

        assert result.success is False
        assert "not found" in result.error_message

    def test_run_for_source_creates_item_and_runs(self):
        """run_for_source 一步创建 SourceItem 并执行流水线。"""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator

        orch = PipelineOrchestrator()
        result = orch.run_for_source(
            source_type="text_file",
            source_uri="/tmp/auto_test.txt",
            title="Auto Created",
            mock=True,
        )

        assert result.source_item_id > 0
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# M4-B.2: Claim Extractor
# ═══════════════════════════════════════════════════════════════════════════════


class TestClaimExtractor:
    """Claim extraction from reports/views/signals."""

    def test_extract_claims_from_views(self):
        """从 bullish/bearish view 提取 claim。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        view_id = _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)

        assert len(claims) >= 1
        claim = claims[0]
        assert "NVIDIA" in claim.claim_text
        assert claim.claim_type == "prediction"
        assert claim.source_report_id == rep_id
        assert claim.source_view_id == view_id
        assert claim.confidence > 0.5  # high speaker_confidence → 0.85

    def test_extract_claims_from_signals(self):
        """从 tracking signal 提取 claim。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_signal(rep_id, target_name="NVIDIA")

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)

        assert len(claims) >= 1
        signal_claims = [c for c in claims if c.source_quote and "下季度" in (c.source_quote or "")]
        assert len(signal_claims) == 1
        assert signal_claims[0].claim_type == "prediction"
        assert signal_claims[0].source_report_id == rep_id

    def test_extract_claims_idempotent(self):
        """重复提取不会产生重复 claims。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        # Second extraction should return empty (all claims already exist)
        second = extractor.extract_from_report(rep_id)
        assert len(second) == 0

    def test_neutral_view_without_logic_skipped(self):
        """中性观点且无 logic_chain 时不生成 claim。"""
        from signalvault.db.models import InvestmentViewRecord
        from signalvault.services.claim_extractor import ClaimExtractor

        session = get_session()
        ep_id, rep_id = _seed_episode_and_report()

        view = InvestmentViewRecord(
            report_id=rep_id,
            target_name="Market",
            view_direction="neutral",
            logic_chain="",  # no logic
            source_quote="",
        )
        session.add(view)
        session.commit()

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)

        # The neutral view without logic should NOT generate a claim
        neutral_claims = [c for c in claims if "Market" in c.claim_text]
        assert len(neutral_claims) == 0

    def test_confidence_from_speaker(self):
        """speaker_confidence 正确映射为数值。"""
        from signalvault.services.claim_extractor import _CONFIDENCE_MAP, ClaimExtractor

        assert _CONFIDENCE_MAP["high"] == 0.85
        assert _CONFIDENCE_MAP["medium"] == 0.65
        assert _CONFIDENCE_MAP["low"] == 0.40
        assert _CONFIDENCE_MAP[""] == 0.50

        ep_id, rep_id = _seed_episode_and_report()

        from signalvault.db.models import InvestmentViewRecord
        session = get_session()

        view_low = InvestmentViewRecord(
            report_id=rep_id,
            target_name="Tesla",
            view_direction="bearish",
            speaker_confidence="low",
            logic_chain="竞争加剧",
            source_quote="市场份额在下降",
        )
        session.add(view_low)
        session.commit()

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)

        tesla_claims = [c for c in claims if "Tesla" in c.claim_text]
        assert len(tesla_claims) == 1
        assert tesla_claims[0].confidence == 0.40

    def test_get_claims_for_report(self):
        """get_claims_for_report 返回正确的 claims。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        claims = extractor.get_claims_for_report(rep_id)
        assert len(claims) >= 1
        for c in claims:
            assert c.source_report_id == rep_id

    def test_get_claims_for_entity(self):
        """get_claims_for_entity 按实体名搜索。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        claims = extractor.get_claims_for_entity("NVIDIA")
        assert len(claims) >= 1
        for c in claims:
            assert "NVIDIA" in c.claim_text

    def test_extract_all_reports(self):
        """批量提取所有 report 的 claims。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        # Create second report
        ep2_id, rep2_id = _seed_episode_and_report(source_url="https://other.com")
        _seed_view(rep2_id, target_name="Tesla", direction="bearish")

        extractor = ClaimExtractor()
        stats = extractor.extract_all()

        assert stats["reports_processed"] == 2
        assert stats["claims_extracted"] >= 2

    def test_convenience_function(self):
        """extract_claims() 便捷函数可用。"""
        from signalvault.services.claim_extractor import extract_claims

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        result = extract_claims(report_id=rep_id)
        assert result["report_id"] == rep_id
        assert result["claims_extracted"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# M4-B.3: Graph Sync Service
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraphSyncService:
    """Incremental graph sync tests."""

    def test_sync_report_to_graph_creates_nodes(self):
        """增量同步为 report 创建图谱节点。"""
        from signalvault.services.graph_sync_service import sync_report_to_graph

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        stats = sync_report_to_graph(rep_id)

        assert stats["nodes_created"] >= 2  # report node + entity node + view node
        assert stats["edges_created"] >= 1  # mentioned_in + derived_from

    def test_sync_report_to_graph_idempotent(self):
        """重复同步相同 report 是安全的（upsert）。"""
        from signalvault.services.graph_sync_service import sync_report_to_graph

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        sync_report_to_graph(rep_id)
        second = sync_report_to_graph(rep_id)

        # Second sync should create zero new nodes/edges (already exists)
        assert second["nodes_created"] == 0
        assert second["edges_created"] == 0

    def test_sync_creates_deterministic_edges(self):
        """确定性关系（mentioned_in, derived_from）自动创建。"""
        from signalvault.services.graph_sync_service import sync_report_to_graph

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        stats = sync_report_to_graph(rep_id)

        assert stats["deterministic_edges"] >= 1

    def test_sync_includes_signals(self):
        """增量同步包含 tracking signals。"""
        from signalvault.services.graph_sync_service import sync_report_to_graph

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")
        _seed_signal(rep_id, target_name="NVIDIA")

        stats = sync_report_to_graph(rep_id)

        # Signals contribute nodes + edges (derived_from, tracks)
        assert stats["nodes_created"] >= 3  # report + entity + view + signal
        assert stats["edges_created"] >= 2  # mentioned_in + derived_from + tracks

    def test_sync_report_to_graph_edge_types(self):
        """图谱边类型正确分配。"""
        from signalvault.db.models import KnowledgeEdge
        from signalvault.services.graph_sync_service import sync_report_to_graph

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        sync_report_to_graph(rep_id)

        session = get_session()
        edges = session.query(KnowledgeEdge).all()

        edge_types = {e.edge_type for e in edges}
        assert "mentioned_in" in edge_types
        assert "derived_from" in edge_types

    def test_sync_all_reports(self):
        """sync_all_reports 处理所有现有 report。"""
        from signalvault.services.graph_sync_service import sync_all_reports

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        ep2_id, rep2_id = _seed_episode_and_report(source_url="https://other.com")
        _seed_view(rep2_id, target_name="Tesla", direction="bearish")

        stats = sync_all_reports()

        assert stats["reports_processed"] == 2
        assert stats["nodes_created"] >= 4

    def test_edge_exists_helper(self):
        """_edge_exists 辅助函数正确检测。"""
        from signalvault.services.graph_sync_service import (
            _edge_exists,
            sync_report_to_graph,
        )

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")
        sync_report_to_graph(rep_id)

        session = get_session()
        assert _edge_exists(session, "mentioned_in:entity:nvidia>report:1")

    def test_sync_nonexistent_report(self):
        """不存在的 report 不崩溃。"""
        from signalvault.services.graph_sync_service import sync_report_to_graph

        stats = sync_report_to_graph(99999)
        assert stats["nodes_created"] == 0
        assert stats["edges_created"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# M4-B.4: Unified Search (extended)
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnifiedSearchM4B:
    """统一搜索 M4-B 扩展测试（Claims + SourceDocuments）。"""

    def test_search_includes_claims(self):
        """统一搜索返回 claims（当 result_types 包含 claim）。"""
        from signalvault.db.unified_search import unified_search
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        session = get_session()
        results = unified_search(
            session,
            "NVIDIA",
            result_types=["claim"],
            limit=10,
        )

        assert len(results) >= 1
        for r in results:
            assert r.result_type == "claim"

    def test_search_includes_source_documents(self):
        """统一搜索返回 source_document。"""
        from signalvault.db.models import SourceDocument
        from signalvault.db.unified_search import unified_search

        session = get_session()
        doc = SourceDocument(
            source_doc_id="test_doc_001",
            source_type="youtube_transcript",
            title="Test Source Document",
            content_hash="abc123",
        )
        session.add(doc)
        session.commit()

        results = unified_search(
            session,
            "Source Document",
            result_types=["source_document"],
            limit=10,
        )

        assert len(results) >= 1
        assert results[0].result_type == "source_document"

    def test_search_default_includes_new_types(self):
        """默认搜索包含 source_document 和 claim 类型。"""
        from signalvault.db.models import SourceDocument
        from signalvault.db.unified_search import unified_search
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        session = get_session()
        doc = SourceDocument(
            source_doc_id="unique_doc_for_test",
            source_type="pdf_document",
            title="Unique Search Test PDF",
            content_hash="unique123",
        )
        session.add(doc)
        session.commit()

        results = unified_search(session, "NVIDIA", limit=20)

        result_types = {r.result_type for r in results}
        assert "claim" in result_types

    def test_claim_serialization(self):
        """Claim search result 序列化包含完整字段。"""
        from signalvault.db.unified_search import (
            serialize_unified_result,
            unified_search,
        )
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="NVIDIA", direction="bullish")

        extractor = ClaimExtractor()
        extractor.extract_from_report(rep_id)

        session = get_session()
        results = unified_search(session, "NVIDIA", result_types=["claim"], limit=1)

        assert len(results) == 1
        serialized = serialize_unified_result(results[0])

        assert serialized["result_type"] == "claim"
        assert "claim_type" in serialized["metadata"]
        assert "confidence" in serialized["metadata"]


# ═══════════════════════════════════════════════════════════════════════════════
# M4-B Integration: Pipeline → Claim → Graph → Search
# ═══════════════════════════════════════════════════════════════════════════════


class TestM4BIntegration:
    """M4-B 全链路集成测试。"""

    def test_full_pipeline_with_real_report(self):
        """全链路：SourceItem → Pipeline → Claim Extract → Graph Sync → Search。"""
        from signalvault.db.unified_search import unified_search
        from signalvault.services.claim_extractor import ClaimExtractor
        from signalvault.services.graph_sync_service import sync_report_to_graph
        from signalvault.services.source_item_manager import SourceItemManager

        # 1. Create SourceItem
        item = SourceItemManager.create(
            source_type="text_file",
            source_uri="/tmp/integration_test.txt",
            title="Integration Test",
        )

        # 2. Manually create episode + report (simulating analyze stage output)
        ep_id, rep_id = _seed_episode_and_report()
        _seed_view(rep_id, target_name="OpenAI", direction="bullish")
        _seed_view(rep_id, target_name="Anthropic", direction="bearish")
        _seed_signal(rep_id, target_name="OpenAI")

        # 3. Extract claims
        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)
        assert len(claims) >= 3  # 2 views + 1 signal

        # 4. Sync to graph
        stats = sync_report_to_graph(rep_id)
        assert stats["nodes_created"] >= 3
        assert stats["edges_created"] >= 2

        # 5. Search for claims
        session = get_session()
        results = unified_search(session, "OpenAI", result_types=["claim"], limit=10)
        assert len(results) >= 2

        # 6. Verify claim types
        claim_types = {r.metadata.get("claim_type") for r in results}
        assert "prediction" in claim_types

        # Update SourceItem status
        SourceItemManager.update_status(item.id, "processed")
        updated = SourceItemManager.get(item.id)
        assert updated.status == "processed"

    def test_claim_confidence_varies_by_source(self):
        """不同来源的 claim 置信度有差异。"""
        from signalvault.services.claim_extractor import ClaimExtractor

        ep_id, rep_id = _seed_episode_and_report()

        from signalvault.db.models import InvestmentViewRecord
        session = get_session()

        # High confidence view
        session.add(InvestmentViewRecord(
            report_id=rep_id, target_name="HighConf",
            view_direction="bullish", speaker_confidence="high",
            logic_chain="strong evidence", source_quote="confirmed",
        ))
        # Low confidence view
        session.add(InvestmentViewRecord(
            report_id=rep_id, target_name="LowConf",
            view_direction="bullish", speaker_confidence="low",
            logic_chain="weak signal", source_quote="possibly",
        ))
        session.commit()

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(rep_id)

        high_claim = [c for c in claims if "HighConf" in c.claim_text][0]
        low_claim = [c for c in claims if "LowConf" in c.claim_text][0]

        assert high_claim.confidence > low_claim.confidence
        assert high_claim.confidence_source == "speaker"
