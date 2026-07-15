"""P1-C / P2-I.2 / P2-K.2.1: HTML pages + actions — /dashboard /reports /tasks /patches /search + POST actions"""

import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from signalvault.db.repository import (
    get_report_detail,
    list_reports,
)
from signalvault.db.session import get_session, init_db
from signalvault.db.unified_search import unified_search
from signalvault.utils.perf import measure_page, measure_stage

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
    cache_size=0,
)


def _get_vault_path() -> str:
    from signalvault.config_store import get_user_vault_path
    return get_user_vault_path()


def _flash(request: Request) -> dict:
    """Extract flash messages from query params: ?msg=type:content"""
    msg = request.query_params.get("msg", "")
    if ":" in msg:
        msg_type, content = msg.split(":", 1)
        if msg_type in ("success", "error"):
            return {"flash_type": msg_type, "flash_msg": content}
    return {}


def _get_session():
    init_db()
    return get_session()


def _highlight_text(text: str, query: str) -> str:
    """Wrap matching terms in <mark> tags, case-insensitive.
    Handles mixed CJK/ASCII by extracting ASCII words + CJK bigrams.
    """
    if not query or not text:
        return text

    terms: list[str] = []
    # Extract ASCII words (keep as-is)
    ascii_words = re.findall(r'[A-Za-z0-9+_-]{2,}', query)
    terms.extend(w.lower() for w in ascii_words)

    # Extract CJK characters, create overlapping 2-char bigrams
    cjk_chars = re.findall(r'[一-鿿]', query)
    for i in range(len(cjk_chars) - 1):
        terms.append(cjk_chars[i] + cjk_chars[i + 1])

    # Also add single CJK chars if only 1-2 total
    if len(cjk_chars) <= 2:
        terms.extend(cjk_chars)

    if not terms:
        return text

    # Deduplicate and sort by length descending (longer matches first)
    terms = sorted(set(terms), key=len, reverse=True)

    pattern = re.compile(
        '(' + '|'.join(re.escape(t) for t in terms) + ')',
        re.IGNORECASE,
    )
    return pattern.sub(r'<mark>\1</mark>', text)


def _render(name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    template = _env.get_template(name)
    return HTMLResponse(template.render(context), status_code=status_code)


def _batch_archive_similar(vault_path: Path, card_id: str, card_type: str, new_status: str) -> int:
    """Auto-archive cards similar to the one the user just handled.

    P2-N.4.3.2: When a user adopts/archives/watches a claim or signal,
    find all similar items in the vault and auto-archive them to prevent
    the whack-a-mole UX where another near-duplicate appears immediately.

    Returns count of auto-archived items.
    """
    from signalvault.claim_signal.review import (
        _parse_frontmatter,
        update_claim_status,
        update_signal_status,
    )
    from signalvault.utils.file_io import read_text_safe
    from signalvault.workspace.generators import _token_overlap

    # Read the source card to get its text
    dir_name = "06_Claims" if card_type == "claim" else "07_Signals"
    source_path = vault_path / dir_name / f"{card_id}.md"
    if not source_path.exists():
        return 0

    try:
        source_content = read_text_safe(source_path)
    except Exception:
        return 0
    source_fm = _parse_frontmatter(source_content)
    source_text = source_fm.get("claim", "") or source_fm.get("signal", "") or ""
    if not source_text:
        return 0

    # Scan all cards of same type for similar content
    target_dir = vault_path / dir_name
    batched = 0
    archive_status = "outdated" if card_type == "claim" else "resolved"
    note = f"auto-archived: similar to {card_id}"

    for p in sorted(target_dir.glob("*.md")):
        if p.stem == card_id:
            continue
        try:
            content = read_text_safe(p)
        except Exception:
            continue
        fm = _parse_frontmatter(content)
        # Only archive active/open cards
        current_status = fm.get("status", "")
        if card_type == "claim" and current_status not in ("active", "challenged"):
            continue
        if card_type == "signal" and current_status not in ("open",):
            continue

        other_text = fm.get("claim", "") or fm.get("signal", "") or ""
        if not other_text:
            continue

        # Check similarity
        if _token_overlap(source_text, other_text) > 0.50:
            try:
                if card_type == "claim":
                    update_claim_status(vault_path, p.stem, archive_status, note=note)
                else:
                    update_signal_status(vault_path, p.stem, archive_status, note=note)
                batched += 1
            except Exception:
                pass

    return batched


def _build_recommendations(
    pending_patches: list[dict],
    review_claims: list[dict],
    review_signals: list[dict],
    recent_reports: list[dict],
    core_topics: list[dict],
    summary: dict,
) -> list[dict]:
    """Build 1-3 priority recommendations for the 'Today' section. Rule-based, no LLM."""
    items: list[dict] = []

    # Priority 1: pending AI suggestions (first pending patch)
    for p in pending_patches[:1]:
        items.append({
            "icon": "📋", "action": "view_patch", "action_label": "查看",
            "patch_id": p["patch_id"],
            "target": p["target"],
            "text": f"AI 整理了「{p['target']}」的最新内容，建议确认后采纳",
            "reason": f"该主题已有 {next((t['claims'] for t in core_topics if t['name'] == p['target']), 0)} 条重要判断",
            "post_url": "",
        })

    # Priority 2: watching signal
    if review_signals and len(items) < 3:
        s = review_signals[0]
        signal_text = s['signal'][:70]
        items.append({
            "icon": "🔔", "action": "follow_signal", "action_label": "关注",
            "card_id": s["card_id"],
            "target": "",
            "text": f"关注：{signal_text}",
            "reason": "该信号已标记为需持续观察",
            "post_url": f"/signals/{s['card_id']}/status",
        })

    # Priority 3: active claim that needs review
    if review_claims and len(items) < 3:
        c = review_claims[0]
        claim_text = c['claim'][:120]
        items.append({
            "icon": "💡", "action": "accept_claim", "action_label": "采纳",
            "card_id": c["card_id"],
            "target": "",
            "text": f"{claim_text}",
            "reason": "来自最新报告的核心观点",
            "post_url": f"/claims/{c['card_id']}/status",
        })

    # Fallback: recent report
    if len(items) < 2 and recent_reports:
        r = recent_reports[0]
        items.append({
            "icon": "📄", "action": "view_report", "action_label": "查看",
            "card_id": "",
            "target": "",
            "text": f"阅读最新报告：{r['channel']} — {r['title'][:50]}",
            "reason": f"最新分析内容，{r['date']}",
            "post_url": "",
        })

    return items


def _enrich_recommended_with_report_ids(recs: list[dict]) -> None:
    """Look up DB report_id by video_id and add to recommended report dicts (mutates in-place)."""
    video_ids = [r.get("video_id", "") for r in recs if r.get("video_id")]
    if not video_ids:
        return
    from signalvault.db.models import Episode, Report
    session = _get_session()
    try:
        rows = (
            session.query(Report.id, Episode.video_id)
            .join(Episode, Report.episode_id == Episode.id)
            .filter(Episode.video_id.in_(video_ids))
            .order_by(Report.id.desc())
            .all()
        )
    finally:
        session.close()
    # Build map: video_id → latest report_id
    vid_to_rid: dict[str, int] = {}
    for rid, vid in rows:
        if vid not in vid_to_rid:
            vid_to_rid[vid] = rid
    for r in recs:
        vid = r.get("video_id", "")
        if vid and vid in vid_to_rid:
            r["report_id"] = vid_to_rid[vid]


def _build_dashboard_operational_context(vault_path: Path) -> dict:
    """Build lightweight operational context for the daily radar UI."""
    ingest_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    diagnostics_summary: dict = {}
    recent_ingest_jobs: list[dict] = []
    open_review_items: list[dict] = []

    session = _get_session()
    try:
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            ingest_counts = IngestJobManager.count_by_status(session=session)
            recent_ingest_jobs = IngestJobManager.list_jobs(limit=5, session=session)
        except Exception:
            ingest_counts = {}
            recent_ingest_jobs = []

        try:
            from signalvault.sources.review_items import ReviewItemManager
            review_counts = ReviewItemManager.count_by_status(session=session)
            open_review_items = ReviewItemManager.list_items(
                status="open", limit=5, session=session,
            )
        except Exception:
            review_counts = {}
            open_review_items = []

        try:
            from signalvault.diagnostics.summary import DiagnosticsCenter
            diagnostics_summary = DiagnosticsCenter.get_summary(
                session=session, vault_path=str(vault_path),
            ).to_dict()
        except Exception:
            diagnostics_summary = {}
    finally:
        session.close()

    return {
        "ingest_counts": ingest_counts,
        "review_counts": review_counts,
        "diagnostics_summary": diagnostics_summary,
        "recent_ingest_jobs": recent_ingest_jobs,
        "open_review_items": open_review_items,
    }


def _build_daily_radar_cards(
    summary: dict,
    research_brief: object,
    diagnostics_summary: dict,
    ingest_counts: dict,
    review_counts: dict,
    pending_patches: list[dict],
) -> list[dict]:
    """Create first-screen cards for non-technical dashboard scanning."""
    new_signal_count = len(getattr(research_brief, "new_signals", []) or [])
    reinforced_count = len(getattr(research_brief, "reinforced_claims", []) or [])
    needs_review_count = summary.get("needs_review", 0) or 0
    pending_ingest = ingest_counts.get("pending_preview", 0) or 0
    failed_ingest = ingest_counts.get("preview_failed", 0) or 0
    open_reviews = review_counts.get("open", 0) or 0

    return [
        {
            "label": "新增信号",
            "value": new_signal_count,
            "tone": "info" if new_signal_count else "quiet",
            "text": "新出现的观察点，适合先扫一遍。",
            "href": "#new-signals" if new_signal_count else "/sources",
            "action": "查看新增" if new_signal_count else "补充信息源",
        },
        {
            "label": "信号增强",
            "value": reinforced_count,
            "tone": "success" if reinforced_count else "quiet",
            "text": "被多份报告交叉验证的判断。",
            "href": "#reinforced-claims" if reinforced_count else "/reports",
            "action": "查看判断" if reinforced_count else "浏览报告",
        },
        {
            "label": "需要判断",
            "value": needs_review_count + len(pending_patches),
            "tone": "warning" if needs_review_count or pending_patches else "quiet",
            "text": "需要你采纳、忽略或继续观察的内容。",
            "href": "#recommendations" if needs_review_count or pending_patches else "/watchlist",
            "action": "处理建议" if needs_review_count or pending_patches else "设置关注",
        },
        {
            "label": "导入待处理",
            "value": pending_ingest + failed_ingest + open_reviews,
            "tone": "danger" if failed_ingest else (
                "warning" if pending_ingest or open_reviews else "quiet"
            ),
            "text": "信息源、审核队列和待确认内容。",
            "href": "/sources" if pending_ingest or failed_ingest else "/sources/import/new",
            "action": "处理信息源" if pending_ingest or failed_ingest else "继续导入",
        },
    ]


def _build_diagnostic_radar_card(diagnostics_summary: dict) -> dict:
    """Build a radar card for system health so diagnostics stays visible but not central."""
    diagnostics_summary = diagnostics_summary or {}
    attention = diagnostics_summary.get("attention_count", 0) or 0
    blocked = diagnostics_summary.get("blocked_count", 0) or 0
    total = attention + blocked
    overall = diagnostics_summary.get("overall_status", "ok")
    if blocked:
        tone = "danger"
        text = "核心能力可能不可用，需要先处理。"
    elif attention:
        tone = "warning"
        text = "系统基本正常，但有事项需要关注。"
    elif overall in ("ok", "success"):
        tone = "success"
        text = "摄入、搜索和知识库状态正常。"
    else:
        tone = "quiet"
        text = "暂时无法生成完整诊断摘要。"

    return {
        "label": "系统诊断",
        "value": total,
        "tone": tone,
        "text": text,
        "href": "/tasks",
        "action": "查看诊断" if total else "查看状态",
    }


def _build_today_actions(
    diagnostics_summary: dict,
    ingest_counts: dict,
    review_counts: dict,
    pending_patches: list[dict],
    recent_ingest_jobs: list[dict],
    open_review_items: list[dict],
) -> list[dict]:
    """Build action-oriented dashboard notices from existing status data."""
    actions: list[dict] = []
    pending_ingest = ingest_counts.get("pending_preview", 0) or 0
    failed_ingest = ingest_counts.get("preview_failed", 0) or 0
    open_reviews = review_counts.get("open", 0) or 0

    if failed_ingest:
        failed = [j for j in recent_ingest_jobs if j.get("status") == "preview_failed"]
        name = failed[0].get("source_name") if failed else ""
        actions.append({
            "kind": "import_failed",
            "tone": "danger",
            "title": f"{failed_ingest} 个导入预览失败",
            "body": f"先处理失败的来源{f'：{name}' if name else ''}，避免重要信息漏进知识库。",
            "href": "/sources",
            "label": "去信息源工作台",
        })

    if pending_ingest:
        actions.append({
            "kind": "import_pending",
            "tone": "warning",
            "title": f"{pending_ingest} 个导入待确认",
            "body": "这些内容已经生成预览，还需要你确认归档、跳过或改用其他方式。",
            "href": "/sources",
            "label": "继续导入",
        })

    if open_reviews:
        first = open_review_items[0] if open_review_items else {}
        actions.append({
            "kind": "review",
            "tone": "warning",
            "title": f"{open_reviews} 个审核项待处理",
            "body": first.get("title") or "包含 PDF、Vault Lint、知识星球等需要人工判断的项目。",
            "href": "/tasks",
            "label": "查看任务与诊断",
        })

    if pending_patches:
        p = pending_patches[0]
        actions.append({
            "kind": "patch",
            "tone": "info",
            "title": f"{len(pending_patches)} 个知识补丁待确认",
            "body": f"最新建议涉及「{p.get('target', '关注对象')}」，确认后再写入知识库。",
            "href": f"/patches/{p.get('patch_id')}" if p.get("patch_id") else "/patches",
            "label": "查看补丁",
        })

    overall = (diagnostics_summary or {}).get("overall_status", "ok")
    if overall in ("attention", "blocked"):
        guidance = (diagnostics_summary.get("metadata") or {}).get("user_guidance", "")
        actions.append({
            "kind": "diagnostic",
            "tone": "danger" if overall == "blocked" else "warning",
            "title": "系统诊断需要关注" if overall == "attention" else "核心能力可能不可用",
            "body": guidance or "有子系统提示异常，建议先查看诊断信息再继续导入。",
            "href": "/tasks",
            "label": "查看诊断",
        })

    return actions[:4]


def _build_dashboard_context(vault_path: Path, *, skip_briefs: bool = False) -> dict:
    """Build dashboard data from vault scan. Returns context dict or error info.

    P2-N.4.3: Uses shared system_curation and review_priority logic for consistency
    between web dashboard and Obsidian Home.

    Args:
        vault_path: Path to the Obsidian vault.
        skip_briefs: If True, skip research_brief and watchlist_brief.
            Used when briefs are loaded asynchronously.
    """
    from signalvault.workspace.scanner_cache import scan_with_cache

    with measure_stage("dashboard_scan"):
        snapshot = scan_with_cache(vault_path)

    # P2-N.4.3: Compute system_curation for topics and companies
    with measure_stage("dashboard_system_curation"):
        try:
            from signalvault.workspace.system_curation import (
                compute_company_system_curation,
                compute_topic_system_curation,
                curation_label,
            )
            from signalvault.workspace.watchlist import load_watchlist
            wl_config = load_watchlist(vault_path)
            wl_companies_set = set(wl_config.companies)
            wl_topics_set = set(wl_config.topics)
        except Exception:
            wl_config = None
            wl_companies_set = set()
            wl_topics_set = set()
            curation_label = lambda x: x  # noqa: E731

        for t in snapshot.topics:
            t.system_curation = compute_topic_system_curation(t, snapshot, wl_topics_set)
        for c in snapshot.companies:
            c.system_curation = compute_company_system_curation(c, snapshot, wl_companies_set)

    # P2-N.4.3: Compute review_priority (single pass: set attributes + accumulate stats)
    with measure_stage("dashboard_review_priority"):
        try:
            from signalvault.workspace.review_priority import (
                PRIORITY_AUTO_ACCEPTED,
                PRIORITY_CRITICAL,
                PRIORITY_HIGH,
                PRIORITY_LOW,
                compute_claim_review_priority,
                compute_signal_review_priority,
            )
            needs_review_n = 0
            auto_accepted_n = 0
            low_priority_n = 0

            for cl in snapshot.claims:
                priority = compute_claim_review_priority(
                    cl, snapshot, wl_companies_set, wl_topics_set,
                )
                cl.review_priority = priority
                if priority in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                    needs_review_n += 1
                elif priority == PRIORITY_AUTO_ACCEPTED:
                    auto_accepted_n += 1
                elif priority == PRIORITY_LOW:
                    low_priority_n += 1

            for s in snapshot.signals:
                priority = compute_signal_review_priority(
                    s, snapshot, wl_companies_set, wl_topics_set,
                )
                s.review_priority = priority
                if priority in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                    needs_review_n += 1
                elif priority == PRIORITY_AUTO_ACCEPTED:
                    auto_accepted_n += 1
                elif priority == PRIORITY_LOW:
                    low_priority_n += 1
        except Exception:
            needs_review_n = len(snapshot.active_claims()) + len(snapshot.open_signals())
            auto_accepted_n = 0
            low_priority_n = 0

    # P2-N.4.3: Priority-grouped summary instead of raw counts
    summary = {
        "reports": len(snapshot.reports),
        "topics": len(snapshot.topics),
        "core_topics": len(snapshot.core_topics()),
        "companies": len(snapshot.companies),
        "core_companies": len(snapshot.core_companies()),
        "claims": len(snapshot.claims),
        "signals": len(snapshot.signals),
        "patches": len(snapshot.llm_patches),
        "pending_patches": len(snapshot.pending_patches()),
        "channels": len(snapshot.channels),
        # P2-N.4.3: Priority-grouped (replaces active_claims/open_signals/watching_signals)
        "needs_review": needs_review_n,
        "auto_accepted": auto_accepted_n,
        "low_priority": low_priority_n,
        "tracking_signals": len(snapshot.tracking_signals()),
        # Legacy fields kept for template compatibility
        "active_claims": len(snapshot.active_claims()),
        "open_signals": len(snapshot.open_signals()),
        "watching_signals": len(snapshot.watching_signals()),
    }

    core_topics = []
    for t in sorted(snapshot.core_topics(), key=lambda x: x.name):
        sys_cur = t.system_curation or ""
        user_cur = t.curation_status or ""
        if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
            display_cur = user_cur
        elif sys_cur:
            display_cur = curation_label(sys_cur)
        else:
            display_cur = "—"
        core_topics.append({
            "name": t.name, "reports": len(t.source_reports),
            "claims": snapshot.claims_count_for(t.name),
            "signals": snapshot.signals_count_for(t.name),
            "curation": display_cur,
        })

    core_companies = []
    for c in sorted(snapshot.core_companies(), key=lambda x: x.name):
        sys_cur = c.system_curation or ""
        user_cur = c.curation_status or ""
        if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
            display_cur = user_cur
        elif sys_cur:
            display_cur = curation_label(sys_cur)
        else:
            display_cur = "—"
        core_companies.append({
            "name": c.name, "reports": len(c.source_reports),
            "claims": snapshot.claims_count_for(c.name),
            "signals": snapshot.signals_count_for(c.name),
            "curation": display_cur,
        })

    pending_patches = []
    all_pending = sorted(snapshot.pending_patches(), key=lambda x: x.generated_at, reverse=True)
    for p in all_pending[:5]:
        pending_patches.append({
            "target": p.target, "type": p.target_type,
            "generated": p.generated_at[:10] if p.generated_at else "?",
            "patch_id": p.patch_id,
        })

    from signalvault.workspace.generators import (
        _dedup_needs_review_items,
        _sort_claims_by_priority,
        _sort_signals_by_priority,
    )

    # P2-N.4.3: Show needs-review items (critical + high priority)
    try:
        needs_claims = [
            c for c in snapshot.review_claims()
            if getattr(c, 'review_priority', '') in ('critical', 'high')
        ]
        # P2-N.4.3.2: Only show "open" signals in recommendations — "watching"
        # signals have already been acknowledged by the user and should appear
        # in the tracking section, not re-occupy attention in 今日建议.
        needs_signals = [
            s for s in snapshot.review_signals()
            if getattr(s, 'review_priority', '') in ('critical', 'high')
            and s.status == "open"  # exclude already-acknowledged watching signals
        ]
        # P2-N.4.3.2: Dedup before building review lists — prevents
        # similar claims/signals (different markdown, same content)
        # from cycling through recommendations after user action.
        needs_claims_deduped = _dedup_needs_review_items(needs_claims)
        needs_signals_deduped = _dedup_needs_review_items(needs_signals)
    except Exception:
        needs_claims_deduped = snapshot.review_claims()
        needs_signals_deduped = snapshot.review_signals()

    review_claims = []
    for c in _sort_claims_by_priority(needs_claims_deduped)[:5]:
        review_claims.append({
            "card_id": c.card_id, "status": c.status,
            "claim": c.claim if c.claim else c.card_id,
            "priority": getattr(c, 'review_priority', ''),
        })

    review_signals = []
    for s in _sort_signals_by_priority(needs_signals_deduped)[:5]:
        review_signals.append({
            "card_id": s.card_id, "status": s.status,
            "signal": s.signal if s.signal else s.card_id,
            "priority": getattr(s, 'review_priority', ''),
        })

    recent_reports = []
    for r in snapshot.recent_reports(10):
        recent_reports.append({
            "filename": r.filename, "channel": r.channel or "?",
            "title": r.title or r.filename,
            "date": r.analyzed_at[:10] if r.analyzed_at else "?",
        })

    # P2-N.4.4: Use canonicalization + actionability for recommendations
    try:
        from signalvault.workspace.actionability import (
            build_actionable_recommendations,
        )
        recommendations = build_actionable_recommendations(
            snapshot, watchlist_config=wl_config, limit=3,
        )
    except Exception:
        # Fallback to old logic
        recommendations = _build_recommendations(
            pending_patches, review_claims, review_signals,
            recent_reports, core_topics, summary,
        )

    # Pre-compute canonicalize results once (shared by research_brief
    # and watchlist_brief to avoid duplicate O(n²) computation)
    _claim_groups = None
    _signal_groups = None
    _canonical_claim_views = None
    _canonical_signal_views = None
    if not skip_briefs:
        with measure_stage("dashboard_canonicalize"):
            try:
                from signalvault.workspace.canonicalize import (
                    group_duplicate_claims,
                    group_duplicate_signals,
                )
                _claim_groups = group_duplicate_claims(snapshot.claims)
                _signal_groups = group_duplicate_signals(snapshot.signals)
            except Exception:
                _claim_groups = None
                _signal_groups = None
            try:
                from signalvault.workspace.canonical_view import (
                    build_canonical_claim_views,
                    build_canonical_signal_views,
                )
                _canonical_claim_views = build_canonical_claim_views(
                    snapshot, precomputed_groups=_claim_groups,
                ) if _claim_groups is not None else None
                _canonical_signal_views = build_canonical_signal_views(
                    snapshot, precomputed_groups=_signal_groups,
                ) if _signal_groups is not None else None
            except Exception:
                _canonical_claim_views = None
                _canonical_signal_views = None

    # Build research brief (rule-based insights)
    if not skip_briefs:
        with measure_stage("dashboard_briefs"):
            try:
                from signalvault.workspace.research_brief import generate_brief
                research_brief = generate_brief(
                    snapshot, claim_groups=_claim_groups,
                )
                # Enrich recommended_reports with DB report_ids for direct linking
                if research_brief and research_brief.recommended_reports:
                    _enrich_recommended_with_report_ids(research_brief.recommended_reports)
            except Exception:
                research_brief = None

            # Build watchlist brief
            try:
                from signalvault.workspace.watchlist import (
                    ensure_watchlist_template,
                    generate_watchlist_brief,
                )
                from signalvault.workspace.watchlist import (
                    load_watchlist as _load_wl,
                )
                if wl_config is None:
                    wl_config = _load_wl(vault_path)
                watchlist_items = generate_watchlist_brief(
                    snapshot, vault_path,
                    canonical_claim_views=_canonical_claim_views,
                    canonical_signal_views=_canonical_signal_views,
                ) if (wl_config.companies or wl_config.topics) else []
                watchlist_configured = bool(wl_config.companies or wl_config.topics)
                if not watchlist_configured:
                    ensure_watchlist_template(vault_path)
            except Exception:
                watchlist_items = []
                watchlist_configured = False
    else:
        research_brief = None
        watchlist_items = []
        watchlist_configured = False

    with measure_stage("dashboard_operational_context"):
        operational = _build_dashboard_operational_context(vault_path)
    with measure_stage("dashboard_cards_actions"):
        daily_radar_cards = _build_daily_radar_cards(
            summary,
            research_brief,
            operational["diagnostics_summary"],
            operational["ingest_counts"],
            operational["review_counts"],
            pending_patches,
        )
        diagnostic_radar_card = _build_diagnostic_radar_card(
            operational["diagnostics_summary"]
        )
        today_actions = _build_today_actions(
            operational["diagnostics_summary"],
            operational["ingest_counts"],
            operational["review_counts"],
            pending_patches,
            operational["recent_ingest_jobs"],
            operational["open_review_items"],
        )

    return {
        "vault_configured": True,
        "summary": summary,
        "research_brief": research_brief,
        "watchlist_items": watchlist_items,
        "watchlist_configured": watchlist_configured,
        "recommendations": recommendations,
        "core_topics": core_topics,
        "core_companies": core_companies,
        "pending_patches": pending_patches,
        "review_claims": review_claims,
        "review_signals": review_signals,
        "recent_reports": recent_reports,
        "daily_radar_cards": daily_radar_cards,
        "diagnostic_radar_card": diagnostic_radar_card,
        "today_actions": today_actions,
        **operational,
        "error": None,
    }


# ── GET Routes ────────────────────────────────────────────────────

@router.get("/debug/perf")
def api_perf_report(request: Request):
    """Return per-stage timing stats for the last 20 requests (dev only)."""
    from signalvault.utils.perf import get_stage_report
    return JSONResponse({
        "stages": get_stage_report(),
        "note": "In-memory data, resets on restart. Development diagnostics only.",
    })


@router.get("/docs", response_class=HTMLResponse)
def page_api_docs(request: Request):
    return _render(
        "api_docs.html",
        {
            "request": request,
            "api_groups": [
                {
                    "name": "健康检查",
                    "path": "/api/health",
                    "desc": "确认服务、数据库和基础依赖是否可用。",
                },
                {
                    "name": "报告与证据",
                    "path": "/api/reports",
                    "desc": "读取已分析报告、观点、实体、信号和来源上下文。",
                },
                {
                    "name": "统一搜索",
                    "path": "/api/search",
                    "desc": "跨报告、观点、实体和信号检索可追溯证据。",
                },
                {
                    "name": "OpenAPI",
                    "path": "/openapi.json",
                    "desc": "机器可读接口定义，供调试工具或外部集成使用。",
                },
            ],
        },
    )


@router.get("/")
def page_index(request: Request):
    if _get_vault_path():
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/reports", status_code=302)


# ── P2-L.1: Vault Setup Wizard ─────────────────────────────────────


@router.get("/setup/vault")
def page_setup_vault(request: Request):
    """First-run vault setup page."""
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_path": vault_path_str,
           "vault_missing": not Path(vault_path_str).exists() if vault_path_str else True}
    ctx.update(_flash(request))
    return _render("setup_vault.html", ctx)


