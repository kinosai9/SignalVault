"""P6-A2: ZSXQ topic analysis pipeline — feed ZSXQ topic content into the existing
LLM analysis pipeline with group/topic-level evidence tracking.

Key design:
  - Converts ZsxqTopic content_text into SubtitleSegment-like objects
    where segment_id="zsxq_{topic_id}", timestamps are empty (no video time).
  - Passes through existing _run_pipeline() without modifying it.
  - Eligibility checks prevent analysis of empty/short/attachment-only/inactive topics.
  - Group/topic metadata propagate through source_info and report frontmatter.
  - Evidence uses source_url, group_id, topic_id for traceability.
"""

from __future__ import annotations

import logging
from pathlib import Path

from signalvault.analysis.models import SubtitleSegment
from signalvault.config import REPORT_DIR, ensure_dirs
from signalvault.sources.zsxq_models import ZsxqSourceProfile, ZsxqTopic

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_CONTENT_CHARS = 100  # minimum chars for analysis eligibility


# ── Topic → Segments ─────────────────────────────────────────────────────────


def _topic_to_segments(topic: ZsxqTopic) -> list[SubtitleSegment]:
    """Convert a ZsxqTopic's content_text to SubtitleSegment objects.

    Each topic becomes a single segment:
      - segment_id = "zsxq_{topic_id}"
      - start_time = ""  (no video timestamp)
      - end_time = ""    (no video timestamp)
      - text = content_text

    Returns an empty list if content_text is empty.
    """
    text = (topic.content_text or "").strip()
    if not text:
        return []

    return [SubtitleSegment(
        segment_id=f"zsxq_{topic.topic_id}",
        start_time="",
        end_time="",
        text=text,
    )]


# ── Eligibility Check ────────────────────────────────────────────────────────


def _check_zsxq_analysis_eligibility(
    profile: ZsxqSourceProfile,
) -> tuple[bool, str, list[dict]]:
    """Determine whether a ZSXQ topic is eligible for LLM analysis.

    Returns:
        (eligible, reason, review_findings)

    Ineligible conditions:
      - content_text is empty
      - content_text is too short (< MIN_CONTENT_CHARS)
      - group_access_status != "active"
      - attachment-only topic with minimal body text
      - parse_failed or profile missing key fields
    """
    findings: list[dict] = []

    # 1. Content text empty
    if not profile.content_text or not profile.content_text.strip():
        findings.append({
            "rule": "zsxq_content_too_short",
            "severity": "warning",
            "file_path": f"zsxq:topic:{profile.topic_id}",
            "message": "ZSXQ topic 正文为空，无法进行分析。",
            "detail": f"group_id={profile.group_id}, topic_id={profile.topic_id}",
        })
        return False, "正文为空", findings

    # 2. Content text too short
    if len(profile.content_text.strip()) < MIN_CONTENT_CHARS:
        findings.append({
            "rule": "zsxq_content_too_short",
            "severity": "warning",
            "file_path": f"zsxq:topic:{profile.topic_id}",
            "message": f"ZSXQ topic 正文字数不足（{len(profile.content_text.strip())} < {MIN_CONTENT_CHARS}），不适合分析。",
            "detail": f"group_id={profile.group_id}, topic_id={profile.topic_id}",
        })
        return False, f"文本过短 ({len(profile.content_text.strip())} chars)", findings

    # 3. Inactive group
    if profile.group_access_status != "active":
        findings.append({
            "rule": "zsxq_analysis_skipped",
            "severity": "warning",
            "file_path": f"zsxq:group:{profile.group_id}",
            "message": f"星球 {profile.group_name} 当前状态为 {profile.group_access_status}，跳过分析。",
            "detail": f"group_id={profile.group_id}, topic_id={profile.topic_id}, access_status={profile.group_access_status}",
        })
        return False, f"星球状态为 {profile.group_access_status}", findings

    # 4. Attachment-only topic with minimal body
    has_attachments = len(profile.attachment_metadata) > 0
    if has_attachments and len(profile.content_text.strip()) < 200:
        findings.append({
            "rule": "zsxq_analysis_skipped",
            "severity": "warning",
            "file_path": f"zsxq:topic:{profile.topic_id}",
            "message": "ZSXQ topic 正文不足，主要内容在附件中（附件暂不支持分析）。",
            "detail": f"group_id={profile.group_id}, topic_id={profile.topic_id}, attachments={len(profile.attachment_metadata)}",
        })
        return False, "附件为主、正文不足", findings

    # 5. Parse quality check
    if profile.parse_quality == "minimal":
        findings.append({
            "rule": "zsxq_analysis_skipped",
            "severity": "warning",
            "file_path": f"zsxq:topic:{profile.topic_id}",
            "message": "ZSXQ topic 解析质量过低，无法进行有效分析。",
            "detail": f"parse_quality={profile.parse_quality}",
        })
        return False, "解析质量过低", findings

    # 6. Missing key fields (topic_id, group_id)
    if not profile.topic_id or not profile.group_id:
        findings.append({
            "rule": "zsxq_evidence_missing",
            "severity": "warning",
            "file_path": "zsxq:profile",
            "message": "ZSXQ profile 缺少关键字段（topic_id/group_id）。",
            "detail": f"group_id={profile.group_id}, topic_id={profile.topic_id}",
        })
        return False, "缺少关键字段", findings

    return True, "ok", findings


