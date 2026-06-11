"""P2-A2: 跨频道 Prompt v2 质量评估工具。

统计函数 + CLI eval 子命令，支持：
- eval reports: 终端表格展示
- eval export: CSV 导出
- eval summary: Markdown 总结导出
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from podcast_research.db.models import Episode, InvestmentViewRecord, Report
from podcast_research.db.session import get_session, init_db

logger = logging.getLogger(__name__)

# ── Generic target keywords ──

GENERIC_TARGETS = frozenset({
    "Broad Market", "Economy", "Investors", "Consumers", "Society",
    "AI Industry", "Technology Sector", "Market", "Companies", "Startups",
})


def is_generic_target(target_name: str) -> bool:
    """检测 target_name 是否属于过泛对象。"""
    return target_name.strip() in GENERIC_TARGETS


# ── Per-report stats ──


def compute_report_stats(
    report: Report,
    episode: Episode,
    views: list[InvestmentViewRecord],
    extraction: dict,
) -> dict:
    """计算单份报告的评估统计。"""
    source_info = extraction.get("source_info", {}) or {}

    # Evidence type distribution
    evidence_counter: Counter[str] = Counter()
    relevance_counter: Counter[str] = Counter()
    ai_chain_counter: Counter[str] = Counter()
    horizon_counter: Counter[str] = Counter()
    topic_tags_counter: Counter[str] = Counter()
    generic_count = 0
    unknown_speaker_count = 0

    for v in views:
        et = v.evidence_type or "unsupported_claim"
        evidence_counter[et] += 1
        rel = v.investment_relevance or "medium"
        relevance_counter[rel] += 1
        chain = v.ai_value_chain_layer or "other"
        ai_chain_counter[chain] += 1
        horizon = v.time_horizon or "unknown"
        horizon_counter[horizon] += 1

        if v.speaker_label in ("unknown_speaker", "未识别发言人", ""):
            unknown_speaker_count += 1

        if is_generic_target(v.target_name):
            generic_count += 1

        # Topic tags
        raw_tags = v.topic_tags or "[]"
        try:
            tags = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
            for t in (tags or []):
                topic_tags_counter[t] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # Tech insights & non-focus from extraction
    tech_insights = extraction.get("tech_industry_insights", []) or []
    non_focus = extraction.get("non_focus_items", []) or []
    risks = extraction.get("risks", []) or []
    signals = extraction.get("tracking_signals", []) or []
    entities = extraction.get("mentioned_entities", []) or []

    seg_count = source_info.get("transcript_segment_count", 0)
    estimated_tokens = seg_count * 30  # rough: ~30 tokens per segment

    # Top topic tags
    top_tags = [tag for tag, _ in topic_tags_counter.most_common(5)]

    # Channel name from source_info
    channel_name = source_info.get("channel_name", "") or ""

    # Prompt version
    prompt_ver = extraction.get("prompt_version", "") or report.prompt_version or ""

    # Model
    model = extraction.get("metadata", {}).get("model", "") if isinstance(extraction.get("metadata"), dict) else ""
    if not model:
        model = report.llm_model or ""

    # Determine report status
    status = "ok"
    if not views and not tech_insights:
        status = "empty"
    elif generic_count > 0:
        status = "generic_targets"

    return {
        "report_id": report.id,
        "channel_name": channel_name,
        "video_id": episode.video_id or "",
        "source_url": episode.source_url or "",
        "prompt_version": prompt_ver,
        "model": model,
        "transcript_segment_count": seg_count,
        "estimated_tokens": estimated_tokens,
        "investment_view_count": len(views),
        "tech_insight_count": len(tech_insights),
        "non_focus_count": len(non_focus),
        "entity_count": len(entities),
        "risk_count": len(risks),
        "tracking_signal_count": len(signals),
        "evidence_type_distribution": dict(evidence_counter),
        "investment_relevance_distribution": dict(relevance_counter),
        "ai_value_chain_layer_distribution": dict(ai_chain_counter),
        "topic_tags_top": top_tags,
        "generic_target_count": generic_count,
        "unknown_speaker_count": unknown_speaker_count,
        "time_horizon_distribution": dict(horizon_counter),
        "report_status": status,
    }


def eval_all_reports(channel_filter: str | None = None) -> list[dict]:
    """评估所有报告（可选按频道名过滤），返回统计列表。"""
    init_db()
    session = get_session()
    try:
        rows = (
            session.query(Report, Episode)
            .join(Episode, Report.episode_id == Episode.id)
            .order_by(Report.analysis_timestamp.desc())
            .all()
        )

        results = []
        for report, episode in rows:
            # Parse extraction JSON
            try:
                extraction = json.loads(report.extraction_json)
            except (json.JSONDecodeError, TypeError):
                extraction = {}

            # Channel name from source_info (may be empty for pre-P2-A2.1 reports)
            source_info = extraction.get("source_info", {}) or {}
            chan_name = source_info.get("channel_name", "")

            # Filter by channel name
            if channel_filter and channel_filter.lower() not in chan_name.lower():
                # Also check episode title for backwards compatibility
                if channel_filter.lower() not in episode.title.lower():
                    continue

            views = session.query(InvestmentViewRecord).filter_by(report_id=report.id).all()
            stats = compute_report_stats(report, episode, views, extraction)
            results.append(stats)

        return results
    finally:
        session.close()


# ── CSV Export ──


def export_csv(results: list[dict], output_path: Path) -> Path:
    """将评估结果导出为 CSV。"""
    if not results:
        output_path.write_text("No reports found.\n", encoding="utf-8")
        return output_path

    fieldnames = [
        "report_id", "channel_name", "video_id", "source_url",
        "prompt_version", "model", "transcript_segment_count", "estimated_tokens",
        "investment_view_count", "tech_insight_count", "non_focus_count",
        "entity_count", "risk_count", "tracking_signal_count",
        "evidence_type_distribution", "investment_relevance_distribution",
        "ai_value_chain_layer_distribution", "topic_tags_top",
        "generic_target_count", "unknown_speaker_count",
        "time_horizon_distribution", "report_status",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = dict(r)
            # Serialize dict columns as JSON
            for key in ["evidence_type_distribution", "investment_relevance_distribution",
                         "ai_value_chain_layer_distribution", "time_horizon_distribution",
                         "topic_tags_top"]:
                val = row.get(key)
                if isinstance(val, (dict, list)):
                    row[key] = json.dumps(val, ensure_ascii=False)
            writer.writerow(row)

    return output_path


# ── Markdown Summary ──


def generate_summary_md(results: list[dict]) -> str:
    """生成 Prompt v2 跨频道评估总结 Markdown。"""
    lines = [
        "# Prompt v2 Cross-channel Evaluation",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"Total reports evaluated: {len(results)}",
        "",
        "---",
        "",
        "## Overall Metrics",
        "",
    ]

    if not results:
        lines.append("No reports available for evaluation.")
        return "\n".join(lines)

    total_views = sum(r["investment_view_count"] for r in results)
    total_insights = sum(r["tech_insight_count"] for r in results)
    total_generic = sum(r["generic_target_count"] for r in results)
    total_unknown_speaker = sum(r["unknown_speaker_count"] for r in results)
    total_entities = sum(r["entity_count"] for r in results)
    reports_with_generic = sum(1 for r in results if r["generic_target_count"] > 0)

    lines.append(f"- **Reports**: {len(results)}")
    lines.append(f"- **Total investment views**: {total_views}")
    lines.append(f"- **Avg views/report**: {total_views / len(results):.1f}")
    lines.append(f"- **Total tech/industry insights**: {total_insights}")
    lines.append(f"- **Total entities**: {total_entities}")
    lines.append(f"- **Reports with generic targets**: {reports_with_generic}")
    lines.append(f"- **Total generic target views**: {total_generic}")
    lines.append(f"- **Total unknown speaker views**: {total_unknown_speaker}")
    lines.append("")

    # Channel breakdown
    channels: dict[str, list[dict]] = {}
    for r in results:
        ch = r["channel_name"] or "unknown"
        channels.setdefault(ch, []).append(r)

    if channels:
        lines.append("---")
        lines.append("")
        lines.append("## By Channel")
        lines.append("")

        for ch_name in sorted(channels.keys()):
            ch_results = channels[ch_name]
            ch_views = sum(r["investment_view_count"] for r in ch_results)
            ch_insights = sum(r["tech_insight_count"] for r in ch_results)
            ch_generic = sum(r["generic_target_count"] for r in ch_results)
            lines.append(f"### {ch_name}")
            lines.append("")
            lines.append(f"- Reports: {len(ch_results)}")
            lines.append(f"- Total views: {ch_views}")
            lines.append(f"- Tech insights: {ch_insights}")
            lines.append(f"- Generic targets: {ch_generic}")

            # Evidence distribution for channel
            all_evidence: Counter[str] = Counter()
            all_relevance: Counter[str] = Counter()
            for r in ch_results:
                for k, v in (r.get("evidence_type_distribution") or {}).items():
                    all_evidence[k] += v
                for k, v in (r.get("investment_relevance_distribution") or {}).items():
                    all_relevance[k] += v

            if all_evidence:
                lines.append("- Evidence types:")
                for et, cnt in all_evidence.most_common():
                    lines.append(f"  - {et}: {cnt}")
            if all_relevance:
                lines.append("- Investment relevance:")
                for rel, cnt in all_relevance.most_common():
                    lines.append(f"  - {rel}: {cnt}")
            lines.append("")

    # Known Issues
    lines.append("---")
    lines.append("")
    lines.append("## Known Issues")
    lines.append("")

    # Long video timeout
    long_reports = [r for r in results if r["transcript_segment_count"] > 1500]
    if long_reports:
        lines.append(f"- **Long video risk** ({len(long_reports)} reports > 1500 segments): potential token overflow")
        for r in long_reports:
            label = r["channel_name"] or r["video_id"] or f"report #{r['report_id']}"
            lines.append(f"  - {label}: {r['transcript_segment_count']} segments, ~{r['estimated_tokens']} tokens")

    # Generic targets
    if total_generic > 0:
        lines.append(f"- **Generic targets**: {total_generic} views across {reports_with_generic} reports")
        generic_reports = [r for r in results if r["generic_target_count"] > 0]
        for r in generic_reports:
            ch = r["channel_name"] or "unknown"
            lines.append(f"  - {ch} (#{r['report_id']}): {r['generic_target_count']} generic targets")

    # Evidence quality (high unsupported_claim)
    all_evidence2: Counter[str] = Counter()
    for r in results:
        for k, v in (r.get("evidence_type_distribution") or {}).items():
            all_evidence2[k] += v
    unsupported = all_evidence2.get("unsupported_claim", 0)
    if unsupported > 0:
        pct = unsupported / max(total_views, 1) * 100
        lines.append(f"- **Evidence quality**: {unsupported} unsupported_claim ({pct:.0f}% of views)")

    # Over/under extraction
    zero_view_reports = [r for r in results if r["investment_view_count"] == 0]
    if zero_view_reports:
        lines.append(f"- **Underextraction**: {len(zero_view_reports)} reports with 0 views")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append("- Review generic target detection and consider prompt hardening")
    lines.append("- Monitor evidence quality distribution across channels")
    lines.append("- Consider chunking for long videos (>1500 segments)")
    lines.append("- Track topic_tags coverage as proxy for topic signal completeness")
    lines.append("")

    return "\n".join(lines)