@router.get("/setup/browse-folder")
def api_browse_folder():
    """Open a native OS folder picker dialog and return the selected path.

    On Windows: uses PowerShell + .NET FolderBrowserDialog (always on top).
    On other platforms: falls back to tkinter subprocess.
    """
    import platform
    import subprocess
    import sys

    if platform.system() == "Windows":
        ps_script = r"""
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = "选择知识库文件夹 — 选择后点击确定"
$d.ShowNewFolderButton = $true
$d.RootFolder = "MyComputer"
if ($d.ShowDialog() -eq 'OK') {
    Write-Output $d.SelectedPath
}
"""
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
            selected = proc.stdout.strip()
            if selected:
                return JSONResponse({"path": selected, "error": None})
            elif proc.stderr.strip():
                return JSONResponse({"path": "", "error": f"对话框错误: {proc.stderr.strip()[:200]}"})
            else:
                return JSONResponse({"path": "", "error": "未选择文件夹"})
        except subprocess.TimeoutExpired:
            return JSONResponse({"path": "", "error": "选择超时"})
        except Exception as e:
            return JSONResponse({"path": "", "error": str(e)})

    # Non-Windows: try tkinter
    picker_script = """
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.lift()
root.focus_force()
path = filedialog.askdirectory(title="Select Vault Folder", mustexist=False)
root.destroy()
if path:
    print(path)
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", picker_script],
            capture_output=True, text=True, timeout=120,
        )
        selected = proc.stdout.strip()
        if selected:
            return JSONResponse({"path": selected, "error": None})
        else:
            return JSONResponse({"path": "", "error": "未选择文件夹"})
    except subprocess.TimeoutExpired:
        return JSONResponse({"path": "", "error": "选择超时"})
    except Exception as e:
        return JSONResponse({"path": "", "error": str(e)})


@router.post("/setup/vault")
def action_setup_vault(request: Request, vault_path: str = Form("")):
    """Initialize a vault at the given path."""
    path_str = vault_path.strip()
    if not path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请输入知识库目录路径", status_code=303)

    target = Path(path_str)
    if not target.is_absolute():
        return RedirectResponse(
            url="/setup/vault?msg=error:请输入完整的绝对路径", status_code=303)

    try:
        from signalvault.workspace.setup import initialize_vault
        result = initialize_vault(target)

        from signalvault.config_store import save_user_vault_path
        save_user_vault_path(target)

        created = len(result.created_dirs) + len(result.created_files)
        if result.warnings:
            return RedirectResponse(
                url=f"/dashboard?msg=success:知识库已初始化（{created} 项），{result.warnings[0]}",
                status_code=303)
        return RedirectResponse(
            url=f"/dashboard?msg=success:知识库已初始化，创建了 {created} 个目录和文件",
            status_code=303)
    except PermissionError:
        return RedirectResponse(
            url="/setup/vault?msg=error:无法在该路径创建文件，请检查权限。", status_code=303)
    except OSError as e:
        return RedirectResponse(
            url=f"/setup/vault?msg=error:无法创建目录: {e}", status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/setup/vault?msg=error:初始化失败: {e}", status_code=303)


@router.post("/setup/vault/repair")
def action_repair_vault(request: Request):
    """Repair an incomplete vault by creating missing dirs and files."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/setup/vault", status_code=302)

    target = Path(vault_path_str)
    try:
        from signalvault.workspace.setup import repair_vault
        result = repair_vault(target)
        created = len(result.created_dirs) + len(result.created_files)
        return RedirectResponse(
            url=f"/dashboard?msg=success:知识库已修复，补齐了 {created} 项缺失内容",
            status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard?msg=error:修复失败: {e}", status_code=303)


@router.get("/dashboard")
@measure_page("dashboard")
def page_dashboard(request: Request):
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": False, "vault_path": vault_path_str,
           "summary": {}, "recommendations": [], "watchlist_items": [],
           "watchlist_configured": False,
           "core_topics": [], "core_companies": [],
           "pending_patches": [], "review_claims": [], "review_signals": [], "recent_reports": [],
           "active_task_count": 0, "needs_repair": False, "missing_dirs": [],
           "missing_files": []}
    ctx.update(_flash(request))
    try:
        from signalvault.services.job_service import count_active_jobs
        ctx["active_task_count"] = count_active_jobs()
    except Exception:
        pass

    if not vault_path_str:
        return RedirectResponse(url="/setup/vault", status_code=302)

    vp = Path(vault_path_str)
    if not vp.exists():
        ctx["vault_missing"] = True
        return _render("dashboard.html", ctx)

    # Check vault health — show repair banner if structure incomplete
    try:
        from signalvault.workspace.setup import validate_vault
        health = validate_vault(vp)
        if not health.is_initialized:
            ctx["needs_repair"] = True
            ctx["missing_dirs"] = health.missing_dirs
            ctx["missing_files"] = health.missing_files
    except Exception:
        pass

    try:
        ctx.update(_build_dashboard_context(vp, skip_briefs=True))
    except Exception as e:
        ctx["error"] = str(e)
    return _render("dashboard.html", ctx)


@router.get("/dashboard/brief-fragment")
def page_dashboard_brief_fragment(request: Request):
    """Async fragment: research_brief + watchlist_brief for lazy loading."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return HTMLResponse("")
    vp = Path(vault_path_str)
    if not vp.exists():
        return HTMLResponse("")

    try:
        from signalvault.workspace.canonical_view import (
            build_canonical_claim_views,
            build_canonical_signal_views,
        )
        from signalvault.workspace.canonicalize import (
            group_duplicate_claims,
            group_duplicate_signals,
        )
        from signalvault.workspace.research_brief import generate_brief
        from signalvault.workspace.scanner_cache import scan_with_cache
        from signalvault.workspace.watchlist import (
            ensure_watchlist_template,
            generate_watchlist_brief,
        )
        from signalvault.workspace.watchlist import (
            load_watchlist as _load_wl,
        )

        snapshot = scan_with_cache(vp)
        wl_config = _load_wl(vp)

        # Pre-compute canonicalize once
        _claim_groups = group_duplicate_claims(snapshot.claims)
        _signal_groups = group_duplicate_signals(snapshot.signals)
        _canonical_claim_views = build_canonical_claim_views(
            snapshot, precomputed_groups=_claim_groups,
        )
        _canonical_signal_views = build_canonical_signal_views(
            snapshot, precomputed_groups=_signal_groups,
        )

        research_brief = generate_brief(snapshot, claim_groups=_claim_groups)
        if research_brief and research_brief.recommended_reports:
            _enrich_recommended_with_report_ids(research_brief.recommended_reports)

        watchlist_items = generate_watchlist_brief(
            snapshot, vp,
            canonical_claim_views=_canonical_claim_views,
            canonical_signal_views=_canonical_signal_views,
        ) if (wl_config.companies or wl_config.topics) else []
        watchlist_configured = bool(wl_config.companies or wl_config.topics)
        if not watchlist_configured:
            ensure_watchlist_template(vp)

        ctx: dict = {
            "request": request,
            "research_brief": research_brief,
            "watchlist_items": watchlist_items,
            "watchlist_configured": watchlist_configured,
        }
    except Exception:
        return HTMLResponse("")

    return _render("_dashboard_brief_fragment.html", ctx)


@router.get("/reports")
def page_reports(request: Request, limit: int = 50, source: str | None = None):
    session = _get_session()
    try:
        reports = list_reports(session, limit=limit, source_type=source)
    finally:
        session.close()
    from datetime import datetime, timedelta

    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    for report in reports:
        created = report.get("created_at")
        created_date = created.date() if hasattr(created, "date") else None
        if created_date == today:
            report["date_group"] = "今天"
            report["date_group_order"] = 0
        elif created_date and created_date >= week_start:
            report["date_group"] = "本周"
            report["date_group_order"] = 1
        else:
            report["date_group"] = "更早"
            report["date_group_order"] = 2

    source_options = sorted({r.get("source_type") for r in reports if r.get("source_type")})
    focus_options = sorted({
        focus
        for r in reports
        for focus in (r.get("focus_areas") or [])
        if focus
    })
    entity_options = sorted({
        (r.get("episode_title") or r.get("title") or "")
        for r in reports
        if r.get("entity_count", 0) > 0 and (r.get("episode_title") or r.get("title"))
    })[:20]

    ctx = {
        "request": request,
        "reports": reports,
        "source_options": source_options,
        "focus_options": focus_options,
        "entity_options": entity_options,
    }
    ctx.update(_flash(request))
    return _render("reports_list.html", ctx)


@router.get("/reports/{report_id}")
def page_report_detail(request: Request, report_id: int, hl: str = ""):
    session = _get_session()
    try:
        report = get_report_detail(session, report_id)
    finally:
        session.close()
    if not report:
        ctx = {"request": request, "status_code": 404, "detail": f"报告 ID={report_id} 不存在"}
        ctx.update(_flash(request))
        return _render("error.html", ctx, status_code=404)
    if hl and report.get("report_markdown"):
        report["report_markdown_highlighted"] = _highlight_text(report["report_markdown"], hl)
    else:
        report["report_markdown_highlighted"] = report.get("report_markdown", "")
    report["evidence_context"] = _build_report_evidence_context(report)
    ctx = {"request": request, "report": report, "hl": hl}
    ctx.update(_flash(request))
    return _render("report_detail.html", ctx)


def _report_has_source_document(report: dict) -> bool:
    """Check if a report has a linked SourceDocument with segments."""
    try:
        session = _get_session()
        try:
            from signalvault.db.models import Episode
            ep = session.query(Episode).filter(Episode.id == report.get("episode_id")).first()
            if ep is None or not getattr(ep, "source_doc_id", None):
                return False
            from signalvault.db.source_provenance import count_segments
            return count_segments(session, ep.source_doc_id) > 0
        finally:
            session.close()
    except Exception:
        return False


@router.get("/reports/{report_id}/transcript")
def page_report_transcript(request: Request, report_id: int):
    """Display the full original transcript for a report (bilingual if translated)."""
    session = _get_session()
    try:
        report = get_report_detail(session, report_id)
        if not report:
            ctx = {"request": request, "status_code": 404, "detail": "报告不存在"}
            ctx.update(_flash(request))
            return _render("error.html", ctx, status_code=404)

        # Find SourceDocument via Episode.source_doc_id
        from signalvault.db.models import Episode
        ep = session.query(Episode).filter(Episode.id == report.get("episode_id")).first()
        if ep is None or not getattr(ep, "source_doc_id", None):
            ctx = {"request": request, "status_code": 404, "detail": "该报告没有关联的原文材料"}
            ctx.update(_flash(request))
            return _render("error.html", ctx, status_code=404)

        from signalvault.db.source_provenance import get_segments, get_source_document

        doc = get_source_document(session, ep.source_doc_id)
        segments = get_segments(session, ep.source_doc_id)

        # Collect view timestamps for highlighting
        view_timestamps = set()
        for v in report.get("views", []):
            ts = v.get("timestamp_start", "")
            if ts:
                view_timestamps.add(ts)

        # Check if translation is needed
        needs_translation = any(
            s.get("translation_status", "not_needed") == "not_needed"
            and s.get("text_original", "").strip()
            for s in segments
        )

        ctx = {
            "request": request,
            "report": report,
            "doc": doc,
            "segments": segments,
            "view_timestamps": view_timestamps,
            "needs_translation": needs_translation,
            "segment_count": len(segments),
        }
        ctx.update(_flash(request))
        return _render("report_transcript.html", ctx)
    finally:
        session.close()


@router.post("/reports/{report_id}/translate")
def action_translate_report(request: Request, report_id: int):
    """Trigger LLM translation for a report's source segments."""
    session = _get_session()
    try:
        from signalvault.db.models import Episode
        report = get_report_detail(session, report_id)
        if not report:
            return JSONResponse({"error": "报告不存在"}, status_code=404)

        ep = session.query(Episode).filter(Episode.id == report.get("episode_id")).first()
        if ep is None or not getattr(ep, "source_doc_id", None):
            return JSONResponse({"error": "没有原文材料"}, status_code=404)

        # Get provider
        provider_name = report.get("llm_provider", "mock")
        from signalvault.analysis.pipeline import get_llm_provider
        provider = get_llm_provider(provider_name)

        from signalvault.services.translate_service import translate_segments
        result = translate_segments(session, ep.source_doc_id, provider)

        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        session.close()