# ── Source Info Builder ──────────────────────────────────────────────────────


def build_zsxq_analysis_source(profile: ZsxqSourceProfile) -> tuple[dict, dict]:
    """Build source_info and episode_extra dicts for _run_pipeline().

    These dicts carry ZSXQ-specific metadata into the pipeline, report
    frontmatter, and DB episode record.

    Returns:
        (source_info, episode_extra)
    """
    source_info = {
        "source_type": "zsxq_topic",
        "source_url": profile.source_url,
        "title": profile.topic_title,
        "zsxq_group_id": profile.group_id,
        "zsxq_group_name": profile.group_name,
        "zsxq_topic_id": profile.topic_id,
        "zsxq_topic_type": profile.topic_type,
        "zsxq_author": profile.author_name,
        "zsxq_create_time": profile.create_time,
        "zsxq_tags": profile.tags,
        "zsxq_content_hash": profile.content_hash,
    }

    episode_extra = {
        "source": "zsxq_topic",
        "source_url": profile.source_url,
        "video_id": "",  # ZSXQ topics don't have video IDs
        "language": "zh",
    }

    return source_info, episode_extra


# ── Main Analysis Entry Point ────────────────────────────────────────────────


def analyze_zsxq_topic(
    profile: ZsxqSourceProfile,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
    write_review: bool = False,
    db_path: str | None = None,
) -> dict:
    """Analyze a ZSXQ topic through the existing LLM pipeline.

    This is the main entry point for P6-A2. It:
      1. Checks eligibility (writes review items if ineligible)
      2. Builds segments from topic content_text
      3. Passes through existing _run_pipeline()
      4. Writes review items for quality issues

    Args:
        profile: ZsxqSourceProfile from import pipeline.
        provider_name: LLM provider ("mock" or "openai-compatible").
        output_dir: Output directory for reports.
        focus_areas: List of focus areas.
        analysis_depth: "standard" or "deep".
        write_review: If True, write quality findings to review_items.
        db_path: Optional DB path override.

    Returns:
        dict with keys: success, report_id, report_path, view_count,
        entity_count, source_profile, eligible, reason
    """
    ensure_dirs()

    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    # 1. Eligibility check
    eligible, reason, review_findings = _check_zsxq_analysis_eligibility(profile)

    # 2. Write review items if requested (for ineligible cases too)
    if write_review and review_findings:
        from signalvault.db.session import init_db
        from signalvault.sources.review_items import ReviewItemManager
        if db_path:
            init_db(db_path)
        else:
            init_db()
        ReviewItemManager.create_from_lint_findings(review_findings)

    if not eligible:
        logger.warning(
            "ZSXQ topic %s/%s not eligible for analysis: %s",
            profile.group_id, profile.topic_id, reason,
        )
        return {
            "success": False,
            "report_id": 0,
            "report_path": "",
            "view_count": 0,
            "entity_count": 0,
            "eligible": False,
            "reason": reason,
            "source_profile": {
                "group_id": profile.group_id,
                "topic_id": profile.topic_id,
                "topic_title": profile.topic_title,
                "source_type": "zsxq_topic",
            },
        }

    # 3. Build segments from topic content
    # We create a minimal ZsxqTopic to reuse _topic_to_segments
    topic = ZsxqTopic(
        group_id=profile.group_id,
        group_name=profile.group_name,
        topic_id=profile.topic_id,
        topic_title=profile.topic_title,
        content_text=profile.content_text,
    )
    segments = _topic_to_segments(topic)
    logger.info(
        "ZSXQ topic '%s': %d segments, %d chars",
        profile.topic_title, len(segments),
        sum(len(s.text) for s in segments),
    )

    # 4. Build source_info and episode_extra
    source_info, episode_extra = build_zsxq_analysis_source(profile)

    # 5. Run the existing pipeline
    from signalvault.analysis.pipeline import _run_pipeline

    output_path = output_dir or REPORT_DIR

    pipeline_result = _run_pipeline(
        segments=segments,
        episode_title=profile.topic_title or f"ZSXQ-{profile.topic_id}",
        source_path=profile.source_url or f"zsxq:{profile.group_id}:{profile.topic_id}",
        subtitle_format="zsxq_topic",
        subtitle_hash=profile.content_hash,
        provider_name=provider_name,
        output_dir=output_path,
        focus_areas=focus_areas,
        analysis_depth=analysis_depth,
        source_info=source_info,
        episode_extra=episode_extra,
    )

    return {
        "success": True,
        "report_id": pipeline_result.get("report_id", 0),
        "report_path": pipeline_result.get("report_path", ""),
        "extraction_path": pipeline_result.get("extraction_path", ""),
        "view_count": pipeline_result.get("view_count", 0),
        "entity_count": pipeline_result.get("entity_count", 0),
        "eligible": True,
        "reason": "ok",
        "source_profile": {
            "group_id": profile.group_id,
            "group_name": profile.group_name,
            "topic_id": profile.topic_id,
            "topic_title": profile.topic_title,
            "author_name": profile.author_name,
            "source_type": "zsxq_topic",
            "source_url": profile.source_url,
        },
    }


