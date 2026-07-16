"""P2-N.3: Knowledge Graph Quality Audit.

Scans DB + Obsidian Vault for quality issues across reports, entities,
topics, companies, claims, signals, and graph links.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from signalvault.workspace.quality_models import (
    ClaimSignalQuality,
    DuplicateFinding,
    EntityConfusionFinding,
    ExtractionDensity,
    ObsidianGraphFinding,
    QualityAuditResult,
    ReportQualityFinding,
)

logger = logging.getLogger(__name__)

# ── Normalization helpers ──────────────────────────────────────────

_COMPANY_ALIASES: dict[str, str] = {
    "google": "Alphabet", "nvidia": "NVIDIA", "nvda": "NVIDIA",
    "microsoft": "Microsoft", "msft": "Microsoft",
    "meta": "Meta", "facebook": "Meta",
    "open ai": "OpenAI", "openai": "OpenAI",
    "amazon": "Amazon", "apple": "Apple", "tesla": "Tesla",
    "tsmc": "TSMC", "broadcom": "Broadcom", "amd": "AMD",
    "intel": "Intel", "palantir": "Palantir",
}

_TOPIC_ALIASES: dict[str, str] = {
    "agent": "AI Agents", "ai agent": "AI Agents", "ai agents": "AI Agents",
    "model": "AI Models", "models": "AI Models", "ai model": "AI Models",
    "enterprise": "Enterprise AI", "enterprise saas": "Enterprise AI",
    "infrastructure": "AI Infrastructure", "ai infra": "AI Infrastructure",
    "market": "Public Markets", "capital market": "Public Markets",
    "compute": "AI Compute", "gpu supply": "AI Compute",
    "regulation": "AI Regulation", "policy": "AI Regulation",
    "economy": "Macro Economy",
    "startup": "Startup Ecosystem", "startups": "Startup Ecosystem",
    "semiconductor": "Semiconductor", "chip": "Semiconductor",
    "cybersecurity": "Cybersecurity", "cyber": "Cybersecurity",
    "llm": "LLMs", "large language model": "LLMs",
}

_NOT_COMPANY: set[str] = {
    "agent", "ai agent", "model", "market", "enterprise", "infrastructure",
    "compute", "regulation", "economy", "startup", "startups",
    "ai", "ml", "saas", "paas", "iaas", "api", "sdk", "cli",
    "cpu", "gpu", "tpu", "npu", "ram", "ssd", "hdd",
}

_NOT_TOPIC: set[str] = {
    "openai", "anthropic", "nvidia", "microsoft", "google", "alphabet",
    "meta", "amazon", "apple", "tesla", "tsmc", "broadcom", "amd",
    "intel", "salesforce", "oracle", "ibm", "palantir",
    "deepseek", "mistral", "perplexity",
}


def _norm(text: str) -> str:
    """Normalize text for comparison: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm_title(text: str) -> str:
    """Normalize a report title for dedup. Removes common prefixes/suffixes."""
    text = _norm(text)
    # Remove common prefixes
    for prefix in ["episode", "podcast", "interview"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _slug(text: str) -> str:
    """Generate a dedup slug from text (first 80 chars normalized)."""
    return _norm(text)[:80]


def _find_duplicates(items: list[dict], key_field: str, entity_type: str) -> list[DuplicateFinding]:
    """Find duplicates in a list of items by normalized key."""
    findings: list[DuplicateFinding] = []
    seen: dict[str, str] = {}
    for item in items:
        raw = str(item.get(key_field, ""))
        nk = _norm(raw)
        if nk in seen:
            findings.append(DuplicateFinding(
                entity_type=entity_type,
                entity_a=seen[nk],
                entity_b=raw,
                normalized_a=nk,
                normalized_b=nk,
                match_type="normalized",
                action="merge",
            ))
        else:
            seen[nk] = raw
    return findings


# ── Main audit entry point ─────────────────────────────────────────


def run_quality_audit(
    db_path: str | None = None,
    vault_path: str | None = None,
) -> QualityAuditResult:
    """Run the complete knowledge graph quality audit.

    Args:
        db_path: Path to SQLite DB. Uses config default if None.
        vault_path: Path to Obsidian vault. Skips Obsidian scan if None.

    Returns:
        QualityAuditResult with all findings populated.
    """
    result = QualityAuditResult()
    datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Scan DB
    _audit_db_reports(result, db_path)
    _audit_extraction_density(result, db_path)

    # 2. Scan Obsidian Vault
    if vault_path:
        vp = Path(vault_path)
        if vp.exists():
            _audit_obsidian_vault(result, vp)
            _audit_entity_hygiene(result, vp)
            _audit_claims_signals(result, vp)
            _audit_graph_integrity(result, vp)

    # 2.5 P2-N.3.2: Compute confusion breakdown
    result.entity_confusions_raw = len(result.entity_confusions)
    result.entity_confusions_active = sum(1 for e in result.entity_confusions if e.status == "active")
    result.entity_confusions_archived = sum(1 for e in result.entity_confusions if e.status == "archived")
    result.entity_confusions_resolved = sum(1 for e in result.entity_confusions if e.status == "resolved")
    result.entity_confusions_new = 0  # requires baseline comparison

    # 3. Classify root causes
    _classify_root_causes(result)

    # 4. Build fix recommendations
    _build_fix_plan(result)

    return result


# ── DB Audit ────────────────────────────────────────────────────────


def _audit_db_reports(result: QualityAuditResult, db_path: str | None) -> None:
    """Audit reports from SQLite DB."""
    try:
        from signalvault.db.models import Episode, Report
        from signalvault.db.session import get_session, init_db, reset_engine

        if db_path:
            # Reset engine so init_db rebuilds with the explicit db_path
            # (no longer mutates cfg.DB_PATH — C1-C cleanup)
            reset_engine()

        init_db(db_path)
        session = get_session()
        try:
            rows = (
                session.query(Report, Episode)
                .join(Episode, Report.episode_id == Episode.id)
                .order_by(Report.analysis_timestamp.desc())
                .all()
            )

            result.total_reports = len(rows)
            result.current_reports = len(rows)

            # Check per report
            video_id_counts: Counter[str] = Counter()
            for report, episode in rows:
                vid = episode.video_id or ""
                video_id_counts[vid] += 1

                # Metadata checks
                if not episode.source_url and vid:
                    result.report_findings.append(ReportQualityFinding(
                        report_id=report.id, video_id=vid,
                        title=episode.title or vid, channel_name="",
                        issue="缺少 source_url", severity="warning", category="metadata",
                    ))

                # Check if extraction JSON is empty
                if not report.extraction_json or len(report.extraction_json) < 100:
                    result.report_findings.append(ReportQualityFinding(
                        report_id=report.id, video_id=vid,
                        title=episode.title or vid, channel_name="",
                        issue="extraction_json 为空或过短", severity="warning", category="metadata",
                    ))

            # Duplicate video_id check
            for vid, count in video_id_counts.items():
                if count > 1 and vid:
                    dup_reports = [
                        r.id for r, _ in rows if (_.video_id or "") == vid
                    ]
                    result.duplicate_findings.append(DuplicateFinding(
                        entity_type="report",
                        entity_a=f"video_id={vid}",
                        entity_b=f"{count} reports: {dup_reports}",
                        normalized_a=vid,
                        normalized_b=vid,
                        match_type="exact",
                        action="archive" if len(dup_reports) > 1 else "keep",
                    ))
                    result.duplicate_report_ids.append(dup_reports)
                    result.blocking_issues.append(
                        f"video_id={vid}: {count} 份报告重复 (IDs: {dup_reports})"
                    )
                    for rid in dup_reports[1:]:
                        result.report_findings.append(ReportQualityFinding(
                            report_id=rid, video_id=vid,
                            title="", channel_name="",
                            issue=f"与 report_id={dup_reports[0]} 重复 (同一 video_id)",
                            severity="blocking", category="duplicate",
                        ))

        finally:
            session.close()
    except Exception as e:
        logger.warning("DB audit failed: %s", e)


def _audit_extraction_density(result: QualityAuditResult, db_path: str | None) -> None:
    """Audit extraction density per report."""
    try:
        from signalvault.db.repository import get_report_detail
        from signalvault.db.session import get_session, init_db

        init_db(db_path)
        session = get_session()
        try:
            from signalvault.db.models import Report
            report_ids = [r[0] for r in session.query(Report.id).all()]
        finally:
            session.close()

        for rid in report_ids:
            try:
                s2 = get_session()
                try:
                    detail = get_report_detail(s2, rid)
                finally:
                    s2.close()
                if not detail:
                    continue

                ex_json = detail.get("extraction_json", "")
                ex_data = {}
                if ex_json:
                    with contextlib.suppress(json.JSONDecodeError):
                        ex_data = json.loads(ex_json)

                views = detail.get("views", [])
                signals = detail.get("signals", [])
                entities = _count_unique("mentioned_entities", ex_data, [])
                topic_tags = _count_unique("topic_tags", ex_data, [])
                tech_insights = ex_data.get("tech_industry_insights", [])
                source_quotes = sum(
                    1 for i in (tech_insights if isinstance(tech_insights, list) else [])
                    if isinstance(i, dict) and i.get("source_quote")
                )
                high_rel = sum(1 for v in views if v.get("investment_relevance") == "high")

                # Density check
                is_low = False
                reasons = []
                title = detail.get("episode_title", "") or ""
                if len(views) <= 2 and len(views) < 4:
                    is_low = True
                    reasons.append(f"观点稀疏 ({len(views)}条)")
                if not ex_json or len(ex_json) < 500:
                    is_low = True
                    reasons.append("extraction_json 过短")

                density = ExtractionDensity(
                    report_id=rid,
                    video_id=detail.get("video_id", ""),
                    title=title,
                    views_count=len(views),
                    claims_count=len(views),
                    signals_count=len(signals),
                    entities_count=entities,
                    topic_tags_count=topic_tags,
                    source_quotes_count=source_quotes,
                    high_relevance_views=high_rel,
                    related_companies=0,
                    related_topics=0,
                    is_low_density=is_low,
                    low_density_reason="; ".join(reasons),
                )
                result.extraction_density.append(density)
                if is_low:
                    result.low_density_reports.append(rid)
                    result.report_findings.append(ReportQualityFinding(
                        report_id=rid, video_id=detail.get("video_id", ""),
                        title=title, channel_name="",
                        issue=f"低密度报告: {density.low_density_reason}",
                        severity="warning", category="density",
                    ))

            except Exception as e:
                logger.warning("Density audit failed for report %s: %s", rid, e)

    except Exception as e:
        logger.warning("Extraction density audit failed: %s", e)


def _count_unique(key: str, data: dict, default: Any) -> int:
    """Count unique items in a data field."""
    val = data.get(key, default)
    if isinstance(val, list):
        return len(val)
    return 0


# ── Obsidian Vault Audit ────────────────────────────────────────────


def _audit_obsidian_vault(result: QualityAuditResult, vault_path: Path) -> None:
    """Audit Obsidian vault structure."""
    from signalvault.utils.file_io import read_text_safe

    dirs = {
        "01_Reports": "report",
        "02_Topics": "topic",
        "03_Companies": "company",
        "06_Claims": "claim",
        "07_Signals": "signal",
    }

    for dir_name, card_type in dirs.items():
        d = vault_path / dir_name
        if not d.exists():
            continue
        count = len(list(d.glob("*.md")))
        if card_type == "report":
            result.total_reports = max(result.total_reports, count)
        elif card_type == "topic":
            result.total_topics = count
        elif card_type == "company":
            result.total_companies = count
        elif card_type == "claim":
            result.total_claims = count
        elif card_type == "signal":
            result.total_signals = count

        # Check for duplicate filenames (case-insensitive on Windows)
        seen: dict[str, Path] = {}
        for f in sorted(d.glob("*.md")):
            key = f.stem.lower()
            if key in seen:
                result.duplicate_findings.append(DuplicateFinding(
                    entity_type=f"{card_type}_file",
                    entity_a=str(seen[key]),
                    entity_b=str(f),
                    normalized_a=key,
                    normalized_b=key,
                    match_type="normalized",
                    action="merge",
                ))
            else:
                seen[key] = f


def _audit_entity_hygiene(result: QualityAuditResult, vault_path: Path) -> None:
    """P2-N.3.2: Check entity hygiene with raw/active/archived/resolved/new status.

    Classifies each confusion:
    - active: still present, needs fixing
    - archived: moved to backup, residual file may remain
    - resolved: canonical card exists, old file is a remnant
    - new: detected for the first time in this audit run
    """
    from signalvault.utils.file_io import read_text_safe

    backup_dir = vault_path / "99_System"
    companies_dir = vault_path / "03_Companies"
    topics_dir = vault_path / "02_Topics"

    def _in_backup(name: str) -> bool:
        for bdn in ["Topic_Consolidation_Backup", "Card_Cleanup_Backup"]:
            bd = backup_dir / bdn
            if bd.exists():
                for _ in bd.glob(f"*{name}*"):
                    return True
        return False

    def _canonical_card_exists(canonical: str, card_type: str) -> bool:
        d = topics_dir if card_type == "topic" else companies_dir
        return (d / f"{canonical}.md").exists()

    # Check Companies
    if companies_dir.exists():
        for f in companies_dir.glob("*.md"):
            name = f.stem
            name_lower = name.lower().strip()
            if name_lower in _NOT_COMPANY:
                status = "archived" if _in_backup(name) else "active"
                result.entity_confusions.append(EntityConfusionFinding(
                    name=name, current_type="company", suggested_type="topic",
                    reason="generic_name", severity="blocking", status=status,
                    source_layer="card_frontmatter",
                    source_file=str(f.relative_to(vault_path)),
                    should_count=(status == "active"),
                    suggested_action=(
                        "已备份，手动删除残余文件" if status == "archived"
                        else "运行 cleanup-cards --apply 迁移到 Topic"
                    ),
                ))
                if status == "active":
                    result.topic_company_confusions.append(f"Company→Topic: {name}")

    # Check Topics
    if topics_dir.exists():
        for f in topics_dir.glob("*.md"):
            name = f.stem
            name_lower = name.lower().strip()
            if name_lower in _NOT_TOPIC:
                status = "archived" if _in_backup(name) else "active"
                result.entity_confusions.append(EntityConfusionFinding(
                    name=name, current_type="topic", suggested_type="company",
                    reason="company_whitelist", severity="blocking", status=status,
                    source_layer="card_frontmatter",
                    source_file=str(f.relative_to(vault_path)),
                    should_count=(status == "active"),
                    suggested_action=(
                        "已备份，手动删除残余文件" if status == "archived"
                        else "运行 consolidate-topics --apply 迁移到 Company"
                    ),
                ))
                if status == "active":
                    result.topic_company_confusions.append(f"Topic→Company: {name}")
            if name_lower in _TOPIC_ALIASES:
                canonical = _TOPIC_ALIASES[name_lower]
                if name.lower() != canonical.lower():
                    if _canonical_card_exists(canonical, "topic"):
                        status = "resolved"
                        should = False
                        action = f"删除残余文件（canonical {canonical} 已存在）"
                    elif _in_backup(name):
                        status = "archived"
                        should = False
                        action = f"已在备份中（→ {canonical}）"
                    else:
                        status = "active"
                        should = True
                        action = f"运行 consolidate-topics --apply 合并 {name} → {canonical}"
                    result.entity_confusions.append(EntityConfusionFinding(
                        name=name, current_type="topic", suggested_type="topic",
                        reason=f"alias → {canonical}", severity="warning",
                        status=status, source_layer="card_frontmatter",
                        source_file=str(f.relative_to(vault_path)),
                        should_count=should, suggested_action=action,
                    ))


def _audit_claims_signals(result: QualityAuditResult, vault_path: Path) -> None:
    """Audit claim and signal quality from Obsidian vault."""
    from signalvault.utils.file_io import read_text_safe

    for card_type, dir_name in [("claim", "06_Claims"), ("signal", "07_Signals")]:
        d = vault_path / dir_name
        if not d.exists():
            continue

        for f in d.glob("*.md"):
            content = read_text_safe(f)
            slug = f.stem

            # Extract claim/signal text
            text = ""
            for line in content.split("\n"):
                if line.startswith(f"{card_type}:") or line.startswith("signal:"):
                    text = line.split(":", 1)[1].strip().strip('"')
                    break

            evidence_count = content.count("source_quote") + content.count("evidence")
            related_comp = len(re.findall(r"\[\[([^\]]+)\]\]", content))

            # Length checks
            if card_type == "claim":
                if len(text) > 350:
                    result.claim_signal_issues.append(ClaimSignalQuality(
                        entity_type="claim", slug=slug, text=text[:100],
                        issue=f"claim 过长 ({len(text)} chars)", severity="warning",
                        evidence_count=evidence_count,
                        related_company_count=related_comp,
                        related_topic_count=0,
                    ))
                elif len(text) < 30:
                    result.claim_signal_issues.append(ClaimSignalQuality(
                        entity_type="claim", slug=slug, text=text[:100],
                        issue=f"claim 过短 ({len(text)} chars)", severity="warning",
                        evidence_count=evidence_count,
                        related_company_count=related_comp,
                        related_topic_count=0,
                    ))

            if card_type == "signal" and len(text) < 20:
                result.claim_signal_issues.append(ClaimSignalQuality(
                    entity_type="signal", slug=slug, text=text[:100],
                    issue=f"signal 过短 ({len(text)} chars)", severity="warning",
                    evidence_count=evidence_count,
                    related_company_count=related_comp,
                    related_topic_count=0,
                ))

            # Evidence check
            if evidence_count == 0 and len(text) > 50:
                result.claim_signal_issues.append(ClaimSignalQuality(
                    entity_type=card_type, slug=slug, text=text[:100],
                    issue="缺少 evidence/source_quote", severity="info",
                    evidence_count=0,
                    related_company_count=related_comp,
                    related_topic_count=0,
                ))

    # Duplicate claims by normalized text
    claim_texts: dict[str, str] = {}
    for f in sorted((vault_path / "06_Claims").glob("*.md")) if (vault_path / "06_Claims").exists() else []:
        content = read_text_safe(f)
        for line in content.split("\n"):
            if line.startswith("claim:"):
                txt = _norm(line.split(":", 1)[1])
                if txt in claim_texts:
                    result.duplicate_findings.append(DuplicateFinding(
                        entity_type="claim",
                        entity_a=claim_texts[txt],
                        entity_b=f.stem,
                        normalized_a=txt,
                        normalized_b=txt,
                        match_type="normalized",
                        action="merge",
                    ))
                else:
                    claim_texts[txt] = f.stem
                break


def _audit_graph_integrity(result: QualityAuditResult, vault_path: Path) -> None:
    """Check graph integrity: orphan cards, broken links, archived leakage."""
    from signalvault.utils.file_io import read_text_safe

    # Check for orphaned cards (no source reports)
    for card_type, dir_name in [("claim", "06_Claims"), ("signal", "07_Signals")]:
        d = vault_path / dir_name
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            content = read_text_safe(f)
            if "Source Reports" not in content and "source_report" not in content.lower():
                if card_type == "claim":
                    result.orphan_claims.append(str(f))
                else:
                    result.orphan_signals.append(str(f))

    # Check Source Report links in Topic/Company cards
    for card_type, dir_name in [("topic", "02_Topics"), ("company", "03_Companies")]:
        d = vault_path / dir_name
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            content = read_text_safe(f)
            reports = re.findall(r"\[\[([^\]]+)\]\]", content)
            seen_reports: set[str] = set()
            for r in reports:
                if r in seen_reports:
                    result.obsidian_findings.append(ObsidianGraphFinding(
                        card_type=card_type, card_path=str(f),
                        issue=f"重复 Source Report 链接: {r}",
                        severity="warning",
                    ))
                    break
                seen_reports.add(r)


# ── Root Cause Classification ───────────────────────────────────────


def _classify_root_causes(result: QualityAuditResult) -> None:
    """Classify each finding by root cause."""
    rc = result.root_causes

    # Duplicates → normalization or rerun/archive
    for d in result.duplicate_findings:
        if d.entity_type == "report":
            rc["rerun_archive"] += 1
        else:
            rc["normalization"] += 1

    # Entity confusions → taxonomy or normalization
    for e in result.entity_confusions:
        if "alias" in e.reason:
            rc["normalization"] += 1
        else:
            rc["taxonomy"] += 1

    # Claim/signal issues → prompt
    for c in result.claim_signal_issues:
        if "过长" in c.issue or "过短" in c.issue:
            rc["prompt"] += 1
        else:
            rc["normalization"] += 1

    # Report findings
    for r in result.report_findings:
        if r.category == "duplicate":
            rc["rerun_archive"] += 1
        elif r.category == "density":
            rc["prompt"] += 1
        elif r.category == "sync":
            rc["sync"] += 1
        else:
            rc["sync"] += 1

    # Obsidian findings
    for _o in result.obsidian_findings:
        rc["scanner"] += 1

    # Orphans → sync
    rc["sync"] += len(result.orphan_claims) + len(result.orphan_signals)


# ── Fix Recommendations ─────────────────────────────────────────────


def _build_fix_plan(result: QualityAuditResult) -> None:
    """Build prioritized fix recommendations."""
    # Blocking: duplicates
    if result.duplicate_report_ids:
        result.blocking_issues.insert(0,
            f"发现 {len(result.duplicate_report_ids)} 组重复报告，需去重归档"
        )
        result.no_rerun_fixes.append("archive duplicate reports, keep latest per video_id")

    # Blocking: entity confusions
    tc = [e for e in result.entity_confusions if e.severity == "blocking"]
    if tc:
        result.blocking_issues.append(
            f"发现 {len(tc)} 个实体分类混淆 (Topic↔Company)"
        )
        result.no_rerun_fixes.append("run cleanup-cards + consolidate-topics to fix entity classification")

    # Low density → targeted rerun
    if result.low_density_reports:
        result.targeted_rerun_candidates = list(result.low_density_reports)
        result.warnings.append(
            f"发现 {len(result.low_density_reports)} 份低密度报告，建议 targeted rerun"
        )

    # Alias normalization
    aliases = [e for e in result.entity_confusions if "alias" in e.reason]
    if aliases:
        result.no_rerun_fixes.append(f"normalize {len(aliases)} entity/topic aliases in taxonomy.py")

    # Rebuild
    if result.obsidian_findings:
        result.rebuild_artifacts.append("rebuild topic/company cards to fix duplicate source reports")


# ── Export ──────────────────────────────────────────────────────────


def export_audit_json(result: QualityAuditResult, path: Path) -> None:
    """Export audit result as JSON."""
    data = {
        "summary": {
            "total_reports": result.total_reports,
            "current_reports": result.current_reports,
            "total_companies": result.total_companies,
            "total_topics": result.total_topics,
            "total_claims": result.total_claims,
            "total_signals": result.total_signals,
            "duplicate_report_groups": len(result.duplicate_report_ids),
            "entity_confusions_raw": result.entity_confusions_raw,
            "entity_confusions_active": result.entity_confusions_active,
            "entity_confusions_archived": result.entity_confusions_archived,
            "entity_confusions_resolved": result.entity_confusions_resolved,
            "entity_confusions_new": result.entity_confusions_new,
            "low_density_reports": len(result.low_density_reports),
            "orphan_claims": len(result.orphan_claims),
            "orphan_signals": len(result.orphan_signals),
        },
        "blocking_issues": result.blocking_issues,
        "warnings": result.warnings,
        "duplicate_findings": [
            {"type": d.entity_type, "a": d.entity_a, "b": d.entity_b, "action": d.action}
            for d in result.duplicate_findings
        ],
        "entity_confusions": [
            {"name": e.name, "current": e.current_type, "suggested": e.suggested_type,
             "reason": e.reason, "status": e.status,
             "source_layer": e.source_layer, "source_file": e.source_file,
             "archived": e.archived, "should_count": e.should_count,
             "suggested_action": e.suggested_action}
            for e in result.entity_confusions
        ],
        "low_density_reports": [
            {"report_id": d.report_id, "video_id": d.video_id, "reason": d.low_density_reason}
            for d in result.extraction_density if d.is_low_density
        ],
        "root_causes": result.root_causes,
        "no_rerun_fixes": result.no_rerun_fixes,
        "rebuild_artifacts": result.rebuild_artifacts,
        "targeted_rerun_candidates": result.targeted_rerun_candidates,
        "prompt_changes": result.prompt_changes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_audit_markdown(result: QualityAuditResult, path: Path) -> None:
    """Export audit result as Markdown report."""
    lines = [
        "# Knowledge Graph Quality Audit",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 1. Summary",
        "",
        f"- reports: {result.total_reports}",
        f"- current_reports: {result.current_reports}",
        f"- companies: {result.total_companies}",
        f"- topics: {result.total_topics}",
        f"- claims: {result.total_claims}",
        f"- signals: {result.total_signals}",
        f"- duplicate_report_groups: {len(result.duplicate_report_ids)}",
        f"- entity_confusions: {len(result.entity_confusions)}",
        f"- low_density_reports: {len(result.low_density_reports)}",
        f"- orphan_claims: {len(result.orphan_claims)}",
        f"- orphan_signals: {len(result.orphan_signals)}",
    ]

    # Blocking issues
    if result.blocking_issues:
        lines += ["", "## 2. Blocking Issues", ""]
        for b in result.blocking_issues:
            lines.append(f"- **{b}**")

    # Warnings
    if result.warnings:
        lines += ["", "## 3. Warnings", ""]
        for w in result.warnings:
            lines.append(f"- {w}")

    # Report Quality
    lines += ["", "## 4. Report Quality Findings", ""]
    if result.report_findings:
        lines.append("| report_id | video_id | issue | severity |")
        lines.append("|-----------|----------|-------|----------|")
        for f in result.report_findings:
            lines.append(f"| {f.report_id} | {f.video_id[:15]} | {f.issue[:60]} | {f.severity} |")
    else:
        lines.append("No report quality issues found.")

    # Duplicates
    if result.duplicate_findings:
        lines += ["", "## 5. Duplicate Findings", ""]
        lines.append("| type | entity_a | entity_b | action |")
        lines.append("|------|----------|----------|--------|")
        for d in result.duplicate_findings:
            lines.append(f"| {d.entity_type} | {d.entity_a[:30]} | {d.entity_b[:30]} | {d.action} |")

    # Entity hygiene
    if result.entity_confusions:
        active_count = result.entity_confusions_active
        lines += [
            "", "## 6. Entity Hygiene Findings", "",
            "| metric | count |",
            "|--------|-------|",
            f"| raw (total ever detected) | {result.entity_confusions_raw} |",
            f"| **active (needs fixing)** | **{result.entity_confusions_active}** |",
            f"| archived (in backup) | {result.entity_confusions_archived} |",
            f"| resolved (canonical exists) | {result.entity_confusions_resolved} |",
            f"| new (first-time detection) | {result.entity_confusions_new} |",
            "",
        ]
        if active_count <= 3:
            lines.append("> ✅ Active confusions <= 3, ready for next batch.")
            lines.append("")
        lines.append("| name | detected_as | suspected_as | status | source_file | should_count? | suggested_action |")
        lines.append("|------|------------|--------------|--------|-------------|---------------|------------------|")
        for e in sorted(result.entity_confusions, key=lambda x: (0 if x.should_count else 1, x.name)):
            lines.append(
                f"| {e.name} | {e.current_type} | {e.suggested_type} | {e.status} "
                f"| {e.source_file[:30]} | {e.should_count} | {e.suggested_action[:50]} |"
            )

    # Claim/Signal quality
    if result.claim_signal_issues:
        lines += ["", "## 7. Claim & Signal Quality Findings", ""]
        lines.append(f"Total issues: {len(result.claim_signal_issues)}")
        lines.append("")
        lines.append("| type | slug | issue | severity |")
        lines.append("|------|------|-------|----------|")
        for c in result.claim_signal_issues[:30]:
            lines.append(f"| {c.entity_type} | {c.slug[:40]} | {c.issue} | {c.severity} |")

    # Obsidian graph
    if result.obsidian_findings:
        lines += ["", "## 8. Obsidian Graph Findings", ""]
        lines.append("| type | path | issue |")
        lines.append("|------|------|-------|")
        for o in result.obsidian_findings[:20]:
            lines.append(f"| {o.card_type} | {o.card_path[:40]} | {o.issue[:50]} |")

    # Root causes
    lines += ["", "## 9. Root Cause Classification", ""]
    lines.append("| root_cause | count |")
    lines.append("|------------|-------|")
    for k, v in result.root_causes.items():
        lines.append(f"| {k} | {v} |")

    # Fix plan
    lines += ["", "## 10. Recommended Fix Plan", ""]

    if result.no_rerun_fixes:
        lines += ["### A. No-rerun Fixes", ""]
        for f in result.no_rerun_fixes:
            lines.append(f"- {f}")

    if result.rebuild_artifacts:
        lines += ["", "### B. Rebuild Artifacts", ""]
        for f in result.rebuild_artifacts:
            lines.append(f"- {f}")

    if result.targeted_rerun_candidates:
        lines += ["", "### C. Targeted Rerun Candidates", ""]
        lines.append(f"report_ids: {result.targeted_rerun_candidates}")

    if result.prompt_changes:
        lines += ["", "### D. Prompt Changes", ""]
        for f in result.prompt_changes:
            lines.append(f"- {f}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