@router.get("/briefs/latest")
def page_research_brief(request: Request):
    """P2-J.1: Latest Research Brief — rule-based insights from knowledge graph."""
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str),
           "brief": None}
    ctx.update(_flash(request))

    if not vault_path_str:
        return _render("research_brief.html", ctx)

    vp = Path(vault_path_str)
    if not vp.exists():
        return _render("research_brief.html", ctx)

    try:
        from signalvault.workspace.research_brief import generate_brief
        from signalvault.workspace.scanner_cache import scan_with_cache
        from signalvault.workspace.watchlist import (
            generate_watchlist_brief,
            load_watchlist,
        )

        snapshot = scan_with_cache(vp)
        brief = generate_brief(snapshot)
        ctx["brief"] = brief

        wl_config = load_watchlist(vp)
        ctx["watchlist_items"] = generate_watchlist_brief(snapshot, vp) if (
            wl_config.companies or wl_config.topics
        ) else []
    except Exception as e:
        ctx["error"] = str(e)

    return _render("research_brief.html", ctx)


@router.get("/watchlist")
def page_watchlist(request: Request):
    """P2-J.2: Watchlist Brief page."""
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str),
           "items": [], "config_exists": False}
    ctx.update(_flash(request))

    if not vault_path_str:
        return _render("watchlist.html", ctx)

    vp = Path(vault_path_str)
    if not vp.exists():
        return _render("watchlist.html", ctx)

    config_path = vp / "99_System" / "Watchlist.yaml"
    ctx["config_exists"] = config_path.exists()

    if not config_path.exists():
        from signalvault.workspace.watchlist import ensure_watchlist_template
        ensure_watchlist_template(vp)
        ctx["config_created"] = True

    try:
        from signalvault.workspace.scanner_cache import scan_with_cache
        from signalvault.workspace.watchlist import generate_watchlist_brief

        snapshot = scan_with_cache(vp)
        ctx["items"] = generate_watchlist_brief(snapshot, vp)
    except Exception as e:
        ctx["error"] = str(e)

    return _render("watchlist.html", ctx)


@router.get("/watchlist/settings")
def page_watchlist_settings(request: Request):
    """P2-J.3: Watchlist settings page — add/remove items."""
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str),
           "config": None}
    ctx.update(_flash(request))

    if not vault_path_str:
        return _render("watchlist_settings.html", ctx)

    vp = Path(vault_path_str)
    if not vp.exists():
        return _render("watchlist_settings.html", ctx)

    from signalvault.workspace.watchlist import (
        ensure_watchlist_template,
        load_watchlist,
    )
    ensure_watchlist_template(vp)
    config = load_watchlist(vp)
    ctx["config"] = config

    # Check card existence and suggestions
    try:
        from signalvault.workspace.scanner_cache import scan_with_cache
        from signalvault.workspace.watchlist import (
            get_suggested_companies,
            get_suggested_topics,
            resolve_watchlist_name,
        )
        snapshot = scan_with_cache(vp)
        known_companies = {c.name for c in snapshot.companies}
        known_topics = {t.name for t in snapshot.topics}
        ctx["known_companies"] = known_companies
        ctx["known_topics"] = known_topics
        ctx["suggested_companies"] = get_suggested_companies(snapshot)
        ctx["suggested_topics"] = get_suggested_topics(snapshot)

        # Resolve each config item
        resolved_items = []
        for name in config.companies:
            r = resolve_watchlist_name(name, "company", known_companies, known_topics)
            resolved_items.append({"name": name, "type": "company", **r})
        for name in config.topics:
            r = resolve_watchlist_name(name, "topic", known_companies, known_topics)
            resolved_items.append({"name": name, "type": "topic", **r})
        for name in config.themes:
            r = resolve_watchlist_name(name, "theme", known_companies, known_topics)
            resolved_items.append({"name": name, "type": "theme", **r})
        ctx["resolved_items"] = resolved_items
    except Exception:
        ctx["known_companies"] = set()
        ctx["known_topics"] = set()
        ctx["suggested_companies"] = []
        ctx["suggested_topics"] = []
        ctx["resolved_items"] = []

    return _render("watchlist_settings.html", ctx)


@router.post("/watchlist/settings/add")
def action_watchlist_add(request: Request, item_type: str = Form(...), name: str = Form(...)):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/watchlist/settings?msg=error:Vault 未配置", status_code=303)

    from signalvault.workspace.watchlist import add_watchlist_item
    _, msg = add_watchlist_item(Path(vault_path_str), item_type, name)
    msg_type = "success" if "已添加" in msg else "error"
    return RedirectResponse(url=f"/watchlist/settings?msg={msg_type}:{msg}", status_code=303)


@router.post("/watchlist/settings/remove")
def action_watchlist_remove(request: Request, item_type: str = Form(...), name: str = Form(...)):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/watchlist/settings?msg=error:Vault 未配置", status_code=303)

    from signalvault.workspace.watchlist import remove_watchlist_item
    _, msg = remove_watchlist_item(Path(vault_path_str), item_type, name)
    msg_type = "success" if "已移除" in msg else "error"
    return RedirectResponse(url=f"/watchlist/settings?msg={msg_type}:{msg}", status_code=303)


# ── P2-K.1: Add New Content ──────────────────────────────────────

@router.get("/content/new")
def page_content_new(request: Request):
    """P2-K.1: Add new content form page."""
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str)}
    ctx.update(_flash(request))

    # Load watchlist topics as focus suggestions
    focus_suggestions = ["AI Agents", "Enterprise AI", "AI Infrastructure",
                         "Semiconductor", "AI Applications", "Business Model"]
    if vault_path_str:
        vp = Path(vault_path_str)
        try:
            from signalvault.workspace.watchlist import load_watchlist
            config = load_watchlist(vp)
            if config.topics:
                focus_suggestions = config.topics[:6]
        except Exception:
            pass
    ctx["focus_suggestions"] = focus_suggestions
    return _render("content_new.html", ctx)


@router.post("/content/analyze")
def action_content_analyze(
    request: Request,
    youtube_url: str = Form(...),
    focus: str = Form(""),
    depth: str = Form("standard"),
    mock_mode: bool = Form(False),
    flow_mode: str = Form("full"),
):
    """Submit a YouTube URL for analysis.

    flow_mode: "full" = analyze + auto sync (full_flow), "report_only" = analysis only.
    """
    from signalvault.utils.youtube import is_youtube_url

    # Validate URL
    url = youtube_url.strip()
    if not url:
        return RedirectResponse(
            url="/content/new?msg=error:请输入 YouTube 链接", status_code=303)

    if not is_youtube_url(url):
        return RedirectResponse(
            url="/content/new?msg=error:无法识别该 YouTube 链接，请检查链接是否完整", status_code=303)

    # Parse focus areas
    focus_areas = [f.strip() for f in focus.replace("，", ",").split(",") if f.strip()]
    if not focus_areas:
        focus_areas = ["通用投资研究"]

    if depth not in ("standard", "deep"):
        depth = "standard"

    auto_sync = flow_mode not in ("report_only", "analysis")

    # Extract video ID for descriptive title
    import re as _re
    vid_match = _re.search(r"(?:v=|/)([a-zA-Z0-9_-]{11})", url)
    short_vid = vid_match.group(1)[:11] if vid_match else ""

    # Create job and start background analysis
    from signalvault.services.job_service import create_job, start_job
    job_type_label = "整理" if auto_sync else "分析"
    job_title = f"{job_type_label}: {short_vid}" if short_vid else ""
    job = create_job(
        youtube_url=url,
        focus_areas=focus_areas,
        depth=depth,
        mock=mock_mode,
        auto_sync=auto_sync,
        title=job_title,
    )
    start_job(job)
    return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)


# ── P2-K.1: Old job routes — redirect to unified /tasks ────────────


@router.get("/content/jobs/{job_id}")
def page_content_job(job_id: str):
    """Redirect to unified task detail page."""
    return RedirectResponse(url=f"/tasks/{job_id}", status_code=301)