# ── Convenience: fetch + import + analyze in one call ────────────────────────


def _persist_zsxq_provenance(profile, analysis_result: dict) -> None:
    """Persist ZSXQ topic as SourceDocument + SourceSegments. Best-effort."""
    try:
        from signalvault.db.session import get_session, init_db
        from signalvault.db.source_provenance import (
            compute_content_hash,
            create_source_document,
            create_source_segments,
            upsert_source_document,
        )
        init_db()
        session = get_session()
        topic = getattr(profile, "content_text", "") or ""
        ch = profile.content_hash or compute_content_hash(topic)

        doc_id, is_new = upsert_source_document(
            session,
            source_type="zsxq_topic",
            content_hash=ch,
            title=getattr(profile, "topic_title", "") or f"ZSXQ {getattr(profile, 'topic_id', '')}",
            source_url=getattr(profile, "source_url", "") or "",
            access_scope="private_subscription",
            retention_policy="metadata_only",
        )
        if not is_new:
            return

        # Create segments: topic body + comments if present
        segs = [{
            "segment_id": "body", "sequence_index": 0,
            "segment_type": "topic_body",
            "text_original": topic,
            "content_hash": compute_content_hash(topic),
        }]
        if hasattr(profile, "comments") and profile.comments:
            for i, c in enumerate(profile.comments):
                segs.append({
                    "segment_id": f"comment_{i}", "sequence_index": i + 1,
                    "segment_type": "comment",
                    "text_original": getattr(c, "text", str(c)),
                    "content_hash": compute_content_hash(getattr(c, "text", str(c))),
                })
        create_source_segments(session, doc_id, segs)

        # Link Episode
        ep_id = analysis_result.get("episode_id")
        if ep_id:
            from signalvault.db.models import Episode
            ep = session.query(Episode).filter(Episode.id == ep_id).first()
            if ep is not None:
                ep.source_doc_id = doc_id
                session.flush()
    except Exception:
        pass


def import_and_analyze(
    group_id: str,
    topic_id: str,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
    session=None,
) -> dict:
    """Fetch a ZSXQ topic, build profile, check eligibility, and run analysis.

    This combines the import and analysis steps into a single call for CLI use.
    All steps use the existing P6-A1 import pipeline + new P6-A2 analysis.

    Returns:
        dict with keys: success, profile, analysis (from analyze_zsxq_topic),
        error, error_type, review_findings
    """
    from signalvault.sources.zsxq_import import import_topic_to_ingest

    # 1. Import topic (fetch + profile + ingest_job)
    import_result = import_topic_to_ingest(group_id, topic_id, session=session)

    if not import_result["success"]:
        return {
            "success": False,
            "profile": import_result.get("profile"),
            "analysis": None,
            "error": import_result.get("error", "Import failed"),
            "error_type": import_result.get("error_type", "unknown"),
            "review_findings": import_result.get("review_findings", []),
        }

    profile = import_result["profile"]
    if profile is None:
        return {
            "success": False,
            "profile": None,
            "analysis": None,
            "error": "Profile is None after import",
            "error_type": "profile_missing",
            "review_findings": import_result.get("review_findings", []),
        }

    # 2. Check import eligibility
    if not profile.import_eligible:
        return {
            "success": False,
            "profile": profile,
            "analysis": None,
            "error": f"Topic not eligible for import: {profile.ineligible_reason}",
            "error_type": "ineligible",
            "review_findings": import_result.get("review_findings", []),
        }

    # 3. Run analysis
    analysis_result = analyze_zsxq_topic(
        profile=profile,
        provider_name=provider_name,
        output_dir=output_dir,
        focus_areas=focus_areas,
        analysis_depth=analysis_depth,
        write_review=True,
    )

    # Source Provenance: persist ZSXQ topic as SourceDocument + SourceSegments
    _persist_zsxq_provenance(profile, analysis_result)

    return {
        "success": analysis_result["success"],
        "profile": profile,
        "analysis": analysis_result,
        "error": "",
        "error_type": "",
        "review_findings": import_result.get("review_findings", []),
    }
