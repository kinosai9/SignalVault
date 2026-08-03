"""M4-B.1: Unified Pipeline Orchestrator.

Orchestrates the full Research Asset Pipeline:
  SourceItem → Extract → Analyze → Claim Extract → Graph Sync

Integrates SourceItemManager, ProcessingJobManager, the existing analysis
pipeline, and the new Claim Extractor / Graph Sync Service.

Design principles:
- Pure orchestration: delegates to existing services, doesn't duplicate logic
- SourceItem-driven: any source_type can enter the pipeline
- ProcessingJob tracking: each stage creates/updates a ProcessingJob
- Graceful degradation: failures at one stage don't block downstream stages
  (e.g., claim extraction failure doesn't prevent graph sync)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Pipeline result types ────────────────────────────────────────────────────

@dataclass
class StageResult:
    """Result of a single pipeline stage."""
    stage_name: str
    job_type: str
    status: str = "pending"          # pending / running / completed / failed / skipped
    job_id: int | None = None
    result_ref: int | None = None     # report_id / claim_count / etc.
    result_type: str = ""
    error_message: str = ""
    duration_seconds: int = 0
    llm_calls: int = 0
    tokens_used: int = 0


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    success: bool = False
    source_item_id: int = 0
    report_id: int | None = None
    episode_id: int | None = None
    stages: list[StageResult] = field(default_factory=list)
    claim_count: int = 0
    graph_synced: bool = False
    error_message: str = ""

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.stages if s.status == "completed")

    @property
    def total_llm_calls(self) -> int:
        return sum(s.llm_calls for s in self.stages)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_used for s in self.stages)


# ── Pipeline stages ──────────────────────────────────────────────────────────

class PipelineStage:
    """Base class for pipeline stages."""

    def __init__(self, name: str, job_type: str):
        self.name = name
        self.job_type = job_type

    def execute(
        self,
        source_item_id: int,
        source_type: str,
        source_uri: str,
        params: dict[str, Any] | None = None,
    ) -> StageResult:
        """Execute this stage. Override in subclasses."""
        raise NotImplementedError


class _ExtractStage(PipelineStage):
    """Stage 1: Extract text from source (PDF, web page, file, etc.).

    For YouTube, the transcript is fetched by the YouTube adapter; this stage
    is skipped for YouTube sources (extraction happens in adapter layer).
    """

    def __init__(self):
        super().__init__("extract", "extract_text")

    def execute(self, source_item_id, source_type, source_uri, params=None):
        from signalvault.services.processing_job_manager import ProcessingJobManager

        # Create job
        job = ProcessingJobManager.create(
            source_item_id=source_item_id,
            job_type=self.job_type,
            priority=9,
            params=params or {},
        )

        result = StageResult(
            stage_name=self.name,
            job_type=self.job_type,
            job_id=job.id,
        )

        # For YouTube, text extraction happens in the adapter — skip
        if source_type in ("youtube_video", "youtube_channel"):
            result.status = "skipped"
            result.result_type = "adapter_handled"
            ProcessingJobManager.mark_completed(job.id, result_type="adapter_handled")
            return result

        # For PDF — extraction is handled in pdf_analysis flow
        if source_type == "pdf_document":
            result.status = "skipped"
            result.result_type = "pdf_analysis_handled"
            ProcessingJobManager.mark_completed(job.id, result_type="pdf_analysis_handled")
            return result

        # For web pages, text files — extraction is handled by source adapters
        result.status = "skipped"
        result.result_type = "source_adapter_handled"
        ProcessingJobManager.mark_completed(job.id, result_type="source_adapter_handled")
        return result


class _AnalyzeStage(PipelineStage):
    """Stage 2: Analyze content via LLM pipeline.

    Dispatches to the appropriate analysis path based on source_type:
    - youtube_video → analyze_youtube_url()
    - pdf_document → analyze_pdf()
    - Others → generic analysis path
    """

    def __init__(self):
        super().__init__("analyze", "analyze")

    def execute(self, source_item_id, source_type, source_uri, params=None):
        from signalvault.services.processing_job_manager import ProcessingJobManager

        params = params or {}
        focus = params.get("focus", "")
        depth = params.get("depth", "standard")
        mock = params.get("mock", True)

        job = ProcessingJobManager.create(
            source_item_id=source_item_id,
            job_type=self.job_type,
            priority=7,
            params={"focus": focus, "depth": depth, "mock": mock},
        )

        result = StageResult(
            stage_name=self.name,
            job_type=self.job_type,
            job_id=job.id,
        )

        try:
            ProcessingJobManager.mark_running(job.id)
            start = datetime.now()

            if source_type == "youtube_video":
                from signalvault.services.analyze_service import analyze_youtube_url

                focus_list = [f.strip() for f in focus.split(",") if f.strip()] if focus else None
                analyze_result = analyze_youtube_url(
                    youtube_url=source_uri,
                    focus_areas=focus_list,
                    depth=depth or "standard",
                    mock=mock,
                )

                if analyze_result.success:
                    result.status = "completed"
                    result.result_ref = analyze_result.report_id
                    result.result_type = "report"
                else:
                    result.status = "failed"
                    result.error_message = analyze_result.message

            elif source_type == "pdf_document":
                try:
                    from signalvault.sources.pdf_analysis import analyze_pdf

                    pdf_result = analyze_pdf(
                        pdf_path=source_uri,
                        mock=mock,
                        focus=focus or None,
                        depth=depth or "standard",
                    )
                    if pdf_result and pdf_result.get("report_id"):
                        result.status = "completed"
                        result.result_ref = pdf_result["report_id"]
                        result.result_type = "report"
                    else:
                        result.status = "failed"
                        result.error_message = "PDF analysis returned no report"
                except ImportError:
                    result.status = "skipped"
                    result.error_message = "PDF analysis module not available"
                except Exception as e:
                    result.status = "failed"
                    result.error_message = str(e)

            elif source_type in ("web_page", "text_file", "rss_article"):
                # Generic source — skip LLM analysis (text extraction only)
                result.status = "skipped"
                result.result_type = "text_extraction_only"

            else:
                result.status = "skipped"
                result.result_type = "unsupported_source_type"

            # Update cost stats
            elapsed = int((datetime.now() - start).total_seconds())
            result.duration_seconds = elapsed
            ProcessingJobManager.update_cost(job.id, duration_seconds=elapsed)

            if result.status == "completed":
                ProcessingJobManager.mark_completed(
                    job.id,
                    result_type=result.result_type,
                    result_ref=result.result_ref,
                )
            elif result.status == "failed":
                ProcessingJobManager.mark_failed(job.id, result.error_message)
            elif result.status == "skipped":
                ProcessingJobManager.mark_completed(job.id, result_type=result.result_type)

        except Exception as e:
            logger.exception(f"Analyze stage failed for SourceItem {source_item_id}")
            result.status = "failed"
            result.error_message = str(e)
            ProcessingJobManager.mark_failed(job.id, str(e))

        return result


class _ClaimExtractStage(PipelineStage):
    """Stage 3: Extract claims from analysis results.

    Requires a completed analyze stage with a valid report_id.
    """

    def __init__(self):
        super().__init__("claim_extract", "extract_claims")

    def execute(self, source_item_id, source_type, source_uri, params=None):
        from signalvault.services.claim_extractor import ClaimExtractor
        from signalvault.services.processing_job_manager import ProcessingJobManager

        job = ProcessingJobManager.create(
            source_item_id=source_item_id,
            job_type=self.job_type,
            priority=5,
            params=params or {},
        )

        result = StageResult(
            stage_name=self.name,
            job_type=self.job_type,
            job_id=job.id,
        )

        report_id = (params or {}).get("report_id")
        if not report_id:
            result.status = "skipped"
            result.result_type = "no_report"
            ProcessingJobManager.mark_completed(job.id, result_type="no_report")
            return result

        try:
            ProcessingJobManager.mark_running(job.id)
            start = datetime.now()

            extractor = ClaimExtractor()
            claims = extractor.extract_from_report(report_id)

            result.status = "completed"
            result.result_ref = len(claims)
            result.result_type = "claims"

            elapsed = int((datetime.now() - start).total_seconds())
            result.duration_seconds = elapsed
            ProcessingJobManager.update_cost(job.id, duration_seconds=elapsed)
            ProcessingJobManager.mark_completed(
                job.id,
                result_type="claims",
                result_ref=len(claims),
            )

        except Exception as e:
            logger.exception(f"Claim extraction failed for report {report_id}")
            result.status = "failed"
            result.error_message = str(e)
            ProcessingJobManager.mark_failed(job.id, str(e))

        return result


class _GraphSyncStage(PipelineStage):
    """Stage 4: Sync analysis results to knowledge graph.

    Incrementally adds nodes and edges for a single report.
    """

    def __init__(self):
        super().__init__("graph_sync", "sync_graph")

    def execute(self, source_item_id, source_type, source_uri, params=None):
        from signalvault.services.graph_sync_service import sync_report_to_graph
        from signalvault.services.processing_job_manager import ProcessingJobManager

        job = ProcessingJobManager.create(
            source_item_id=source_item_id,
            job_type=self.job_type,
            priority=3,
            params=params or {},
        )

        result = StageResult(
            stage_name=self.name,
            job_type=self.job_type,
            job_id=job.id,
        )

        report_id = (params or {}).get("report_id")
        if not report_id:
            result.status = "skipped"
            result.result_type = "no_report"
            ProcessingJobManager.mark_completed(job.id, result_type="no_report")
            return result

        try:
            ProcessingJobManager.mark_running(job.id)
            start = datetime.now()

            stats = sync_report_to_graph(report_id)

            result.status = "completed"
            result.result_ref = stats.get("edges_created", 0)
            result.result_type = "graph_sync"

            elapsed = int((datetime.now() - start).total_seconds())
            result.duration_seconds = elapsed
            ProcessingJobManager.update_cost(job.id, duration_seconds=elapsed)
            ProcessingJobManager.mark_completed(
                job.id,
                result_type="graph_sync",
                result_ref=stats.get("edges_created", 0),
            )

        except Exception as e:
            logger.exception(f"Graph sync failed for report {report_id}")
            result.status = "failed"
            result.error_message = str(e)
            ProcessingJobManager.mark_failed(job.id, str(e))

        return result


# ── Pipeline stages registry ─────────────────────────────────────────────────

# Ordered list of stages in the pipeline
_DEFAULT_STAGES: list[PipelineStage] = [
    _ExtractStage(),
    _AnalyzeStage(),
    _ClaimExtractStage(),
    _GraphSyncStage(),
]

# source_type → stages to skip
_STAGE_SKIP_MAP: dict[str, set[str]] = {
    "youtube_video": {"extract"},       # extraction in adapter
    "youtube_channel": {"extract", "analyze"},  # channel not directly analyzed
    "pdf_document": {"extract"},        # extraction in pdf_analysis
    "web_page": {"analyze", "claim_extract", "graph_sync"},  # text-only for now
    "text_file": {"analyze", "claim_extract", "graph_sync"}, # text-only for now
    "rss_article": {"analyze", "claim_extract", "graph_sync"},  # text-only for now
}


# ── Orchestrator ─────────────────────────────────────────────────────────────

class PipelineOrchestrator:
    """Unified pipeline orchestrator for Research Asset Lifecycle.

    Usage:
        orch = PipelineOrchestrator()
        result = orch.run(source_item_id=42)
        # or with a new SourceItem:
        result = orch.run_for_source(
            source_type="youtube_video",
            source_uri="https://youtube.com/watch?v=...",
            focus="AI投资",
        )
    """

    def __init__(self, stages: list[PipelineStage] | None = None):
        self.stages = stages or _DEFAULT_STAGES

    def run(
        self,
        source_item_id: int,
        *,
        focus: str = "",
        depth: str = "standard",
        mock: bool = True,
        auto_claim_extract: bool = True,
        auto_graph_sync: bool = True,
    ) -> PipelineResult:
        """Run the full pipeline for an existing SourceItem.

        Args:
            source_item_id: ID of the SourceItem to process.
            focus: Comma-separated focus areas for analysis.
            depth: Analysis depth (standard / deep).
            mock: Use mock LLM provider.
            auto_claim_extract: Whether to extract claims after analysis.
            auto_graph_sync: Whether to sync to knowledge graph after analysis.

        Returns:
            PipelineResult with stage-by-stage results and overall status.
        """
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.get(source_item_id)
        if not item:
            return PipelineResult(
                success=False,
                source_item_id=source_item_id,
                error_message=f"SourceItem {source_item_id} not found",
            )

        # Mark SourceItem as processing
        SourceItemManager.update_status(source_item_id, "processing")

        pipeline_result = PipelineResult(
            success=True,
            source_item_id=source_item_id,
        )

        skip_set = _STAGE_SKIP_MAP.get(item.source_type, set())
        shared_params: dict[str, Any] = {
            "focus": focus,
            "depth": depth,
            "mock": mock,
        }

        report_id: int | None = None

        for stage in self.stages:
            # Check if this stage should be skipped for this source_type
            if stage.name in skip_set:
                continue

            # Check runtime flags
            if stage.name == "claim_extract" and not auto_claim_extract:
                continue
            if stage.name == "graph_sync" and not auto_graph_sync:
                continue

            # Pass report_id from analyze stage to downstream stages
            stage_params = dict(shared_params)
            if report_id and stage.name in ("claim_extract", "graph_sync"):
                stage_params["report_id"] = report_id

            stage_result = stage.execute(
                source_item_id=source_item_id,
                source_type=item.source_type,
                source_uri=item.source_uri,
                params=stage_params,
            )

            pipeline_result.stages.append(stage_result)

            # Track report_id from analyze stage
            if stage.name == "analyze" and stage_result.result_ref:
                report_id = stage_result.result_ref
                pipeline_result.report_id = report_id

            # Track claim count
            if stage.name == "claim_extract" and stage_result.result_ref:
                pipeline_result.claim_count = stage_result.result_ref or 0

            # Track graph sync
            if stage.name == "graph_sync" and stage_result.status == "completed":
                pipeline_result.graph_synced = True

            # Critical failure: if analyze fails, we can't continue
            if stage.name == "analyze" and stage_result.status == "failed":
                pipeline_result.success = False
                pipeline_result.error_message = stage_result.error_message
                break

        # Update SourceItem status
        final_status = (
            "processed"
            if pipeline_result.success
            else "failed"
        )
        SourceItemManager.update_status(source_item_id, final_status)

        logger.info(
            "Pipeline complete for SourceItem %d: success=%s stages=%d/%d claims=%d graph=%s",
            source_item_id,
            pipeline_result.success,
            pipeline_result.completed_stages,
            pipeline_result.stage_count,
            pipeline_result.claim_count,
            pipeline_result.graph_synced,
        )

        return pipeline_result

    def run_for_source(
        self,
        source_type: str,
        source_uri: str,
        *,
        title: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        focus: str = "",
        depth: str = "standard",
        mock: bool = True,
        provenance: str = "user_intake",
    ) -> PipelineResult:
        """Create a SourceItem and run the full pipeline.

        Convenience method combining SourceItemManager.create() + self.run().
        """
        from signalvault.services.source_item_manager import SourceItemManager

        item = SourceItemManager.create(
            source_type=source_type,
            source_uri=source_uri,
            title=title,
            description=description,
            metadata=metadata,
            provenance=provenance,
        )

        return self.run(
            source_item_id=item.id,
            focus=focus,
            depth=depth,
            mock=mock,
        )


# ── Convenience function ─────────────────────────────────────────────────────

def run_pipeline_for_source(
    source_type: str,
    source_uri: str,
    **kwargs,
) -> PipelineResult:
    """Run the full pipeline for a source in one call.

    Shortcut for PipelineOrchestrator().run_for_source().
    """
    orch = PipelineOrchestrator()
    return orch.run_for_source(source_type=source_type, source_uri=source_uri, **kwargs)