@router.get("/content/jobs/{job_id}/status")
def api_job_status(job_id: str):
    """Delegate to unified task status API."""
    from fastapi.responses import JSONResponse

    from signalvault.services.job_service import get_job_status

    data = get_job_status(job_id)
    if data is None:
        return JSONResponse({"status": "not_found", "error": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(data)


# ── P2-K.2: Old sync job routes — redirect to unified /tasks ───────


@router.post("/reports/{report_id}/sync")
def action_reports_sync(request: Request, report_id: int):
    """Create a knowledge sync job and redirect to unified task page."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url=f"/reports/{report_id}?msg=error:知识库路径尚未配置，请检查 OBSIDIAN_VAULT_PATH。",
            status_code=303)

    vp = Path(vault_path_str)
    if not vp.exists():
        return RedirectResponse(
            url=f"/reports/{report_id}?msg=error:知识库路径不存在: {vault_path_str}",
            status_code=303)

    # Verify report exists
    session = _get_session()
    try:
        report = get_report_detail(session, report_id)
    finally:
        session.close()

    if not report:
        return RedirectResponse(
            url="/reports?msg=error:没有找到这份报告，可能已被删除或尚未生成。",
            status_code=303)

    # Create sync job
    from signalvault.services.job_service import create_sync_job, start_sync_job
    job = create_sync_job(report_id=report_id)

    # P2-M.1.2: Belt-and-suspenders — set source context if report has a video_id.
    # This allows the direct video_id writeback path to work for sync retry jobs,
    # in addition to the report_id-based fallback in start_sync_job.
    try:
        video_id = report.get("video_id")
        if video_id:
            job.video_id = video_id
            job.source_type = "channel_video"
    except Exception:
        pass

    start_sync_job(job)

    return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)


@router.get("/sync/jobs/{job_id}")
def page_sync_job(request: Request, job_id: str):
    """Redirect to unified task detail page."""
    return RedirectResponse(url=f"/tasks/{job_id}", status_code=301)


@router.get("/sync/jobs/{job_id}/status")
def api_sync_job_status(job_id: str):
    """Delegate to unified task status API."""
    from fastapi.responses import JSONResponse

    from signalvault.services.job_service import get_job_status

    data = get_job_status(job_id)
    if data is None:
        return JSONResponse({"status": "not_found", "error": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(data)


# ── P2-K.2.1: Unified Task Routes ──────────────────────────────────


@router.get("/tasks")
def page_tasks(request: Request):
    """Unified task list page — shows all recent jobs."""
    from signalvault.services.job_service import (
        _ALL_STAGES,
        JOB_TYPE_LABELS,
        _compute_elapsed,
        _now_epoch,
        list_jobs,
    )

    raw_jobs = list_jobs(limit=50)
    now = _now_epoch()
    jobs = []
    for j in raw_jobs:
        if j.status == "cleaned":
            continue  # P2-N.4.1: hide auto-cleaned failed jobs
        elapsed = _compute_elapsed(j, now)
        jobs.append({
            "job_id": j.job_id,
            "title": j.title or JOB_TYPE_LABELS.get(j.job_type, j.job_type),
            "job_type": j.job_type,
            "job_type_label": JOB_TYPE_LABELS.get(j.job_type, j.job_type),
            "status": j.status,
            "stage": j.stage,
            "stage_label": _ALL_STAGES.get(j.stage, j.stage),
            "elapsed_seconds": elapsed,
            "elapsed_display": _format_elapsed(elapsed),
            "report_id": j.report_id,
            "result_links": j.result_links,
            "created_at": j.created_at,
            "video_id": j.video_id,
        })

    ctx = {"request": request, "jobs": jobs}
    ctx.update(_build_diagnostics_center_context(jobs))
    ctx.update(_flash(request))
    return _render("task_list.html", ctx)


@router.get("/tasks/diagnostics/export")
def action_export_diagnostic_bundle():
    """Generate and download a diagnostic bundle zip."""
    import tempfile

    from signalvault.diagnostics.bundle import export_diagnostic_bundle

    tmpdir = tempfile.mkdtemp(prefix="sv_diag_")
    result = export_diagnostic_bundle(output_dir=tmpdir)

    if not result.success:
        return HTMLResponse(
            f"<h2>导出失败</h2><p>{result.error}</p><a href='/tasks'>返回诊断中心</a>",
            status_code=500,
        )

    zip_path = Path(result.bundle_path)
    return FileResponse(
        path=str(zip_path),
        filename=zip_path.name,
        media_type="application/zip",
    )


@router.get("/tasks/{job_id}")
def page_task_detail(request: Request, job_id: str):
    """Unified task detail page — renders task progress UI.

    P2-O.2.1: Passes get_job_status() so server-rendered terminal states
    have failure_kind, error_summary, completed_steps, and pending_steps.
    """
    import json as _json

    from signalvault.services.job_service import get_job, get_job_status
    job = get_job(job_id)
    status_data = get_job_status(job_id) if job else None
    ctx = {
        "request": request,
        "job_id": job_id,
        "job": job,
        "not_found": job is None,
        "status_json": _json.dumps(status_data, ensure_ascii=False) if status_data else "null",
    }
    ctx.update(_flash(request))
    return _render("task_detail.html", ctx)


@router.get("/tasks/{job_id}/status")
def api_task_status(job_id: str):
    """Unified task status JSON endpoint for polling."""
    from fastapi.responses import JSONResponse

    from signalvault.services.job_service import get_job_status

    data = get_job_status(job_id)
    if data is None:
        return JSONResponse({"status": "not_found", "error": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(data)


@router.get("/tasks/{job_id}/logs")
def page_task_logs(request: Request, job_id: str):
    """P2-M.4.1: Task event log detail page."""
    from signalvault.services.job_service import get_job, get_job_status

    job = get_job(job_id)
    if not job:
        return _render("task_logs.html", {
            "request": request, "not_found": True, "job_id": job_id,
            "job": None, "status": {}, "events": [],
        }, status_code=404)

    status = get_job_status(job_id) or {}

    ctx = {
        "request": request,
        "job_id": job_id,
        "job": job,
        "status": status,
        "events": job.events,
        "not_found": False,
    }
    ctx.update(_flash(request))
    return _render("task_logs.html", ctx)


@router.post("/tasks/{job_id}/delete")
def action_task_delete(job_id: str):
    """P2-N.4.1: Delete a task record manually."""
    from signalvault.services.job_service import delete_job
    delete_job(job_id)
    return RedirectResponse(url="/tasks?msg=info:已删除任务记录", status_code=303)


def _format_elapsed(seconds: int) -> str:
    if seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds} 秒"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} 分 {s} 秒"
    h, m = divmod(m, 60)
    return f"{h} 时 {m} 分"


def _status_label(status: str) -> str:
    return {
        "ok": "正常",
        "attention": "需关注",
        "blocked": "受阻",
        "unknown": "未知",
        "queued": "排队中",
        "running": "进行中",
        "long_running": "耗时较长",
        "stale": "无响应",
        "success": "已完成",
        "failed": "失败",
        "succeeded": "成功",
        "started": "进行中",
        "cancelled": "已取消",
    }.get(status or "", status or "未知")


def _operation_type_label(operation_type: str) -> str:
    return {
        "zsxq.groups.refresh": "刷新知识星球",
        "zsxq.topic.import": "导入星球主题",
        "zsxq.topic.analyze": "分析星球主题",
        "zsxq.sync": "同步知识星球",
        "pdf.preview": "PDF 预览",
        "pdf.extract": "PDF 解析",
        "pdf.analyze": "PDF 分析",
        "ingest.confirm": "确认导入",
        "ingest.retry": "重试导入",
        "ingest.resume": "恢复导入",
        "vault.lint": "知识库检查",
        "vault.export": "导出知识库",
        "review.accept": "采纳审核",
        "review.skip": "跳过审核",
        "review.resolve": "完成审核",
        "search.unified": "统一搜索",
        "graph.rebuild": "重建图谱",
        "system.doctor": "系统检查",
        "system.diagnostics": "系统诊断",
        "system.unknown": "系统操作",
    }.get(operation_type or "", operation_type or "系统操作")


def _diagnostics_headline(overall_status: str) -> tuple[str, str]:
    if overall_status == "blocked":
        return "有核心能力需要处理", "先处理受阻项目，再继续导入或分析。"
    if overall_status == "attention":
        return "有事项需要关注", "系统可继续使用，但建议先处理失败、待审核或配置问题。"
    return "系统运行正常", "导入、搜索、知识库和任务队列没有发现阻塞问题。"


def _build_diagnostics_center_context(jobs: list[dict]) -> dict:
    session = _get_session()
    try:
        try:
            from signalvault.diagnostics.summary import DiagnosticsCenter
            diagnostics = DiagnosticsCenter.get_summary(
                session=session,
                check_zsxq=False,
                vault_path=_get_vault_path(),
            ).to_dict()
        except Exception:
            diagnostics = {
                "overall_status": "unknown",
                "subsystems": [],
                "recent_failures": [],
                "open_review_count": 0,
                "blocked_count": 0,
                "attention_count": 0,
                "suggested_actions": [],
                "metadata": {"user_guidance": "暂时无法生成诊断摘要。"},
            }

        try:
            from signalvault.diagnostics.operation_log import OperationLogManager
            operation_logs = OperationLogManager.list_operations(limit=12, session=session)
        except Exception:
            operation_logs = []
    finally:
        session.close()

    status_counts: dict[str, int] = {}
    for job in jobs:
        status_counts[job["status"]] = status_counts.get(job["status"], 0) + 1

    active_jobs = [
        j for j in jobs
        if j["status"] in ("queued", "running", "long_running", "stale")
    ]
    failed_jobs = [j for j in jobs if j["status"] in ("failed", "stale")]

    cards = [
        {
            "label": "系统状态",
            "value": _status_label(diagnostics.get("overall_status", "unknown")),
            "tone": diagnostics.get("overall_status", "unknown"),
            "hint": diagnostics.get("metadata", {}).get("user_guidance", ""),
        },
        {
            "label": "待处理任务",
            "value": len(active_jobs),
            "tone": "info" if active_jobs else "ok",
            "hint": "正在运行、排队或无响应的任务。",
        },
        {
            "label": "失败/无响应",
            "value": len(failed_jobs) + len(diagnostics.get("recent_failures", []) or []),
            "tone": "blocked" if (
                failed_jobs or diagnostics.get("recent_failures")
            ) else "ok",
            "hint": "优先查看日志或按建议重试。",
        },
        {
            "label": "审核事项",
            "value": diagnostics.get("open_review_count", 0),
            "tone": "attention" if diagnostics.get("open_review_count", 0) else "ok",
            "hint": "来自导入、PDF、知识星球或知识库检查。",
        },
    ]

    subsystems = diagnostics.get("subsystems", []) or []
    for subsystem in subsystems:
        subsystem["status_label"] = _status_label(subsystem.get("status", "unknown"))

    for op in operation_logs:
        op["status_label"] = _status_label(op.get("status", ""))
        op["operation_label"] = _operation_type_label(op.get("operation_type", ""))

    headline, subhead = _diagnostics_headline(diagnostics.get("overall_status", "unknown"))
    return {
        "diagnostics": diagnostics,
        "diagnostics_headline": headline,
        "diagnostics_subhead": subhead,
        "diagnostics_cards": cards,
        "subsystems": subsystems,
        "operation_logs": operation_logs,
        "job_status_counts": status_counts,
        "active_jobs": active_jobs[:5],
        "failed_jobs": failed_jobs[:5],
    }


def _parse_json_object(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _build_report_evidence_context(report: dict) -> dict:
    """Build reader-facing evidence chain context from existing report records."""
    extraction = _parse_json_object(report.get("extraction_json", ""))
    source_info = extraction.get("source_info") if isinstance(extraction.get("source_info"), dict) else {}
    source_type = report.get("source_type", "local")
    source_label = _source_type_label(source_type)

    views = report.get("views", []) or []
    signals = report.get("signals", []) or []
    evidence_items: list[dict] = []

    for index, view in enumerate(views, start=1):
        quote = view.get("source_quote", "") or ""
        evidence_items.append({
            "kind": "观点",
            "index": index,
            "target": view.get("target_name", ""),
            "type_label": _entity_type_label(view.get("target_type", "")),
            "tone": view.get("view_direction", ""),
            "tone_label": _direction_label(view.get("view_direction", "")),
            "summary": view.get("logic_chain", ""),
            "evidence_detail": view.get("evidence_detail", ""),
            "risk_warning": view.get("risk_warning", ""),
            "source_quote": quote,
            "timestamp": view.get("timestamp_start", ""),
            "page_number": view.get("evidence_page"),
            "evidence_strength": view.get("evidence_strength", ""),
            "quote_support_strength": view.get("quote_support_strength", ""),
            "speaker": view.get("speaker_label", ""),
            "report_anchor": f"view-{index}",
        })

    for index, signal in enumerate(signals, start=1):
        quote = signal.get("source_quote", "") or ""
        evidence_items.append({
            "kind": "信号",
            "index": index,
            "target": signal.get("target_name", ""),
            "type_label": "",
            "tone": "signal",
            "tone_label": _signal_status_label(signal.get("status", "open")),
            "summary": signal.get("signal", ""),
            "evidence_detail": signal.get("trigger_condition", ""),
            "risk_warning": "",
            "source_quote": quote,
            "timestamp": signal.get("timestamp", ""),
            "page_number": None,
            "evidence_strength": "",
            "quote_support_strength": "",
            "speaker": "",
            "report_anchor": f"signal-{index}",
        })

    quote_count = sum(1 for item in evidence_items if item.get("source_quote"))
    location_count = sum(
        1 for item in evidence_items
        if item.get("timestamp") or item.get("page_number")
    )
    entity_count = len(extraction.get("mentioned_entities", []) or [])

    if source_type == "youtube":
        retention_note = "已保留视频链接、视频 ID、报告正文、结构化观点/信号、原文引用和时间戳；完整逐字稿未作为独立数据库条目保存。"
        location_label = "时间戳"
        source_action = "打开原视频"
    elif source_type == "pdf_upload":
        retention_note = "已保留 PDF 文件路径、报告正文、结构化观点/信号、原文引用和页码；PDF 全文本身保留在原文件，数据库不单独保存逐页全文。"
        location_label = "页码"
        source_action = "查看 PDF 路径"
    elif source_type == "zsxq_topic":
        retention_note = "已保留知识星球 topic 来源、报告正文、结构化观点/信号和原文引用；topic 正文目前通过分析结果保留关键证据，不作为全文条目单独入库。"
        location_label = "Topic"
        source_action = "打开来源"
    else:
        retention_note = "已保留来源路径、报告正文、结构化观点/信号和原文引用；完整原文是否可回看取决于本地文件或 SourceArchive 是否仍可访问。"
        location_label = "来源位置"
        source_action = "查看来源"

    source_facts = [
        {"label": "来源类型", "value": source_label},
        {"label": "原始来源", "value": report.get("source_url") or report.get("subtitle_path") or "未记录"},
        {"label": "证据定位", "value": f"{location_count} 条带{location_label}"},
        {"label": "原文引用", "value": f"{quote_count} 条可读引用"},
        {"label": "拆解条目", "value": f"{len(views)} 个观点 / {len(signals)} 个信号 / {entity_count} 个实体"},
    ]

    if report.get("subtitle_hash"):
        source_facts.append({"label": "内容指纹", "value": report.get("subtitle_hash")})

    if source_info.get("pdf_quality"):
        source_facts.append({"label": "PDF 解析质量", "value": source_info.get("pdf_quality")})
    if source_info.get("zsxq_group_name"):
        source_facts.append({"label": "星球", "value": source_info.get("zsxq_group_name")})

    return {
        "source_label": source_label,
        "source_facts": source_facts,
        "source_action": source_action,
        "retention_note": retention_note,
        "evidence_items": evidence_items,
        "quote_count": quote_count,
        "location_count": location_count,
        "entity_count": entity_count,
        "has_full_transcript": _report_has_source_document(report),
        "source_info": source_info,
    }


def _search_type_label(result_type: str) -> str:
    return {
        "report": "报告",
        "investment_view": "观点",
        "tracking_signal": "信号",
        "entity": "实体",
    }.get(result_type, "结果")


def _source_type_label(source_type: str) -> str:
    return {
        "youtube": "YouTube",
        "zsxq_topic": "知识星球",
        "pdf_upload": "PDF",
        "local": "本地文本",
        "web": "网页",
        "all": "全部来源",
    }.get(source_type or "local", source_type or "本地文本")


def _direction_label(direction: str) -> str:
    return {
        "bullish": "正向观点",
        "bearish": "谨慎/负向",
        "neutral": "中性观察",
        "all": "全部方向",
    }.get(direction or "all", direction or "全部方向")


def _signal_status_label(status: str) -> str:
    return {
        "open": "待跟踪",
        "triggered": "已触发",
        "resolved": "已收口",
        "all": "全部状态",
    }.get(status or "all", status or "全部状态")


def _entity_type_label(entity_type: str) -> str:
    return {
        "stock": "股票",
        "company": "公司",
        "topic": "主题",
        "technology": "技术",
        "person": "人物",
        "industry": "行业",
    }.get(entity_type or "", entity_type or "")


def _prepare_unified_result(result, query: str) -> dict:
    snippet = _highlight_text(result.snippet or result.source_quote or "", query)
    source_quote = _highlight_text(result.source_quote or "", query)
    matched_fields = [
        {
            "name": field,
            "label": {
                "report_markdown": "报告正文",
                "executive_summary": "摘要",
                "target_name": "关注对象",
                "logic_chain": "逻辑链",
                "source_quote": "原文证据",
                "evidence_detail": "证据细节",
                "signal": "跟踪信号",
                "trigger_condition": "触发条件",
                "name": "实体名称",
            }.get(field, field),
        }
        for field in result.matched_fields
    ]
    return {
        "result_type": result.result_type,
        "type_label": _search_type_label(result.result_type),
        "title": result.title,
        "snippet": snippet,
        "relevance_score": result.relevance_score,
        "matched_fields": matched_fields,
        "report_id": result.report_id,
        "source_type": result.source_type or "local",
        "source_label": _source_type_label(result.source_type or "local"),
        "source_path": result.source_path,
        "source_title": result.source_title,
        "timestamp": result.timestamp,
        "page_number": result.page_number,
        "source_quote": source_quote,
        "entity_name": result.entity_name,
        "entity_type": result.entity_type,
        "entity_type_label": _entity_type_label(result.entity_type),
        "view_direction": result.view_direction,
        "view_direction_label": _direction_label(result.view_direction),
        "signal_status": result.signal_status,
        "signal_status_label": _signal_status_label(result.signal_status),
    }


@router.get("/search")
def page_search(
    request: Request,
    q: str = "",
    result_type: str = "all",
    source_type: str = "all",
    view_direction: str = "all",
    signal_status: str = "all",
):
    allowed_types = {"all", "report", "investment_view", "tracking_signal", "entity"}
    allowed_sources = {"all", "youtube", "zsxq_topic", "pdf_upload", "local"}
    allowed_directions = {"all", "bullish", "bearish", "neutral"}
    allowed_signal_statuses = {"all", "open", "triggered", "resolved"}

    if result_type not in allowed_types:
        result_type = "all"
    if source_type not in allowed_sources:
        source_type = "all"
    if view_direction not in allowed_directions:
        view_direction = "all"
    if signal_status not in allowed_signal_statuses:
        signal_status = "all"

    ctx = {
        "request": request,
        "q": "",
        "results": [],
        "count": 0,
        "result_type": result_type,
        "source_type": source_type,
        "view_direction": view_direction,
        "signal_status": signal_status,
        "type_filters": [
            {"value": "all", "label": "全部"},
            {"value": "investment_view", "label": "观点"},
            {"value": "tracking_signal", "label": "信号"},
            {"value": "report", "label": "报告"},
            {"value": "entity", "label": "实体"},
        ],
        "source_filters": [
            {"value": "all", "label": "全部来源"},
            {"value": "youtube", "label": "YouTube"},
            {"value": "zsxq_topic", "label": "知识星球"},
            {"value": "pdf_upload", "label": "PDF"},
            {"value": "local", "label": "本地文本"},
        ],
        "direction_filters": [
            {"value": "all", "label": "观点方向"},
            {"value": "bullish", "label": "正向"},
            {"value": "bearish", "label": "谨慎"},
            {"value": "neutral", "label": "中性"},
        ],
        "signal_filters": [
            {"value": "all", "label": "信号状态"},
            {"value": "open", "label": "待跟踪"},
            {"value": "triggered", "label": "已触发"},
            {"value": "resolved", "label": "已收口"},
        ],
        "type_counts": {},
    }
    ctx.update(_flash(request))
    if not q.strip():
        return _render("search.html", ctx)
    ctx["q"] = q.strip()
    session = _get_session()
    try:
        result_types = None if result_type == "all" else [result_type]
        if result_type == "all" and view_direction != "all" and signal_status != "all":
            result_types = ["investment_view", "tracking_signal"]
        elif result_type == "all" and view_direction != "all":
            result_types = ["investment_view"]
        elif result_type == "all" and signal_status != "all":
            result_types = ["tracking_signal"]
        raw_results = unified_search(
            session,
            q.strip(),
            result_types=result_types,
            source_type=source_type,
            view_direction=view_direction,
            signal_status=signal_status,
            limit=40,
        )
        prepared = [_prepare_unified_result(r, q.strip()) for r in raw_results]
        counts = {"all": len(prepared)}
        for item in prepared:
            counts[item["result_type"]] = counts.get(item["result_type"], 0) + 1
        ctx["results"] = prepared
        ctx["count"] = len(prepared)
        ctx["type_counts"] = counts
    finally:
        session.close()
    return _render("search.html", ctx)


# ── Patch pages ───────────────────────────────────────────────────

@router.get("/patches")
def page_patches(request: Request):
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str),
           "patches": [], "vault_path": vault_path_str}
    ctx.update(_flash(request))

    if not vault_path_str:
        return _render("patches_list.html", ctx)

    vp = Path(vault_path_str)
    if not vp.exists():
        return _render("patches_list.html", ctx)

    patches_dir = vp / "00_Inbox" / "LLM_Patches"
    if patches_dir.exists():
        from signalvault.claim_signal.review import _parse_frontmatter
        patches = []
        for p in sorted(patches_dir.glob("*.md"), reverse=True):
            try:
                content = p.read_text(encoding="utf-8")
                fm = _parse_frontmatter(content)

                # Fallback for patches without frontmatter (mock patches)
                target = fm.get("target", "")
                target_type = fm.get("target_type", "")
                status = fm.get("status", "")

                if not target:
                    # Try to extract from H1: "# Patch Proposal: TargetName"
                    for line in content.split("\n"):
                        if line.startswith("# ") and "Patch Proposal:" in line:
                            target = line.split("Patch Proposal:", 1)[-1].strip()
                            break
                    if not target:
                        target = p.stem

                if not target_type:
                    # Guess from filename
                    target_type = "topic" if p.stem.startswith("topic_") else "company"

                if not status:
                    status = "unknown"

                patches.append({
                    "patch_id": p.stem,
                    "target": target,
                    "target_type": target_type,
                    "status": status,
                    "generated_at": fm.get("generated_at", "")[:10],
                    "target_card": fm.get("target_card", ""),
                })
            except Exception:
                continue
        ctx["patches"] = patches
    return _render("patches_list.html", ctx)


@router.get("/patches/{patch_id}")
def page_patch_detail(request: Request, patch_id: str):
    vault_path_str = _get_vault_path()
    ctx = {"request": request, "vault_configured": bool(vault_path_str),
           "patch_id": patch_id, "not_found": False, "patch": None}
    ctx.update(_flash(request))

    if not vault_path_str:
        return _render("patch_detail.html", ctx)

    patch_path = Path(vault_path_str) / "00_Inbox" / "LLM_Patches" / f"{patch_id}.md"
    if not patch_path.exists():
        ctx["not_found"] = True
        return _render("patch_detail.html", ctx, status_code=404)

    from signalvault.claim_signal.review import _parse_frontmatter
    content = patch_path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)

    # Extract body below frontmatter
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            body = content[end + 3:]

    ctx["patch"] = {
        "patch_id": patch_id,
        "target": fm.get("target", ""),
        "target_type": fm.get("target_type", ""),
        "target_card": fm.get("target_card", ""),
        "status": fm.get("status", ""),
        "generated_at": fm.get("generated_at", ""),
        "provider": fm.get("provider", ""),
        "model": fm.get("model", ""),
        "source_reports": fm.get("source_reports", []),
        "body": body,
    }
    return _render("patch_detail.html", ctx)


# ── POST Actions ──────────────────────────────────────────────────

@router.post("/dashboard/actions/refresh-workspace")
def action_refresh_workspace(request: Request):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/dashboard?msg=error:Vault 未配置", status_code=303)

    vp = Path(vault_path_str)
    try:
        from signalvault.workspace import (
            backfill_relations,
            polish_report_metadata,
            refresh_curation_status,
            refresh_workspace,
        )
        r1 = backfill_relations(vp, dry_run=False, apply=True)
        r2 = refresh_curation_status(vp, dry_run=False)
        r3 = polish_report_metadata(vp, dry_run=False, apply=True)
        refresh_workspace(vp, dry_run=False)

        t_added = r1["stats"].get("topics_added", 0) + r1["stats"].get("companies_added", 0)
        c_updated = r2["stats"].get("topics_updated", 0) + r2["stats"].get("companies_updated", 0)
        m = f"relations +{t_added}, curation {c_updated} updated, metadata {r3['stats'].get('titles_updated',0)} titles"
        return RedirectResponse(url=f"/dashboard?msg=success:工作区已刷新 — {m}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/dashboard?msg=error:刷新失败 — {e}", status_code=303)


@router.post("/patches/{patch_id}/apply")
def action_patch_apply(request: Request, patch_id: str):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/patches?msg=error:Vault 未配置", status_code=303)

    vp = Path(vault_path_str)
    try:
        from signalvault.llm_wiki.applier import apply_patch
        patch_rel = f"00_Inbox/LLM_Patches/{patch_id}.md"
        patch_path = vp / patch_rel
        if not patch_path.exists():
            return RedirectResponse(url=f"/patches?msg=error:Patch 不存在: {patch_id}", status_code=303)
        apply_patch(vault_path=vp, patch_rel_path=patch_rel, dry_run=False, confirm_reviewed=True)
        return RedirectResponse(url=f"/patches/{patch_id}?msg=success:已应用 Patch 到目标卡片", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/patches/{patch_id}?msg=error:Apply 失败 — {e}", status_code=303)


@router.post("/patches/{patch_id}/reject")
def action_patch_reject(request: Request, patch_id: str, reason: str = Form("")):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/patches?msg=error:Vault 未配置", status_code=303)

    vp = Path(vault_path_str)
    try:
        from signalvault.llm_wiki.rollback import reject_patch
        patch_path = vp / "00_Inbox" / "LLM_Patches" / f"{patch_id}.md"
        if not patch_path.exists():
            return RedirectResponse(url=f"/patches?msg=error:Patch 不存在: {patch_id}", status_code=303)
        reject_patch(vault_path=vp, patch_path=patch_path, reason=reason or None)
        return RedirectResponse(url=f"/patches/{patch_id}?msg=success:已拒绝 Patch", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/patches/{patch_id}?msg=error:Reject 失败 — {e}", status_code=303)


@router.post("/claims/{claim_id}/status")
def action_claim_status(request: Request, claim_id: str, status: str = Form(...),
                         note: str = Form(""), return_to: str = Form("dashboard")):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/dashboard?msg=error:Vault 未配置", status_code=303)

    vp = Path(vault_path_str)
    VALID = {"active", "verified", "challenged", "outdated", "archived"}
    if status not in VALID:
        return RedirectResponse(url=f"/dashboard?msg=error:无效状态: {status}", status_code=303)

    try:
        from signalvault.claim_signal.review import update_claim_status
        ok = update_claim_status(vp, claim_id, status, note=note)
        if not ok:
            return RedirectResponse(url=f"/dashboard?msg=error:Claim 不存在: {claim_id}", status_code=303)
        # P2-N.4.3.2: Batch archive similar claims to prevent whack-a-mole
        batched = _batch_archive_similar(vp, claim_id, "claim", status)
        msg = f"Claim 状态已更新为 {status}"
        if batched > 0:
            msg += f"，同时自动归档了 {batched} 条相似判断"
        anchor = "#recommendations" if return_to == "dashboard" else ""
        target = "/dashboard" if return_to == "dashboard" else "/patches"
        return RedirectResponse(url=f"{target}?msg=success:{msg}{anchor}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/dashboard?msg=error:更新失败 — {e}", status_code=303)


@router.post("/signals/{signal_id}/status")
def action_signal_status(request: Request, signal_id: str, status: str = Form(...),
                          note: str = Form(""), return_to: str = Form("dashboard")):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/dashboard?msg=error:Vault 未配置", status_code=303)

    vp = Path(vault_path_str)
    VALID = {"open", "watching", "resolved", "invalidated", "archived"}
    if status not in VALID:
        return RedirectResponse(url=f"/dashboard?msg=error:无效状态: {status}", status_code=303)

    try:
        from signalvault.claim_signal.review import update_signal_status
        ok = update_signal_status(vp, signal_id, status, note=note)
        if not ok:
            return RedirectResponse(url=f"/dashboard?msg=error:Signal 不存在: {signal_id}", status_code=303)
        # P2-N.4.3.2: Batch archive similar signals to prevent whack-a-mole
        batched = _batch_archive_similar(vp, signal_id, "signal", status)
        msg = f"Signal 状态已更新为 {status}"
        if batched > 0:
            msg += f"，同时自动归档了 {batched} 条相似信号"
        anchor = "#recommendations" if return_to == "dashboard" else ""
        target = "/dashboard" if return_to == "dashboard" else "/patches"
        return RedirectResponse(url=f"{target}?msg=success:{msg}{anchor}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/dashboard?msg=error:更新失败 — {e}", status_code=303)


# ═════════════════════════════════════════════════════════════════════════════
# P2-S.3.4: Unified Source Ingestion Dashboard
# ═════════════════════════════════════════════════════════════════════════════


def _build_sources_dashboard_context(vault_path_str: str) -> dict:
    """Build context for the /sources unified dashboard.

    Gathers counts and status for all four source ingestion entry points.
    Returns a dict suitable for template rendering — no writes.
    """
    from datetime import datetime

    from signalvault.db.repository import (
        list_channels,
        list_tracked_source_entries,
        list_tracked_sources,
    )
    from signalvault.db.session import get_session, init_db

    vp = Path(vault_path_str)
    now = datetime.now()

    # ── YouTube Channels ────────────────────────────────────────────────
    channel_count = 0
    channel_last_refreshed: str | None = None
    channel_new_count = 0
    try:
        init_db()
        session = get_session()
        try:
            channels = list_channels(session, active_only=True)
            channel_count = len(channels)
            if channels:
                latest = max(
                    (c.get("last_refreshed_at") for c in channels
                     if c.get("last_refreshed_at")),
                    default=None,
                )
                if latest:
                    channel_last_refreshed = _format_relative_time(latest, now)
            # Count new videos across all channels
            for ch in channels:
                channel_new_count += sum(
                    cnt for st, cnt in ch.get("video_counts", {}).items()
                    if st == "new"
                )
        finally:
            session.close()
    except Exception:
        pass

    # ── Tracked External Sources ────────────────────────────────────────
    tracked_count = 0
    tracked_pending_entries = 0
    tracked_failed_entries = 0
    try:
        init_db()
        session = get_session()
        try:
            sources = list_tracked_sources(session, enabled_only=True)
            tracked_count = len(sources)
            for ts in sources:
                entries = list_tracked_source_entries(
                    session, ts["id"], status_filter="preview_ready",
                )
                tracked_pending_entries += len(entries)
                failed = list_tracked_source_entries(
                    session, ts["id"], status_filter="failed",
                )
                tracked_failed_entries += len(failed)
        finally:
            session.close()
    except Exception:
        pass

    # ── URL Import Previews ─────────────────────────────────────────────
    # P3-A: Memory store is primary (dual-write phase). ingest_jobs augments
    # for restart recovery — after restart, memory stores are empty, so we
    # fall back to ingest_jobs counts.
    url_preview_count = len(_preview_store)
    if url_preview_count == 0:
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            url_counts = IngestJobManager.count_by_status(source_type="url_import")
            url_preview_count = url_counts.get("pending_preview", 0)
        except Exception:
            pass

    # ── File Upload Previews ────────────────────────────────────────────
    file_preview_count = len(_file_preview_store)
    if file_preview_count == 0:
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            file_counts = IngestJobManager.count_by_status(source_type="file_upload")
            file_preview_count = file_counts.get("pending_preview", 0)
        except Exception:
            pass

    # ── SourceArchive Stats ─────────────────────────────────────────────
    archive_file_count = 0
    if vp.exists():
        archive_dir = vp / "01_Reports" / "SourceArchive"
        if archive_dir.exists():
            archive_file_count = len(list(archive_dir.glob("*.md")))

    # ── Compose entry cards ─────────────────────────────────────────────
    entry_cards = [
        {
            "key": "youtube",
            "title": "YouTube 频道",
            "icon": "TV",
            "description": "长期跟踪 YouTube 频道，自动发现新视频并分析导入。",
            "count_label": f"{channel_count} 个频道",
            "count_detail": (
                f"{channel_new_count} 个新视频待处理" if channel_new_count > 0
                else "暂无新视频"
            ),
            "status": "active" if channel_count > 0 else "empty",
            "status_text": (
                f"最近刷新: {channel_last_refreshed}" if channel_last_refreshed
                else "尚未添加频道"
            ),
            "action_url": "/sources/channels",
            "action_label": "管理频道",
        },
        {
            "key": "url_import",
            "title": "网页导入",
            "icon": "URL",
            "description": "粘贴任意网页 URL，解析内容后由你决定导入方式。",
            "count_label": (
                f"{url_preview_count} 个待确认预览" if url_preview_count > 0
                else "无待处理预览"
            ),
            "status": "active" if url_preview_count > 0 else "idle",
            "status_text": (
                "有预览等待确认" if url_preview_count > 0
                else "导入新网页"
            ),
            "action_url": "/sources/import",
            "action_label": "导入网页",
        },
        {
            "key": "tracked",
            "title": "固定信息源",
            "icon": "PIN",
            "description": "跟踪固定外部网页源（如 All-In Podcast 笔记），自动发现新条目。",
            "count_label": f"{tracked_count} 个信息源",
            "count_detail": (
                f"{tracked_pending_entries} 条待确认"
                if tracked_pending_entries > 0 else ""
            ),
            "status": (
                "warning" if tracked_failed_entries > 0
                else "active" if tracked_count > 0
                else "empty"
            ),
            "status_text": (
                f"{tracked_failed_entries} 条解析失败" if tracked_failed_entries > 0
                else "已跟踪" if tracked_count > 0
                else "尚未添加固定信息源"
            ),
            "action_url": "/sources/tracked",
            "action_label": "管理信息源",
        },
        {
            "key": "file_upload",
            "title": "上传文件",
            "icon": "FILE",
            "description": "上传 .md / .txt / .html / .htm 文本文件，提取内容后归档。",
            "count_label": (
                f"{file_preview_count} 个待确认预览" if file_preview_count > 0
                else "无待处理预览"
            ),
            "status": "active" if file_preview_count > 0 else "idle",
            "status_text": (
                "有预览等待确认" if file_preview_count > 0
                else "上传新文件"
            ),
            "action_url": "/sources/files/import",
            "action_label": "上传文件",
        },
    ]

    pdf_review_count = 0
    zsxq_review_count = 0
    try:
        from signalvault.sources.review_items import ReviewItemManager
        review_items = ReviewItemManager.list_items(status="open", limit=200)
        pdf_review_count = sum(
            1 for i in review_items
            if str(i.get("item_type", "")).startswith("pdf_")
        )
        zsxq_review_count = sum(
            1 for i in review_items
            if str(i.get("item_type", "")).startswith("zsxq_")
        )
    except Exception:
        pass

    source_lanes = [
        {
            "key": "youtube",
            "label": "YouTube / 播客视频",
            "summary": "适合长期跟踪公开频道，从字幕中提取投资观点、标的、风险和信号。",
            "state": "有新视频" if channel_new_count else (
                "已连接" if channel_count else "未添加"
            ),
            "metric": f"{channel_count} 个频道",
            "detail": (
                f"{channel_new_count} 个新视频待处理"
                if channel_new_count else "没有新视频等待处理"
            ),
            "href": "/sources/channels",
            "action": "管理频道",
            "tone": "warning" if channel_new_count else (
                "active" if channel_count else "empty"
            ),
        },
        {
            "key": "web",
            "label": "网页 / 研究文章",
            "summary": "适合单篇文章、播客笔记、研究页面；先生成预览，再决定归档方式。",
            "state": "待确认" if url_preview_count else "可导入",
            "metric": f"{url_preview_count} 个预览",
            "detail": "普通网页默认归档为资料，不自动生成投资报告。",
            "href": "/sources/import",
            "action": "粘贴网页",
            "tone": "warning" if url_preview_count else "idle",
        },
        {
            "key": "tracked",
            "label": "固定跟踪源",
            "summary": "适合反复更新的外部页面；刷新后批量确认新条目。",
            "state": "有失败" if tracked_failed_entries else (
                "待确认" if tracked_pending_entries else (
                    "已跟踪" if tracked_count else "未添加"
                )
            ),
            "metric": f"{tracked_count} 个来源",
            "detail": (
                f"{tracked_pending_entries} 条待确认，{tracked_failed_entries} 条失败"
                if tracked_pending_entries or tracked_failed_entries
                else "没有跟踪源待处理"
            ),
            "href": "/sources/tracked",
            "action": "管理跟踪源",
            "tone": "danger" if tracked_failed_entries else (
                "warning" if tracked_pending_entries else (
                    "active" if tracked_count else "empty"
                )
            ),
        },
        {
            "key": "file",
            "label": "本地文件 / PDF",
            "summary": "文本文件可在 Web 归档；PDF 已具备分析能力，当前主要通过 CLI 保留页码证据。",
            "state": "需审核" if pdf_review_count else (
                "待确认" if file_preview_count else "可上传"
            ),
            "metric": f"{archive_file_count} 份已归档",
            "detail": (
                f"{file_preview_count} 个文件预览待确认"
                if file_preview_count else (
                    f"{pdf_review_count} 个 PDF 审核项"
                    if pdf_review_count else "Web 支持 .md/.txt/.html/.htm 上传"
                )
            ),
            "href": "/sources/files/import",
            "action": "上传文件",
            "tone": "warning" if file_preview_count or pdf_review_count else "idle",
        },
        {
            "key": "zsxq",
            "label": "知识星球",
            "summary": "只读导入已订阅星球主题，可进入分析 pipeline；当前 Web 提供能力说明和状态提示。",
            "state": "需审核" if zsxq_review_count else "CLI 可用",
            "metric": f"{zsxq_review_count} 个审核项",
            "detail": "不会发布、评论、点赞或修改知识星球内容。",
            "href": "/sources/zsxq",
            "action": "导入知识星球",
            "tone": "warning" if zsxq_review_count else "idle",
        },
    ]

    import_choices = [
        {
            "label": "我有一个网页链接",
            "description": "文章、播客笔记、研报网页、公司公告页面。",
            "href": "/sources/import",
            "cta": "粘贴 URL",
        },
        {
            "label": "我有本地文本文件",
            "description": ".md / .txt / .html / .htm，先预览再归档。",
            "href": "/sources/files/import",
            "cta": "上传文件",
        },
        {
            "label": "我要长期跟踪来源",
            "description": "YouTube 频道或固定网页源，适合反复更新的信息。",
            "href": "/sources/channels",
            "cta": "设置跟踪",
        },
        {
            "label": "我要处理待确认项",
            "description": "继续上次生成的预览、失败条目或审核项。",
            "href": "/sources",
            "cta": "查看待处理",
        },
    ]

    # ── Pending summary ─────────────────────────────────────────────────
    pending_items: list[dict] = []
    if url_preview_count > 0:
        pending_items.append({
            "type": "url_preview",
            "label": f"{url_preview_count} 个网页导入预览待确认",
            "url": "/sources/import",
        })
    if tracked_pending_entries > 0:
        pending_items.append({
            "type": "tracked_entries",
            "label": f"{tracked_pending_entries} 条跟踪源条目待处理",
            "url": "/sources/tracked",
        })
    if file_preview_count > 0:
        pending_items.append({
            "type": "file_preview",
            "label": f"{file_preview_count} 个文件导入预览待确认",
            "url": "/sources/files/import",
        })
    if tracked_failed_entries > 0:
        pending_items.append({
            "type": "failed",
            "label": f"{tracked_failed_entries} 条导入失败",
            "url": "/sources/tracked",
        })

    return {
        "vault_configured": True,
        "vault_path": vault_path_str,
        "entry_cards": entry_cards,
        "source_lanes": source_lanes,
        "import_choices": import_choices,
        "pending_items": pending_items,
        "pending_total": len(pending_items),
        "archive_file_count": archive_file_count,
        "channel_count": channel_count,
        "tracked_count": tracked_count,
        "url_preview_count": url_preview_count,
        "file_preview_count": file_preview_count,
    }


def _build_import_center_context(vault_path_str: str) -> dict:
    """Build import center choices without changing ingestion behavior."""
    ctx = _build_sources_dashboard_context(vault_path_str)
    ctx["import_sources"] = [
        {
            "key": "youtube",
            "title": "YouTube 视频",
            "subtitle": "从频道候选池或视频字幕进入分析",
            "status": "Web 已支持",
            "body": "适合公开投资长视频、播客字幕。系统会提取观点、标的、风险、信号和原文时间戳。",
            "steps": ["添加或刷新频道", "筛选新视频", "生成投资报告"],
            "primary_url": "/sources/channels",
            "primary_label": "管理 YouTube",
            "secondary": "已有频道会显示新视频候选池。",
            "tone": "active",
        },
        {
            "key": "zsxq",
            "title": "知识星球",
            "subtitle": "只读导入已订阅星球主题",
            "status": "Web 已接入",
            "body": "适合导入指定 group/topic 的长帖、讨论和附件元数据。不会发布、评论、点赞或修改星球内容。",
            "steps": ["检查登录状态", "选择 group/topic", "导入或进入分析"],
            "primary_url": "/sources/zsxq",
            "primary_label": "导入知识星球",
            "secondary": "读取依赖本机 zsxq-cli 登录状态。",
            "tone": "active",
        },
        {
            "key": "web",
            "title": "网页链接",
            "subtitle": "文章、播客笔记、研究页面",
            "status": "Web 已支持",
            "body": "粘贴 URL 后先解析预览，系统检测重复并推荐归档、关联精读笔记或跳过。",
            "steps": ["粘贴 URL", "查看预览和冲突", "确认写入"],
            "primary_url": "/sources/import",
            "primary_label": "粘贴网页",
            "secondary": "普通网页默认归档为资料，不自动生成投资报告。",
            "tone": "active",
        },
        {
            "key": "tracked",
            "title": "固定信息源",
            "subtitle": "反复更新的外部网页源",
            "status": "Web 已支持",
            "body": "适合 All-In 中文笔记等固定来源。刷新后发现新条目，支持批量预览和确认导入。",
            "steps": ["添加跟踪源", "刷新发现新条目", "批量确认导入"],
            "primary_url": "/sources/tracked",
            "primary_label": "管理固定源",
            "secondary": "不支持的 URL 可改用单网页导入。",
            "tone": "active",
        },
        {
            "key": "file",
            "title": "文件导入",
            "subtitle": "文本文件、HTML、PDF 研报",
            "status": "文本 / PDF Web 已支持",
            "body": "Web 支持 .md/.txt/.html/.htm 预览归档；PDF 可直接上传、预览、提取并分析，保留页码证据。",
            "steps": ["上传或选择文件", "预览提取质量", "归档或进入分析"],
            "primary_url": "/sources/files/import",
            "primary_label": "上传文件 / PDF",
            "secondary": "普通文本默认归档；PDF 确认后进入分析流水线。",
            "tone": "active",
        },
    ]
    return ctx


def _build_zsxq_context(vault_path_str: str) -> dict:
    """Build ZSXQ Web import context from existing registry/diagnostics."""
    groups = []
    cli_status = {
        "available": False,
        "version": "",
        "logged_in": False,
        "error": "未检查",
    }
    diagnostics = {}
    recent_jobs: list[dict] = []
    open_reviews: list[dict] = []

    try:
        from signalvault.sources.zsxq_cli import check_cli
        cli_status = check_cli()
    except Exception as e:
        cli_status = {
            "available": False,
            "version": "",
            "logged_in": False,
            "error": str(e)[:200],
        }

    try:
        from signalvault.sources.zsxq_registry import list_registry
        groups = [
            {
                "group_id": g.group_id,
                "group_name": g.group_name,
                "access_status": g.access_status,
                "topic_count": g.topic_count,
                "last_refreshed_at": g.last_refreshed_at[:19] if g.last_refreshed_at else "",
            }
            for g in list_registry()
        ]
    except Exception:
        groups = []

    session = _get_session()
    try:
        try:
            from signalvault.diagnostics.summary import DiagnosticsCenter
            summary = DiagnosticsCenter.get_summary(
                session=session, check_zsxq=False, vault_path=vault_path_str,
            ).to_dict()
            diagnostics = next(
                (s for s in summary.get("subsystems", []) if s.get("name") == "zsxq"),
                {},
            )
        except Exception:
            diagnostics = {}

        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            recent_jobs = IngestJobManager.list_jobs(
                source_type="zsxq_topic", limit=8, session=session,
            )
        except Exception:
            recent_jobs = []

        try:
            from signalvault.sources.review_items import ReviewItemManager
            open_reviews = [
                item for item in ReviewItemManager.list_items(
                    status="open", limit=20, session=session,
                )
                if str(item.get("item_type", "")).startswith("zsxq_")
            ][:6]
        except Exception:
            open_reviews = []
    finally:
        session.close()

    return {
        "vault_configured": True,
        "vault_path": vault_path_str,
        "cli_status": cli_status,
        "groups": groups,
        "diagnostics": diagnostics,
        "recent_jobs": recent_jobs,
        "open_reviews": open_reviews,
    }


def _write_review_findings(findings: list[dict]) -> int:
    if not findings:
        return 0
    try:
        from signalvault.sources.review_items import ReviewItemManager
        return ReviewItemManager.create_from_lint_findings(findings)
    except Exception:
        return 0


def _format_relative_time(dt, now) -> str:
    """Format a datetime as a relative human-readable string in Chinese."""
    if not dt:
        return ""
    diff = now - dt if hasattr(dt, 'replace') else now - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{int(seconds / 60)} 分钟前"
    elif seconds < 86400:
        return f"{int(seconds / 3600)} 小时前"
    elif seconds < 604800:
        return f"{int(seconds / 86400)} 天前"
    else:
        return dt.strftime("%m-%d %H:%M") if hasattr(dt, 'strftime') else str(dt)[:16]


@router.get("/sources")
def page_sources_dashboard(request: Request):
    """P2-S.3.4: Unified source ingestion dashboard."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    ctx = _build_sources_dashboard_context(vault_path_str)
    ctx["request"] = request
    ctx.update(_flash(request))
    return _render("sources_dashboard.html", ctx)


@router.get("/sources/import/new")
def page_import_center(request: Request):
    """Guided import center for all source types."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    ctx = _build_import_center_context(vault_path_str)
    ctx["request"] = request
    ctx.update(_flash(request))
    return _render("source_import_center.html", ctx)


@router.get("/sources/zsxq")
def page_sources_zsxq(request: Request):
    """ZSXQ read-only import and analysis workspace."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    ctx = _build_zsxq_context(vault_path_str)
    ctx["request"] = request
    ctx.update(_flash(request))
    return _render("sources_zsxq.html", ctx)


@router.post("/sources/zsxq/refresh-groups")
def action_zsxq_refresh_groups(request: Request):
    """Refresh local ZSXQ group registry via zsxq-cli."""
    if not _get_vault_path():
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    try:
        from signalvault.sources.zsxq_cli import list_groups
        from signalvault.sources.zsxq_registry import refresh_registry

        result = list_groups()
        if not result.success:
            return RedirectResponse(
                url=f"/sources/zsxq?msg=error:刷新失败 — {result.error[:120]}",
                status_code=303,
            )

        cli_data = result.data or []
        groups_raw = cli_data if isinstance(cli_data, list) else (
            cli_data.get("groups", []) if isinstance(cli_data, dict) else []
        )
        cli_groups = [
            {
                "group_id": g.get("group_id", g.get("id", "")),
                "name": g.get("name", g.get("group_name", "")),
                "topic_count": g.get("topic_count", 0),
            }
            for g in groups_raw if isinstance(g, dict)
        ]
        changes = refresh_registry(cli_groups)
        msg = (
            f"星球列表已刷新：新增 {changes['added']}，恢复 {changes['reactivated']}，"
            f"失效 {changes['deactivated']}，不变 {changes['unchanged']}"
        )
        return RedirectResponse(url=f"/sources/zsxq?msg=success:{msg}", status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/zsxq?msg=error:刷新失败 — {str(e)[:120]}",
            status_code=303,
        )


@router.post("/sources/zsxq/import-topic")
def action_zsxq_import_topic(
    request: Request,
    group_id: str = Form(""),
    topic_id: str = Form(""),
):
    """Import one ZSXQ topic into ingest_jobs without LLM analysis."""
    if not _get_vault_path():
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    group_id = group_id.strip()
    topic_id = topic_id.strip()
    if not group_id or not topic_id:
        return RedirectResponse(
            url="/sources/zsxq?msg=error:请输入 group_id 和 topic_id",
            status_code=303,
        )

    from signalvault.db.session import init_db
    from signalvault.sources.zsxq_import import import_topic_to_ingest

    init_db()
    result = import_topic_to_ingest(group_id, topic_id)
    created = _write_review_findings(result.get("review_findings", []))
    if result.get("success"):
        profile = result.get("profile")
        title = getattr(profile, "topic_title", topic_id) if profile else topic_id
        job = result.get("job") or {}
        return RedirectResponse(
            url=f"/sources/zsxq?msg=success:已导入主题《{title[:40]}》，任务 #{job.get('id', '-')}",
            status_code=303,
        )

    suffix = f"，已写入 {created} 个审核项" if created else ""
    return RedirectResponse(
        url=f"/sources/zsxq?msg=error:导入失败 — {result.get('error', 'unknown')[:120]}{suffix}",
        status_code=303,
    )


@router.post("/sources/zsxq/sync")
def action_zsxq_sync(
    request: Request,
    group_id: str = Form(""),
    limit: int = Form(20),
):
    """Sync recent topics from a ZSXQ group into ingest_jobs."""
    if not _get_vault_path():
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    group_id = group_id.strip()
    if not group_id:
        return RedirectResponse(
            url="/sources/zsxq?msg=error:请输入 group_id",
            status_code=303,
        )
    limit = max(1, min(int(limit or 20), 100))

    from signalvault.db.session import init_db
    from signalvault.sources.zsxq_import import sync_group_to_ingest

    init_db()
    result = sync_group_to_ingest(group_id, limit=limit)
    created = _write_review_findings(result.get("review_findings", []))
    if result.get("success"):
        msg = (
            f"同步完成：导入 {result.get('imported', 0)}，"
            f"跳过 {result.get('skipped', 0)}，错误 {result.get('errors', 0)}"
        )
        return RedirectResponse(url=f"/sources/zsxq?msg=success:{msg}", status_code=303)

    suffix = f"，已写入 {created} 个审核项" if created else ""
    return RedirectResponse(
        url=f"/sources/zsxq?msg=error:同步失败 — {result.get('review_findings', [{}])[0].get('message', 'unknown')[:120]}{suffix}",
        status_code=303,
    )


@router.post("/sources/zsxq/analyze")
def action_zsxq_analyze(
    request: Request,
    group_id: str = Form(""),
    topic_id: str = Form(""),
    focus: str = Form(""),
    depth: str = Form("standard"),
    provider_mode: str = Form("configured"),
):
    """Import and analyze one ZSXQ topic via the existing analysis pipeline."""
    if not _get_vault_path():
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    group_id = group_id.strip()
    topic_id = topic_id.strip()
    if not group_id or not topic_id:
        return RedirectResponse(
            url="/sources/zsxq?msg=error:请输入 group_id 和 topic_id",
            status_code=303,
        )

    from signalvault.config import LLM_PROVIDER
    from signalvault.db.session import init_db
    from signalvault.diagnostics.operation_log import OperationLogManager
    from signalvault.sources.zsxq_analysis import import_and_analyze

    init_db()
    focus_areas = [f.strip() for f in focus.split(",") if f.strip()] if focus else None
    provider = "mock" if provider_mode == "mock" else LLM_PROVIDER
    depth = "deep" if depth == "deep" else "standard"

    op = OperationLogManager.start(
        operation_type="zsxq.topic.analyze",
        source_type="zsxq_topic",
        target_ref=f"group:{group_id}/topic:{topic_id}",
        summary=f"Web 分析 ZSXQ 主题: {topic_id}",
    )
    try:
        result = import_and_analyze(
            group_id=group_id,
            topic_id=topic_id,
            provider_name=provider,
            focus_areas=focus_areas,
            analysis_depth=depth,
        )
        _write_review_findings(result.get("review_findings", []))
        if result.get("success") and result.get("analysis"):
            analysis = result["analysis"]
            OperationLogManager.succeed(
                op,
                summary=f"分析完成，report_id={analysis.get('report_id', 0)}",
                metadata={
                    "report_id": analysis.get("report_id", 0),
                    "view_count": analysis.get("view_count", 0),
                },
            )
            rid = analysis.get("report_id", 0)
            if rid:
                return RedirectResponse(
                    url=f"/reports/{rid}?msg=success:知识星球主题分析完成",
                    status_code=303,
                )
            return RedirectResponse(
                url="/sources/zsxq?msg=success:知识星球主题分析完成",
                status_code=303,
            )

        error = result.get("error", "unknown")
        OperationLogManager.fail(
            op,
            error_code="ANALYSIS_ELIGIBILITY_001",
            error_detail=error[:500],
            summary=f"分析失败: {error[:120]}",
        )
        return RedirectResponse(
            url=f"/sources/zsxq?msg=error:分析失败 — {error[:120]}",
            status_code=303,
        )
    except Exception as e:
        OperationLogManager.fail(
            op,
            error_code="ANALYSIS_PIPELINE_001",
            error_detail=str(e)[:500],
            summary=f"分析异常: {topic_id}",
        )
        return RedirectResponse(
            url=f"/sources/zsxq?msg=error:分析异常 — {str(e)[:120]}",
            status_code=303,
        )


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.1: Channel Source Manager
# ═════════════════════════════════════════════════════════════════════════════

def _build_sources_channels_context(vp_str: str) -> dict:
    """Build context for /sources/channels page."""
    from signalvault.db.repository import list_channels

    session = _get_session()
    try:
        channels = list_channels(session, active_only=True)
    finally:
        session.close()

    return {
        "channels": channels,
        "vault_path": vp_str,
    }


def _build_sources_videos_context(
    channel_id: int, vp_str: str,
    status_filter: str | None = None,
    watchlist_filter: bool = False,
    long_filter: bool = False,
) -> dict | None:
    """Build context for /sources/channels/{id}/videos page.

    Supports optional filters:
        status_filter: filter by import status
        watchlist_filter: only show watchlist-matching videos
        long_filter: only show videos > 90 minutes
    """
    from signalvault.db.repository import (
        detect_video_import_status,
        get_channel,
        list_channel_videos,
    )
    from signalvault.services.watchlist_matcher import (
        compute_recommendation,
        match_video_to_watchlist,
    )
    from signalvault.workspace.watchlist import WatchlistConfig, load_watchlist

    session = _get_session()
    try:
        channel = get_channel(session, channel_id)
        if not channel:
            return None
        videos = list_channel_videos(session, channel_id)

        # Load watchlist once
        vp = Path(vp_str)
        watchlist = load_watchlist(vp) if vp.exists() else WatchlistConfig()

        # Enrich with import status + watchlist match + recommendation badges
        for v in videos:
            v["import_status"] = detect_video_import_status(session, v["video_id"], vp_str)
            match = match_video_to_watchlist(v["title"] or "", watchlist)
            v["watchlist_match"] = match
            v["recommendation_badges"] = compute_recommendation(
                v["import_status"], match, v.get("duration_seconds", 0),
            )

        # Apply filters
        if status_filter:
            videos = [v for v in videos if v["import_status"] == status_filter]
        if watchlist_filter:
            videos = [v for v in videos if v.get("watchlist_match") and v["watchlist_match"].matched]
        if long_filter:
            videos = [v for v in videos if v.get("duration_seconds", 0) > 90 * 60]

    finally:
        session.close()

    return {
        "channel": channel,
        "videos": videos,
        "vault_path": vp_str,
    }


_STAGE_LABELS = {
    "new": "新发现",
    "analyzed": "已生成报告",
    "synced": "已同步",
    "skipped": "已跳过",
    "failed": "整理失败",
    "failed_sync": "报告已生成，同步失败",
    "processing": "整理中",
}

_PRIORITY_LABELS = {
    "core": "核心",
    "watch": "关注",
    "archive": "归档",
}

# P2-S.3.5: Status labels derived from unified SOURCE_STATUS_LABELS.
# Deferred import to avoid E402 (module-level import after non-import code).
def _build_status_labels():
    from signalvault.sources.models import SOURCE_STATUS_LABELS
    return {
        "tracked_source": {
            k: SOURCE_STATUS_LABELS[k]
            for k in ("active", "degraded", "failed", "disabled")
        },
        "tracked_entry": {
            k: SOURCE_STATUS_LABELS[k]
            for k in ("new", "existing", "preview_ready", "imported", "skipped", "failed")
        },
    }

_STATUS_LABELS = _build_status_labels()
_TRACKED_SOURCE_STATUS_LABELS = _STATUS_LABELS["tracked_source"]
_TRACKED_ENTRY_STATUS_LABELS = _STATUS_LABELS["tracked_entry"]


@router.get("/sources/channels")
def page_sources_channels(request: Request):
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    ctx = _build_sources_channels_context(vp_str)
    ctx["request"] = request
    ctx.update(_flash(request))
    ctx["stage_labels"] = _STAGE_LABELS
    ctx["priority_labels"] = _PRIORITY_LABELS
    return _render("sources_channels.html", ctx)


@router.get("/sources/channels/{channel_id}/videos")
def page_sources_videos(
    request: Request,
    channel_id: int,
    status: str | None = None,
    watchlist_match: str | None = None,
    long: str | None = None,
):
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    ctx = _build_sources_videos_context(
        channel_id, vp_str,
        status_filter=status,
        watchlist_filter=(watchlist_match == "1"),
        long_filter=(long == "1"),
    )
    if ctx is None:
        return RedirectResponse(url="/sources/channels?msg=error:频道不存在", status_code=303)

    ctx["request"] = request
    ctx.update(_flash(request))
    ctx["stage_labels"] = _STAGE_LABELS
    ctx["priority_labels"] = _PRIORITY_LABELS
    ctx["channel_id"] = channel_id
    ctx["current_status"] = status or ""
    ctx["current_watchlist"] = watchlist_match or ""
    ctx["current_long"] = long or ""
    return _render("sources_videos.html", ctx)


@router.post("/sources/channels/add")
def action_add_channel(
    request: Request,
    channel_url: str = Form(...),
    name: str = Form(""),
    priority: str = Form("watch"),
    default_focus: str = Form(""),
    default_depth: str = Form("standard"),
):
    """Add a YouTube channel."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.models import Channel
    from signalvault.db.repository import upsert_channel
    from signalvault.utils.youtube import extract_channel_id, is_youtube_url

    if not is_youtube_url(channel_url) and "youtube.com" not in channel_url.lower():
        return RedirectResponse(
            url="/sources/channels?msg=error:请输入有效的 YouTube 频道 URL",
            status_code=303,
        )

    try:
        yt_channel_id = extract_channel_id(channel_url)
    except ValueError as e:
        return RedirectResponse(
            url=f"/sources/channels?msg=error:无法识别频道 ID — {e}",
            status_code=303,
        )

    # Normalize URL for duplicate detection
    def _normalize_channel_url(u: str) -> str:
        u = u.strip().rstrip("/").lower()
        u = u.replace("https://www.youtube.com/", "https://youtube.com/")
        u = u.replace("http://youtube.com/", "https://youtube.com/")
        return u

    normalized_url = _normalize_channel_url(channel_url)

    session = _get_session()
    try:
        # Check by youtube_channel_id (primary dedup)
        existing = session.query(Channel).filter_by(youtube_channel_id=yt_channel_id).first()
        if existing:
            return RedirectResponse(
                url=f"/sources/channels/{existing.id}/videos?msg=success:频道已存在，无需重复添加",
                status_code=303,
            )

        # Check by normalized URL (secondary dedup)
        all_active = session.query(Channel).filter_by(is_active=True).all()
        for ch in all_active:
            if ch.url and _normalize_channel_url(ch.url) == normalized_url:
                return RedirectResponse(
                    url=f"/sources/channels/{ch.id}/videos?msg=success:频道已存在（相同 URL），无需重复添加",
                    status_code=303,
                )

        ch_id = upsert_channel(
            session,
            youtube_channel_id=yt_channel_id,
            name=name or yt_channel_id,
            url=channel_url,
            priority=priority,
            default_focus=default_focus,
            default_depth=default_depth,
        )
        session.commit()
    except Exception as e:
        session.rollback()
        return RedirectResponse(
            url=f"/sources/channels?msg=error:添加失败 — {e}",
            status_code=303,
        )
    finally:
        session.close()

    return RedirectResponse(
        url=f"/sources/channels/{ch_id}/videos?msg=success:频道已添加，可同步视频列表",
        status_code=303,
    )


@router.post("/sources/channels/{channel_id}/edit")
def action_edit_channel(
    request: Request,
    channel_id: int,
    name: str = Form(...),
    priority: str = Form("watch"),
    default_focus: str = Form(""),
):
    """Edit channel name / priority / focus areas."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import update_channel

    session = _get_session()
    try:
        ok = update_channel(
            session,
            channel_id=channel_id,
            name=name.strip() or None,
            priority=priority,
            default_focus=default_focus.strip() or None,
        )
        session.commit()
    except Exception as e:
        session.rollback()
        return RedirectResponse(
            url=f"/sources/channels?msg=error:编辑失败 — {e}",
            status_code=303,
        )
    finally:
        session.close()

    if not ok:
        return RedirectResponse(
            url="/sources/channels?msg=error:频道不存在",
            status_code=303,
        )

    return RedirectResponse(
        url="/sources/channels?msg=success:频道信息已更新",
        status_code=303,
    )


@router.post("/sources/channels/{channel_id}/delete")
def action_delete_channel(request: Request, channel_id: int):
    """Delete (soft-deactivate) a channel."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import delete_channel

    session = _get_session()
    try:
        ok = delete_channel(session, channel_id)
        session.commit()
    except Exception as e:
        session.rollback()
        return RedirectResponse(
            url=f"/sources/channels?msg=error:删除失败 — {e}",
            status_code=303,
        )
    finally:
        session.close()

    if not ok:
        return RedirectResponse(
            url="/sources/channels?msg=error:频道不存在",
            status_code=303,
        )

    return RedirectResponse(
        url="/sources/channels?msg=success:频道已删除",
        status_code=303,
    )


@router.post("/sources/channels/{channel_id}/refresh")
def action_refresh_channel(request: Request, channel_id: int):
    """Create a channel_refresh job and redirect to task detail."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import get_channel
    from signalvault.services.job_service import (
        create_channel_refresh_job,
        start_channel_refresh_job,
    )

    session = _get_session()
    try:
        channel = get_channel(session, channel_id)
        if not channel:
            return RedirectResponse(url="/sources/channels?msg=error:频道不存在", status_code=303)
        channel_url = channel["url"]
        channel_name = channel["name"] or channel["youtube_channel_id"]
    finally:
        session.close()

    job = create_channel_refresh_job(
        channel_url=channel_url,
        channel_name=channel_name,
        channel_id=channel_id,
    )
    start_channel_refresh_job(job)

    return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)


@router.post("/sources/channels/{channel_id}/videos/{video_id}/skip")
def action_skip_video(request: Request, channel_id: int, video_id: str):
    """Mark a video as skipped."""
    from signalvault.db.repository import (
        get_channel_video_by_video_id,
        update_channel_video_status,
    )

    session = _get_session()
    try:
        cv = get_channel_video_by_video_id(session, video_id)
        if cv:
            update_channel_video_status(session, cv["id"], "skipped")
        session.commit()
    finally:
        session.close()

    return RedirectResponse(
        url=f"/sources/channels/{channel_id}/videos?msg=success:已跳过",
        status_code=303,
    )


@router.post("/sources/channels/{channel_id}/videos/{video_id}/import")
def action_import_video(
    request: Request,
    channel_id: int,
    video_id: str,
    focus: str = Form(""),
    depth: str = Form("standard"),
    flow_mode: str = Form("full"),
):
    """Import a video from channel list — with duplicate guard."""
    from signalvault.db.repository import (
        detect_video_import_status,
        get_channel,
        get_channel_video_by_video_id,
        update_channel_video_status,
    )
    from signalvault.services.job_service import (
        create_job,
        create_sync_job,
        start_job,
        start_sync_job,
    )

    vp_str = _get_vault_path()

    session = _get_session()
    try:
        cv = get_channel_video_by_video_id(session, video_id)
        if not cv:
            return RedirectResponse(
                url=f"/sources/channels/{channel_id}/videos?msg=error:视频不存在",
                status_code=303,
            )

        # P2-M.2: Import guard — check current status before creating job
        import_status = detect_video_import_status(session, video_id, vp_str)

        if import_status == "processing":
            return RedirectResponse(
                url=f"/sources/channels/{channel_id}/videos?msg=warning:该视频正在整理中，请稍后查看",
                status_code=303,
            )

        # P2-M.3.1: "analyzed" + report_id → allow sync retry (sync may have failed)
        # "synced" → block (already fully imported)
        if import_status == "synced":
            return RedirectResponse(
                url=f"/sources/channels/{channel_id}/videos?msg=info:该视频已经整理过，可直接查看报告",
                status_code=303,
            )

        video_url = cv["url"] or f"https://www.youtube.com/watch?v={video_id}"
        video_title = cv.get("title", video_id)
        existing_report_id = cv.get("report_id")

        # Get channel defaults
        channel = get_channel(session, channel_id)
        if channel:
            if not focus:
                focus = channel.get("default_focus", "")
            if depth == "standard":
                depth = channel.get("default_depth", "standard")

        # P2-M.2 / P2-M.3.1: Sync retry — failed or analyzed with report_id
        is_sync_retry = (
            import_status in ("failed", "analyzed")
            and existing_report_id is not None
        )

        session.commit()
    finally:
        session.close()

    # P2-M.2: Failed + report_id → retry sync only (not full_flow)
    if is_sync_retry:
        job = create_sync_job(report_id=existing_report_id)
        if video_id:
            job.video_id = video_id
            job.source_type = "channel_video"
            job.source_channel_id = channel_id

        # Mark as processing
        session2 = _get_session()
        try:
            cv2 = get_channel_video_by_video_id(session2, video_id)
            if cv2:
                update_channel_video_status(
                    session2, cv2["id"], "processing",
                    active_job_id=job.job_id,
                )
            session2.commit()
        finally:
            session2.close()

        start_sync_job(job)
        return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)

    # Normal flow: create full_flow (or analysis-only) job
    focus_areas = [f.strip() for f in focus.split(",") if f.strip()] if focus else ["通用投资研究"]

    job = create_job(
        youtube_url=video_url,
        focus_areas=focus_areas,
        depth=depth,
        mock=False,
        auto_sync=(flow_mode == "full"),
        title=video_title or f"整理: {video_id}",
    )

    # Tag job with source context for status writeback
    job.source_type = "channel_video"
    job.source_channel_id = channel_id
    job.video_id = video_id

    # Now mark channel_video as processing (job creation succeeded)
    session2 = _get_session()
    try:
        cv2 = get_channel_video_by_video_id(session2, video_id)
        if cv2:
            update_channel_video_status(
                session2, cv2["id"], "processing",
                active_job_id=job.job_id,
            )
        session2.commit()
    finally:
        session2.close()

    start_job(job)

    return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.3: Rerun (Re-run With Replacement)
# ═════════════════════════════════════════════════════════════════════════════


@router.get("/sources/channels/{channel_id}/videos/{video_id}/rerun")
def page_rerun_video(request: Request, channel_id: int, video_id: str):
    """Show rerun confirmation page."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import (
        detect_video_import_status,
        get_channel,
        get_channel_video_by_video_id,
    )
    from signalvault.db.session import get_session

    session = get_session()
    try:
        channel = get_channel(session, channel_id)
        cv = get_channel_video_by_video_id(session, video_id)
        status = detect_video_import_status(session, video_id, vp_str)
    finally:
        session.close()

    if not channel:
        return RedirectResponse(url="/sources/channels?msg=error:频道不存在", status_code=303)

    video_title = cv["title"] if cv else video_id
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>重新整理 — {video_title}</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body>
<main class="container" style="max-width:600px;margin:40px auto">
    <h2>重新整理: {video_title}</h2>
    <p style="color:var(--text-soft)">该视频已经整理过（当前状态: {status}）。</p>
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px;margin:16px 0">
        <h3>重新整理会：</h3>
        <ul>
            <li>使用当前最新规则重新生成报告</li>
            <li>替换当前知识库中的旧整理结果</li>
            <li>备份旧报告到 99_System/Archive/Reports/</li>
            <li>刷新相关主题、公司、重要判断和观察点</li>
        </ul>
        <p style="color:var(--text-soft);font-size:0.85rem">旧版本会保存在归档中，不会直接删除。</p>
    </div>
    <div style="display:flex;gap:8px">
        <form method="post" action="/sources/channels/{channel_id}/videos/{video_id}/rerun">
            <button type="submit" class="btn-action">确认重新整理</button>
        </form>
        <a href="/sources/channels/{channel_id}/videos" class="btn-action btn-secondary">取消</a>
    </div>
</main>
</body></html>"""
    return HTMLResponse(html)


@router.post("/sources/channels/{channel_id}/videos/{video_id}/rerun")
def action_rerun_video(request: Request, channel_id: int, video_id: str):
    """Execute rerun — archive old, create new full_flow job."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import (
        get_channel_video_by_video_id,
        update_channel_video_status,
    )
    from signalvault.exporters.obsidian import archive_current_video_outputs
    from signalvault.services.job_service import create_job, start_job

    vp = Path(vp_str)

    # Step 1: Archive old outputs
    try:
        archive_current_video_outputs(video_id, vp)
    except Exception:
        pass  # Non-fatal: proceed with rerun even if archive fails

    # Step 2: Get video info
    session = _get_session()
    try:
        cv = get_channel_video_by_video_id(session, video_id)
        video_url = cv["url"] if cv else f"https://www.youtube.com/watch?v={video_id}"
        video_title = cv.get("title", video_id) if cv else video_id
    finally:
        session.close()

    # Step 3: Create rerun job
    job = create_job(
        youtube_url=video_url,
        focus_areas=["通用投资研究"],
        depth="standard",
        mock=False,
        auto_sync=True,
        title=f"[重新整理] {video_title}",
    )
    job.source_type = "channel_video"
    job.source_channel_id = channel_id
    job.video_id = video_id

    # Step 4: Mark processing
    session2 = _get_session()
    try:
        cv2 = get_channel_video_by_video_id(session2, video_id)
        if cv2:
            update_channel_video_status(
                session2, cv2["id"], "processing",
                active_job_id=job.job_id,
            )
        session2.commit()
    finally:
        session2.close()

    start_job(job)
    return RedirectResponse(url=f"/tasks/{job.job_id}", status_code=303)


# ═════════════════════════════════════════════════════════════════════════════
# P2-S.3.1: Generic Web URL Import Preview
# ═════════════════════════════════════════════════════════════════════════════

# In-memory preview store (no writes in preview phase)
_preview_store: dict[str, object] = {}  # ImportPreview instances

# P2-S.3.2: In-memory import results store (survives redirect, cleared on display)
_import_results_store: dict[int, list[dict]] = {}  # tracked_source_id → per-entry results

# P2-S.3.2.1: In-memory profile store (survives redirect to create step)
_profile_store: dict[str, object] = {}  # profile_id → SourceProfile instance

# P2-S.3.3: In-memory file preview store (no writes in preview phase)
# This is a single-process preview cache for local workflow.
# Durable import queues can replace it later.
_file_preview_store: dict[str, object] = {}  # preview_id → FileImportPreview


@router.get("/sources/import")
def page_source_import(request: Request):
    """URL import form page."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vault_path_str,
    }
    ctx.update(_flash(request))
    return _render("source_import.html", ctx)


@router.post("/sources/import/preview")
def action_source_import_preview(
    request: Request,
    url: str = Form(""),
):
    """Parse URL and generate import preview. NO writes happen here."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )

    url = url.strip()
    if not url:
        return RedirectResponse(
            url="/sources/import?msg=error:请输入 URL", status_code=303,
        )

    vp = Path(vault_path_str)
    if not vp.exists():
        return RedirectResponse(
            url="/sources/import?msg=error:知识库目录不存在", status_code=303,
        )

    try:
        from signalvault.sources.import_preview import build_import_preview
        preview = build_import_preview(url, vp)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/import?msg=error:预览生成失败 — {str(e)[:120]}",
            status_code=303,
        )

    _preview_store[preview.preview_id] = preview

    # P3-A: Dual-write to persistent ingest_jobs
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        IngestJobManager.create_job(
            source_type="url_import",
            source_url=url,
            source_hash=getattr(preview, "content_hash", ""),
            source_name=getattr(preview, "title", "") or url,
            preview_data=_serialize_preview(preview),
            preview_id=preview.preview_id,
        )
    except Exception:
        pass  # Non-critical — memory store is the fallback

    # Action labels and descriptions for the template
    from signalvault.sources.models import ACTION_DESCRIPTIONS, ACTION_LABELS

    ctx = {
        "request": request,
        "preview": preview,
        "vault_path": vault_path_str,
        "action_labels": dict(ACTION_LABELS),
        "action_descriptions": dict(ACTION_DESCRIPTIONS),
    }
    ctx.update(_flash(request))
    return _render("source_import_preview.html", ctx)


@router.post("/sources/import/confirm")
def action_source_import_confirm(
    request: Request,
    preview_id: str = Form(...),
    action: str = Form(...),
):
    """Execute the chosen import action. THIS is where writes happen."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )

    vp = Path(vault_path_str)

    preview = _preview_store.pop(preview_id, None)
    if preview is None:
        # P3-A: fall back to persistent ingest_jobs after server restart
        preview = _recover_preview_from_db(preview_id)
    if preview is None:
        return RedirectResponse(
            url="/sources/import?msg=error:预览已过期，请重新导入", status_code=303,
        )

    from signalvault.sources.models import ACTION_LABELS, ActionEnum
    try:
        action_enum = ActionEnum(action)
    except ValueError:
        return RedirectResponse(
            url=f"/sources/import?msg=error:无效的操作: {action}", status_code=303,
        )

    if action_enum == ActionEnum.skip:
        # P3-A: Persist skip decision
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            IngestJobManager.confirm_job(
                preview_id, action="skip",
                action_label=ACTION_LABELS.get("skip", "跳过"),
            )
        except Exception:
            pass
        return RedirectResponse(
            url="/sources/import?msg=info:已取消导入", status_code=303,
        )

    try:
        from signalvault.sources.import_preview import execute_import_action
        result = execute_import_action(preview, action_enum, vp)
    except Exception as e:
        # P3-A: Record failure
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            IngestJobManager.mark_failed(preview_id, str(e)[:500])
        except Exception:
            pass
        return RedirectResponse(
            url=f"/sources/import?msg=error:导入失败 — {str(e)[:120]}",
            status_code=303,
        )

    # P3-A: Dual-write result to ingest_jobs
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        action_label = ACTION_LABELS.get(action, action)
        IngestJobManager.confirm_job(
            preview_id, action=action,
            action_label=action_label,
            result_path=result.get("path", ""),
            result_message=result.get("message", ""),
        )
    except Exception:
        pass

    if result.get("success"):
        return RedirectResponse(
            url=f"/sources/import?msg=success:{result.get('message', '导入完成')}",
            status_code=303,
        )
    else:
        return RedirectResponse(
            url=f"/sources/import?msg=error:{result.get('message', '导入失败')}",
            status_code=303,
        )


# ── P2-S.3.2: Tracked External Sources ────────────────────────────────────


@router.get("/sources/tracked")
def page_sources_tracked(request: Request):
    """List all tracked external sources."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import (
        list_tracked_source_entries,
        list_tracked_sources,
    )

    session = _get_session()
    try:
        sources = list_tracked_sources(session)
        inline_source = sources[0] if len(sources) == 1 else None
        inline_source_id = inline_source["id"] if inline_source else None
        inline_entries = (
            list_tracked_source_entries(session, inline_source_id)
            if inline_source_id else []
        )
    finally:
        session.close()

    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vp_str,
        "sources": sources,
        "inline_source": inline_source,
        "inline_entries": inline_entries,
        "status_labels": _TRACKED_SOURCE_STATUS_LABELS,
        "entry_status_labels": _TRACKED_ENTRY_STATUS_LABELS,
    }
    ctx.update(_flash(request))
    return _render("sources_tracked_list.html", ctx)


@router.get("/sources/tracked/add")
def page_sources_tracked_add(request: Request):
    """Form to add a new tracked source."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vp_str,
    }
    ctx.update(_flash(request))
    return _render("sources_tracked_add.html", ctx)


@router.post("/sources/tracked/profile")
def action_sources_tracked_profile(
    request: Request,
    homepage_url: str = Form(...),
    name: str = Form(""),
):
    """P2-S.3.2.1: Profile a URL and show tracking eligibility preview."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    url = homepage_url.strip()
    if not url:
        return RedirectResponse(
            url="/sources/tracked/add?msg=error:请输入首页 URL", status_code=303)

    from signalvault.sources.models import (
        SUGGESTED_ACTION_LABELS,
        TRACKING_ELIGIBILITY_LABELS,
    )
    from signalvault.sources.source_profiler import profile_source_url

    profile = profile_source_url(url)

    # Store profile for create step
    import uuid
    profile_id = uuid.uuid4().hex[:12]
    _profile_store[profile_id] = profile

    # P3-A: Dual-write profile to ingest_jobs
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        IngestJobManager.create_job(
            source_type="source_profile",
            source_url=url,
            source_name=name.strip() or profile.provider or profile.domain,
            preview_data=_serialize_preview(profile),
            preview_id=profile_id,
        )
    except Exception:
        pass

    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vp_str,
        "profile": profile,
        "profile_id": profile_id,
        "source_name": name.strip() or profile.provider or profile.domain,
        "suggested_action_labels": dict(SUGGESTED_ACTION_LABELS),
        "tracking_eligibility_labels": dict(TRACKING_ELIGIBILITY_LABELS),
    }
    ctx.update(_flash(request))
    return _render("sources_track_profile.html", ctx)


@router.post("/sources/tracked/create")
def action_sources_tracked_create(
    request: Request,
    profile_id: str = Form(""),
    source_name: str = Form(""),
):
    """P2-S.3.2.1: Create a tracked source from a validated profile."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    profile = _profile_store.pop(profile_id, None)
    if profile is None:
        return RedirectResponse(
            url="/sources/tracked/add?msg=error:预览已过期，请重新输入 URL", status_code=303)

    # P3-A: Confirm the profile job
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        IngestJobManager.confirm_job(
            profile_id, action="create_tracked_source",
            action_label="创建固定跟踪源",
        )
    except Exception:
        pass

    if not profile.tracking_supported:
        return RedirectResponse(
            url=f"/sources/tracked/add?msg=error:该来源不支持持续跟踪 — {profile.unsupported_reason or '请使用单网页导入'}",
            status_code=303,
        )

    from signalvault.db.repository import create_tracked_source

    session = _get_session()
    try:
        ts_id = create_tracked_source(
            session,
            name=source_name or profile.provider or profile.domain,
            provider=profile.provider,
            homepage_url=profile.url,
            adapter_name=profile.recommended_adapter or "",
            source_kind=profile.source_kind.value,
            discovery_strategy=profile.discovery_strategy or "",
            identity_strategy=profile.identity_strategy or "",
            change_detection_strategy=profile.change_detection_strategy or "",
            profile_confidence=profile.confidence,
            profile_warnings="\n".join(profile.risk_warnings),
        )
        session.commit()
    except Exception as e:
        session.rollback()
        return RedirectResponse(
            url=f"/sources/tracked/add?msg=error:创建失败 — {e}", status_code=303)
    finally:
        session.close()

    return RedirectResponse(
        url=f"/sources/tracked/{ts_id}?msg=success:信息源已添加，可刷新获取内容",
        status_code=303,
    )


@router.get("/sources/tracked/{tracked_source_id}")
def page_sources_tracked_detail(request: Request, tracked_source_id: int):
    """Detail page for a single tracked source."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import get_tracked_source

    session = _get_session()
    try:
        ts = get_tracked_source(session, tracked_source_id)
        if not ts:
            return RedirectResponse(
                url="/sources/tracked?msg=error:信息源不存在", status_code=303)
    finally:
        session.close()

    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vp_str,
        "source": ts,
        "status_labels": _TRACKED_SOURCE_STATUS_LABELS,
    }
    ctx.update(_flash(request))
    return _render("sources_tracked_detail.html", ctx)


@router.post("/sources/tracked/{tracked_source_id}/refresh")
def action_sources_tracked_refresh(request: Request, tracked_source_id: int):
    """Refresh a tracked source — discover new entries and generate previews."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    vp = Path(vp_str)
    if not vp.exists():
        return RedirectResponse(
            url="/setup/vault?msg=error:知识库目录不存在", status_code=303)

    from signalvault.sources.tracked_source_service import refresh_tracked_source

    try:
        result = refresh_tracked_source(tracked_source_id, vp, _preview_store)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}?msg=error:刷新失败 — {str(e)[:120]}",
            status_code=303,
        )

    if result["success"]:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}/entries?msg=success:{result['message']}",
            status_code=303,
        )
    else:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}?msg=error:{result['message']}",
            status_code=303,
        )


@router.get("/sources/tracked/{tracked_source_id}/entries")
def page_sources_tracked_entries(
    request: Request,
    tracked_source_id: int,
    status: str | None = None,
):
    """List entries for a tracked source with optional status filter."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    from signalvault.db.repository import (
        get_tracked_source,
        list_tracked_source_entries,
    )

    session = _get_session()
    try:
        ts = get_tracked_source(session, tracked_source_id)
        if not ts:
            return RedirectResponse(
                url="/sources/tracked?msg=error:信息源不存在", status_code=303)
        entries = list_tracked_source_entries(session, tracked_source_id, status_filter=status)
    finally:
        session.close()

    # Enrich preview_ready entries with preview data from _preview_store
    for entry in entries:
        if entry["status"] == "preview_ready" and entry.get("preview_id"):
            preview = _preview_store.get(entry["preview_id"])
            if preview:
                entry["recommended_action"] = preview.recommended_action.value
                entry["available_actions"] = [a.value for a in preview.available_actions]
                entry["parse_quality"] = preview.parse_quality
                entry["summary"] = preview.summary

    # Pop import results if present (one-shot display, cleared after rendering)
    import_results = _import_results_store.pop(tracked_source_id, None)

    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vp_str,
        "source": ts,
        "entries": entries,
        "current_status": status or "",
        "status_labels": _TRACKED_SOURCE_STATUS_LABELS,
        "entry_status_labels": _TRACKED_ENTRY_STATUS_LABELS,
        "import_results": import_results or [],
    }
    ctx.update(_flash(request))
    return _render("sources_tracked_entries.html", ctx)


@router.post("/sources/tracked/{tracked_source_id}/import")
def action_sources_tracked_import(
    request: Request,
    tracked_source_id: int,
    entry_ids: str = Form(""),
    action: str = Form(""),
):
    """Batch import selected tracked source entries."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)

    vp = Path(vp_str)

    ids = [int(i.strip()) for i in entry_ids.split(",") if i.strip()]
    if not ids:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}/entries?msg=error:未选择任何条目",
            status_code=303,
        )

    from signalvault.sources.models import ActionEnum
    try:
        action_enum = ActionEnum(action) if action else ActionEnum.import_as_deep_notes_derived_only
    except ValueError:
        action_enum = ActionEnum.import_as_deep_notes_derived_only

    from signalvault.sources.tracked_source_service import (
        import_tracked_source_entries,
    )

    try:
        result = import_tracked_source_entries(
            tracked_source_id, ids, action_enum, vp, _preview_store,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}/entries?msg=error:导入失败 — {str(e)[:120]}",
            status_code=303,
        )

    # Store per-entry results for display on entries page
    _import_results_store[tracked_source_id] = result["results"]

    # Show summary in flash, details in results section
    msg = f"已导入 {result['imported']}/{result['total']} 条"
    if result["failed"] > 0:
        msg += f"，{result['failed']} 条失败（详见下方结果）"
    return RedirectResponse(
        url=f"/sources/tracked/{tracked_source_id}/entries?msg=success:{msg}",
        status_code=303,
    )


@router.post("/sources/tracked/{tracked_source_id}/entries/{entry_id}/skip")
def action_tracked_entry_skip(
    request: Request,
    tracked_source_id: int,
    entry_id: int,
):
    """Skip a single tracked source entry."""
    from signalvault.db.repository import update_tracked_source_entry_status

    session = _get_session()
    try:
        update_tracked_source_entry_status(session, entry_id, "skipped")
        session.commit()
    finally:
        session.close()

    return RedirectResponse(
        url=f"/sources/tracked/{tracked_source_id}/entries?msg=info:已跳过",
        status_code=303,
    )


@router.post("/sources/tracked/{tracked_source_id}/entries/{entry_id}/import")
def action_tracked_entry_import_single(
    request: Request,
    tracked_source_id: int,
    entry_id: int,
    action: str = Form(""),
):
    """Import a single tracked source entry using its stored preview."""
    vp_str = _get_vault_path()
    if not vp_str:
        return RedirectResponse(url="/setup/vault?msg=error:请先配置知识库", status_code=303)
    vp = Path(vp_str)

    from signalvault.sources.models import ActionEnum
    try:
        action_enum = ActionEnum(action) if action else ActionEnum.import_as_deep_notes_derived_only
    except ValueError:
        action_enum = ActionEnum.import_as_deep_notes_derived_only

    from signalvault.sources.tracked_source_service import (
        import_tracked_source_entries,
    )
    result = import_tracked_source_entries(
        tracked_source_id, [entry_id], action_enum, vp, _preview_store,
    )
    # Store per-entry results for display on entries page
    _import_results_store[tracked_source_id] = result["results"]
    first = result["results"][0] if result["results"] else {}
    if first.get("success"):
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}/entries?msg=success:{first.get('message', '导入完成')}",
            status_code=303,
        )
    else:
        return RedirectResponse(
            url=f"/sources/tracked/{tracked_source_id}/entries?msg=error:{first.get('message', '导入失败')}",
            status_code=303,
        )


@router.post("/sources/tracked/{tracked_source_id}/delete")
def action_tracked_source_delete(request: Request, tracked_source_id: int):
    """Delete a tracked source and all its entries."""
    from signalvault.db.repository import delete_tracked_source

    session = _get_session()
    try:
        ok = delete_tracked_source(session, tracked_source_id)
        session.commit()
    except Exception as e:
        session.rollback()
        return RedirectResponse(
            url=f"/sources/tracked?msg=error:删除失败 — {e}", status_code=303)
    finally:
        session.close()

    if not ok:
        return RedirectResponse(
            url="/sources/tracked?msg=error:信息源不存在", status_code=303)

    return RedirectResponse(
        url="/sources/tracked?msg=info:已删除信息源及所有条目", status_code=303)


# ═════════════════════════════════════════════════════════════════════════════
# P2-S.3.3: User Text File Upload Preview & Archive
# ═════════════════════════════════════════════════════════════════════════════

# Temp directory for uploaded files (lives in system temp, auto-cleaned)
_UPLOAD_TEMP_DIR = Path(tempfile.gettempdir()) / "signalvault_uploads"


async def _preview_pdf_upload(
    request: Request,
    filename: str,
    tmp_path: Path,
    vault_path: Path,
):
    """Handle PDF upload preview — extract PDF, build preview context, render template."""
    from signalvault.sources.pdf_extraction import extract_pdf

    result = extract_pdf(tmp_path)

    preview_id = __import__("uuid").uuid4().hex[:8]

    pdf_preview = {
        "preview_id": preview_id,
        "filename": filename,
        "file_size_bytes": tmp_path.stat().st_size,
        "page_count": result.page_count,
        "quality": result.quality,
        "needs_ocr": result.needs_ocr,
        "content_hash": result.content_hash,
        "title": result.metadata.title or Path(filename).stem,
        "author": result.metadata.author or "",
        "text_excerpt": result.full_text[:2000] if result.full_text else "",
        "text_length": len(result.full_text or ""),
        "error_message": result.error_message,
        "import_eligible": result.quality in ("good", "degraded"),
        "ineligible_reason": (
            "PDF 文本提取失败，无法导入分析。" if result.quality == "failed"
            else "PDF 文本量过少，无法进行有效分析。" if result.quality == "minimal"
            else ""
        ),
        "_temp_path": tmp_path,
        "_is_pdf": True,
    }

    # Store preview
    _file_preview_store[preview_id] = pdf_preview

    # Dual-write to ingest_jobs
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        IngestJobManager.create_job(
            source_type="file_upload",
            source_hash=result.content_hash or "",
            source_name=filename,
            preview_id=preview_id,
            action="",
        )
    except Exception:
        pass

    from signalvault.sources.models import ACTION_DESCRIPTIONS, ACTION_LABELS

    ctx = {
        "request": request,
        "preview": pdf_preview,
        "is_pdf": True,
        "vault_path": str(vault_path),
        "vault_configured": True,
        "action_labels": dict(ACTION_LABELS),
        "action_descriptions": dict(ACTION_DESCRIPTIONS),
    }
    return _render("source_file_import_preview.html", ctx)


def _confirm_pdf_analysis(preview_id: str, tmp_path: Path, preview: dict | object):
    """Run PDF analysis synchronously and redirect to the report."""
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        from signalvault.sources.models import ACTION_LABELS
        IngestJobManager.confirm_job(
            preview_id,
            action="pdf_analyze",
            action_label=ACTION_LABELS.get("pdf_analyze", "PDF 分析"),
            result_path=str(tmp_path),
        )
    except Exception:
        pass

    # Run analysis synchronously (same pattern as ZSXQ analyze route)
    from signalvault.sources.pdf_analysis import analyze_pdf

    try:
        result = analyze_pdf(
            file_path=tmp_path,
            provider_name="mock",
            write_review=True,
        )
    except Exception as e:
        _cleanup_temp_file(tmp_path)
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:PDF 分析失败 — {str(e)[:120]}",
            status_code=303,
        )

    _cleanup_temp_file(tmp_path)

    if result.get("success") and result.get("report_id"):
        return RedirectResponse(
            url=f"/reports/{result['report_id']}?msg=success:PDF 分析完成",
            status_code=303,
        )
    else:
        reason = result.get("reason", "分析未能完成")
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:{reason}",
            status_code=303,
        )


@router.get("/sources/files/import")
def page_source_file_import(request: Request):
    """File upload form page."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )
    ctx = {
        "request": request,
        "vault_configured": True,
        "vault_path": vault_path_str,
        "max_upload_mb": 5,
    }
    ctx.update(_flash(request))
    return _render("source_file_import.html", ctx)


@router.post("/sources/files/preview")
async def action_source_file_preview(
    request: Request,
    file: UploadFile | None = None,
):
    """Receive uploaded file, extract content, and generate preview. NO vault writes."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )

    if file is None or not file.filename:
        return RedirectResponse(
            url="/sources/files/import?msg=error:请选择要上传的文件", status_code=303,
        )

    vp = Path(vault_path_str)
    if not vp.exists():
        return RedirectResponse(
            url="/sources/files/import?msg=error:知识库目录不存在", status_code=303,
        )

    # ── Validate extension early ────────────────────────────────────────
    from signalvault.sources.file_profile import (
        ALLOWED_PDF_EXTENSIONS,
        ALLOWED_TEXT_EXTENSIONS,
        UNSUPPORTED_MESSAGE,
    )

    ext = Path(file.filename).suffix.lower()
    is_pdf = ext in ALLOWED_PDF_EXTENSIONS
    if ext not in ALLOWED_TEXT_EXTENSIONS and not is_pdf:
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:{UNSUPPORTED_MESSAGE}", status_code=303,
        )

    # ── Save to temp directory ──────────────────────────────────────────
    _UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_upload_filename(file.filename)
    tmp_path = _UPLOAD_TEMP_DIR / f"{__import__('uuid').uuid4().hex[:8]}_{safe_name}"
    raw_bytes = await file.read()

    # ── Size check ──────────────────────────────────────────────────────
    from signalvault.sources.file_profile import MAX_PDF_UPLOAD_BYTES, MAX_UPLOAD_BYTES
    max_bytes = MAX_PDF_UPLOAD_BYTES if is_pdf else MAX_UPLOAD_BYTES
    if len(raw_bytes) > max_bytes:
        size_mb = len(raw_bytes) / (1024 * 1024)
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:文件大小 ({size_mb:.1f} MB) 超过限制 ({max_bytes // (1024 * 1024)} MB)", status_code=303,
        )

    try:
        tmp_path.write_bytes(raw_bytes)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:无法保存上传文件 — {e}", status_code=303,
        )

    # ── PDF branch: extract and preview ──────────────────────────────────
    if is_pdf:
        return await _preview_pdf_upload(request, file.filename, tmp_path, vp)

    # ── Step 1: Profile the uploaded file ───────────────────────────────
    from signalvault.sources.file_profile import profile_uploaded_file
    profile = profile_uploaded_file(tmp_path, file.filename, raw_bytes=raw_bytes)

    if not profile.supported:
        _cleanup_temp_file(tmp_path)
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:{profile.unsupported_reason or '文件不支持导入'}",
            status_code=303,
        )

    # ── Step 2: Extract content ─────────────────────────────────────────
    from signalvault.sources.file_content_extractor import (
        extract_text_from_uploaded_file,
    )
    content = extract_text_from_uploaded_file(
        tmp_path,
        file.filename,
        content_hash=profile.content_hash or "",
        detected_encoding=profile.detected_encoding or "utf-8",
    )

    # ── Step 3: Build preview ───────────────────────────────────────────
    from signalvault.sources.file_import_preview import (
        build_file_import_preview,
    )
    preview = build_file_import_preview(profile, content, vp)

    # ── Store preview for confirm step ──────────────────────────────────
    _file_preview_store[preview.preview_id] = preview

    # Store temp path for confirm step (attached to preview)
    preview._temp_path = tmp_path  # type: ignore[attr-defined]

    # P3-A: Dual-write to persistent ingest_jobs
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        IngestJobManager.create_job(
            source_type="file_upload",
            source_hash=getattr(preview, "content_hash", "") or "",
            source_name=getattr(preview, "filename", "") or file.filename,
            preview_data=_serialize_preview(preview),
            preview_id=preview.preview_id,
        )
    except Exception:
        pass

    from signalvault.sources.models import ACTION_DESCRIPTIONS, ACTION_LABELS

    ctx = {
        "request": request,
        "preview": preview,
        "vault_path": vault_path_str,
        "action_labels": dict(ACTION_LABELS),
        "action_descriptions": dict(ACTION_DESCRIPTIONS),
    }
    ctx.update(_flash(request))
    return _render("source_file_import_preview.html", ctx)


@router.post("/sources/files/confirm")
def action_source_file_confirm(
    request: Request,
    preview_id: str = Form(...),
    action: str = Form(...),
):
    """Execute the confirmed file import action. THIS is where vault writes happen."""
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(
            url="/setup/vault?msg=error:请先配置知识库目录", status_code=303,
        )

    vp = Path(vault_path_str)

    preview = _file_preview_store.pop(preview_id, None)
    if preview is None:
        preview = _recover_preview_from_db(preview_id)
    if preview is None:
        return RedirectResponse(
            url="/sources/files/import?msg=error:预览已过期，请重新上传", status_code=303,
        )

    from signalvault.sources.models import ActionEnum

    # P3-A helper: record job outcome
    def _record_file_job(status_action: str, path: str = "", msg: str = ""):
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            from signalvault.sources.models import ACTION_LABELS
            IngestJobManager.confirm_job(
                preview_id, action=status_action,
                action_label=ACTION_LABELS.get(status_action, status_action),
                result_path=path, result_message=msg,
            )
        except Exception:
            pass

    if action == ActionEnum.skip.value:
        _cleanup_temp_file(getattr(preview, "_temp_path", None))
        _record_file_job("skip")
        return RedirectResponse(
            url="/sources/files/import?msg=info:已跳过导入", status_code=303,
        )

    if action != ActionEnum.confirm_archive.value:
        _cleanup_temp_file(getattr(preview, "_temp_path", None))
        _record_file_job("skip")
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:无效的操作: {action}", status_code=303,
        )

    if not preview.import_eligible:
        _cleanup_temp_file(getattr(preview, "_temp_path", None))
        _record_file_job("skip")
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:{preview.ineligible_reason or '该文件不符合入库条件'}",
            status_code=303,
        )

    # ── PDF branch: analyze as background job ────────────────────────────
    is_pdf_preview = (
        isinstance(preview, dict) and preview.get("_is_pdf")
        or getattr(preview, "_is_pdf", False)
    )
    if is_pdf_preview:
        tmp_path = getattr(preview, "_temp_path", None) or (
            preview.get("_temp_path") if isinstance(preview, dict) else None
        )
        if not tmp_path:
            return RedirectResponse(
                url="/sources/files/import?msg=error:PDF 临时文件已丢失，请重新上传",
                status_code=303,
            )
        return _confirm_pdf_analysis(preview_id, tmp_path, preview)

    # ── Execute import (text files) ─────────────────────────────────────
    from signalvault.sources.file_import_preview import confirm_file_import

    try:
        result = confirm_file_import(preview, vp)
    except Exception as e:
        _cleanup_temp_file(getattr(preview, "_temp_path", None))
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            IngestJobManager.mark_failed(preview_id, str(e)[:500])
        except Exception:
            pass
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:导入失败 — {str(e)[:120]}",
            status_code=303,
        )

    # Cleanup temp file after successful import
    _cleanup_temp_file(getattr(preview, "_temp_path", None))

    # P3-A: Record successful archive
    _record_file_job(
        "confirm_archive",
        path=result.get("path", ""),
        msg=result.get("message", ""),
    )

    if result.get("success"):
        return RedirectResponse(
            url=f"/sources/files/import?msg=success:{result.get('message', '导入完成')}",
            status_code=303,
        )
    else:
        return RedirectResponse(
            url=f"/sources/files/import?msg=error:{result.get('message', '导入失败')}",
            status_code=303,
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _recover_preview_from_db(preview_id: str) -> dict | None:
    """Recover a preview from IngestJobManager after server restart."""
    try:
        from signalvault.sources.ingest_jobs import IngestJobManager
        job = IngestJobManager.find_by_preview_id(preview_id)
        if not job:
            return None
        preview_data = job.get("preview_data", "")
        if not preview_data:
            return None
        import json as _json
        return _json.loads(preview_data)
    except Exception:
        return None


def _serialize_preview(preview: object) -> str:
    """P3-A: Serialize an ImportPreview / FileImportPreview / SourceProfile to JSON."""
    import json
    if preview is None:
        return ""
    try:
        # Use dataclass-compatible serialization
        return json.dumps(
            preview, default=lambda o: o.__dict__, ensure_ascii=False,
        )
    except (TypeError, ValueError):
        return ""


def _sanitize_upload_filename(filename: str) -> str:
    """Sanitize a user-uploaded filename for temp storage."""
    import re
    # Keep only safe characters
    safe = re.sub(r"[^\w\.\-]", "_", filename)
    # Prevent directory traversal
    safe = Path(safe).name
    return safe or "uploaded_file"


def _cleanup_temp_file(path: Path | None) -> None:
    """Remove a temporary uploaded file."""
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
