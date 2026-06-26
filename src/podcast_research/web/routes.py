"""P1-C / P2-I.2 / P2-K.2.1: HTML pages + actions — /dashboard /reports /tasks /patches /search + POST actions"""

import re
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from podcast_research.db.repository import (
    get_report_detail,
    list_reports,
    search_reports,
)
from podcast_research.db.session import get_session, init_db

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
    cache_size=0,
)


def _get_vault_path() -> str:
    from podcast_research.config_store import get_user_vault_path
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
    from podcast_research.claim_signal.review import (
        _parse_frontmatter,
        update_claim_status,
        update_signal_status,
    )
    from podcast_research.utils.file_io import read_text_safe
    from podcast_research.workspace.generators import _token_overlap

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
    from podcast_research.db.models import Episode, Report
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


def _build_dashboard_context(vault_path: Path) -> dict:
    """Build dashboard data from vault scan. Returns context dict or error info.

    P2-N.4.3: Uses shared system_curation and review_priority logic for consistency
    between web dashboard and Obsidian Home.
    """
    from podcast_research.workspace.scanner import VaultScanner

    scanner = VaultScanner(vault_path)
    snapshot = scanner.scan()

    # P2-N.4.3: Compute system_curation for topics and companies
    try:
        from podcast_research.workspace.system_curation import (
            compute_company_system_curation,
            compute_topic_system_curation,
            curation_label,
        )
        from podcast_research.workspace.watchlist import load_watchlist
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

    # P2-N.4.3: Compute review_priority
    try:
        from podcast_research.workspace.review_priority import (
            PRIORITY_AUTO_ACCEPTED,
            PRIORITY_LOW,
            claims_needing_review,
            compute_claim_review_priority,
            compute_signal_review_priority,
            signals_needing_review,
        )
        for cl in snapshot.claims:
            cl.review_priority = compute_claim_review_priority(
                cl, snapshot, wl_companies_set, wl_topics_set,
            )
        for s in snapshot.signals:
            s.review_priority = compute_signal_review_priority(
                s, snapshot, wl_companies_set, wl_topics_set,
            )
        needs_review_n = len(claims_needing_review(snapshot, wl_companies_set, wl_topics_set)) + \
                         len(signals_needing_review(snapshot, wl_companies_set, wl_topics_set))
        auto_accepted_n = sum(
            1 for c in snapshot.claims
            if compute_claim_review_priority(c, snapshot, wl_companies_set, wl_topics_set) == PRIORITY_AUTO_ACCEPTED
        ) + sum(
            1 for s in snapshot.signals
            if compute_signal_review_priority(s, snapshot, wl_companies_set, wl_topics_set) == PRIORITY_AUTO_ACCEPTED
        )
        low_priority_n = sum(
            1 for c in snapshot.claims
            if compute_claim_review_priority(c, snapshot, wl_companies_set, wl_topics_set) == PRIORITY_LOW
        ) + sum(
            1 for s in snapshot.signals
            if compute_signal_review_priority(s, snapshot, wl_companies_set, wl_topics_set) == PRIORITY_LOW
        )
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

    from podcast_research.workspace.generators import (
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
        from podcast_research.workspace.actionability import (
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

    # Build research brief (rule-based insights)
    try:
        from podcast_research.workspace.research_brief import generate_brief
        research_brief = generate_brief(snapshot)
        # Enrich recommended_reports with DB report_ids for direct linking
        if research_brief and research_brief.recommended_reports:
            _enrich_recommended_with_report_ids(research_brief.recommended_reports)
    except Exception:
        research_brief = None

    # Build watchlist brief
    try:
        from podcast_research.workspace.watchlist import (
            ensure_watchlist_template,
            generate_watchlist_brief,
        )
        from podcast_research.workspace.watchlist import (
            load_watchlist as _load_wl,
        )
        if wl_config is None:
            wl_config = _load_wl(vault_path)
        watchlist_items = generate_watchlist_brief(snapshot, vault_path) if (
            wl_config.companies or wl_config.topics
        ) else []
        watchlist_configured = bool(wl_config.companies or wl_config.topics)
        if not watchlist_configured:
            ensure_watchlist_template(vault_path)
    except Exception:
        watchlist_items = []
        watchlist_configured = False

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
        "error": None,
    }


# ── GET Routes ────────────────────────────────────────────────────

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
        from podcast_research.workspace.setup import initialize_vault
        result = initialize_vault(target)

        from podcast_research.config_store import save_user_vault_path
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
        from podcast_research.workspace.setup import repair_vault
        result = repair_vault(target)
        created = len(result.created_dirs) + len(result.created_files)
        return RedirectResponse(
            url=f"/dashboard?msg=success:知识库已修复，补齐了 {created} 项缺失内容",
            status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard?msg=error:修复失败: {e}", status_code=303)


@router.get("/dashboard")
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
        from podcast_research.services.job_service import count_active_jobs
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
        from podcast_research.workspace.setup import validate_vault
        health = validate_vault(vp)
        if not health.is_initialized:
            ctx["needs_repair"] = True
            ctx["missing_dirs"] = health.missing_dirs
            ctx["missing_files"] = health.missing_files
    except Exception:
        pass

    try:
        ctx.update(_build_dashboard_context(vp))
    except Exception as e:
        ctx["error"] = str(e)
    return _render("dashboard.html", ctx)


@router.get("/reports")
def page_reports(request: Request, limit: int = 50, source: str | None = None):
    session = _get_session()
    try:
        reports = list_reports(session, limit=limit, source_type=source)
    finally:
        session.close()
    ctx = {"request": request, "reports": reports}
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
    ctx = {"request": request, "report": report, "hl": hl}
    ctx.update(_flash(request))
    return _render("report_detail.html", ctx)


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
        from podcast_research.workspace.research_brief import generate_brief
        from podcast_research.workspace.scanner import VaultScanner
        from podcast_research.workspace.watchlist import (
            generate_watchlist_brief,
            load_watchlist,
        )

        scanner = VaultScanner(vp)
        snapshot = scanner.scan()
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
        from podcast_research.workspace.watchlist import ensure_watchlist_template
        ensure_watchlist_template(vp)
        ctx["config_created"] = True

    try:
        from podcast_research.workspace.scanner import VaultScanner
        from podcast_research.workspace.watchlist import generate_watchlist_brief

        scanner = VaultScanner(vp)
        snapshot = scanner.scan()
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

    from podcast_research.workspace.watchlist import (
        ensure_watchlist_template,
        load_watchlist,
    )
    ensure_watchlist_template(vp)
    config = load_watchlist(vp)
    ctx["config"] = config

    # Check card existence and suggestions
    try:
        from podcast_research.workspace.scanner import VaultScanner
        from podcast_research.workspace.watchlist import (
            get_suggested_companies,
            get_suggested_topics,
            resolve_watchlist_name,
        )
        scanner = VaultScanner(vp)
        snapshot = scanner.scan()
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

    from podcast_research.workspace.watchlist import add_watchlist_item
    _, msg = add_watchlist_item(Path(vault_path_str), item_type, name)
    msg_type = "success" if "已添加" in msg else "error"
    return RedirectResponse(url=f"/watchlist/settings?msg={msg_type}:{msg}", status_code=303)


@router.post("/watchlist/settings/remove")
def action_watchlist_remove(request: Request, item_type: str = Form(...), name: str = Form(...)):
    vault_path_str = _get_vault_path()
    if not vault_path_str:
        return RedirectResponse(url="/watchlist/settings?msg=error:Vault 未配置", status_code=303)

    from podcast_research.workspace.watchlist import remove_watchlist_item
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
            from podcast_research.workspace.watchlist import load_watchlist
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
    from podcast_research.utils.youtube import is_youtube_url

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
    from podcast_research.services.job_service import create_job, start_job
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

    from podcast_research.services.job_service import get_job_status

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
    from podcast_research.services.job_service import create_sync_job, start_sync_job
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

    from podcast_research.services.job_service import get_job_status

    data = get_job_status(job_id)
    if data is None:
        return JSONResponse({"status": "not_found", "error": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(data)


# ── P2-K.2.1: Unified Task Routes ──────────────────────────────────


@router.get("/tasks")
def page_tasks(request: Request):
    """Unified task list page — shows all recent jobs."""
    from podcast_research.services.job_service import (
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
    ctx.update(_flash(request))
    return _render("task_list.html", ctx)


@router.get("/tasks/{job_id}")
def page_task_detail(request: Request, job_id: str):
    """Unified task detail page — renders task progress UI.

    P2-O.2.1: Passes get_job_status() so server-rendered terminal states
    have failure_kind, error_summary, completed_steps, and pending_steps.
    """
    import json as _json

    from podcast_research.services.job_service import get_job, get_job_status
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

    from podcast_research.services.job_service import get_job_status

    data = get_job_status(job_id)
    if data is None:
        return JSONResponse({"status": "not_found", "error": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(data)


@router.get("/tasks/{job_id}/logs")
def page_task_logs(request: Request, job_id: str):
    """P2-M.4.1: Task event log detail page."""
    from podcast_research.services.job_service import get_job, get_job_status

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
    from podcast_research.services.job_service import delete_job
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


@router.get("/search")
def page_search(request: Request, q: str = ""):
    ctx = {"request": request, "q": "", "results": [], "count": 0}
    ctx.update(_flash(request))
    if not q.strip():
        return _render("search.html", ctx)
    ctx["q"] = q.strip()
    session = _get_session()
    try:
        ctx["results"] = search_reports(session, q.strip(), limit=20)
        ctx["count"] = len(ctx["results"])
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
        from podcast_research.claim_signal.review import _parse_frontmatter
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

    from podcast_research.claim_signal.review import _parse_frontmatter
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
        from podcast_research.workspace import (
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
        from podcast_research.llm_wiki.applier import apply_patch
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
        from podcast_research.llm_wiki.rollback import reject_patch
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
        from podcast_research.claim_signal.review import update_claim_status
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
        from podcast_research.claim_signal.review import update_signal_status
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
# P2-M.1: Channel Source Manager
# ═════════════════════════════════════════════════════════════════════════════

def _build_sources_channels_context(vp_str: str) -> dict:
    """Build context for /sources/channels page."""
    from podcast_research.db.repository import list_channels

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
    from podcast_research.db.repository import (
        detect_video_import_status,
        get_channel,
        list_channel_videos,
    )
    from podcast_research.services.watchlist_matcher import (
        compute_recommendation,
        match_video_to_watchlist,
    )
    from podcast_research.workspace.watchlist import WatchlistConfig, load_watchlist

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

    from podcast_research.db.models import Channel
    from podcast_research.db.repository import upsert_channel
    from podcast_research.utils.youtube import extract_channel_id, is_youtube_url

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

    from podcast_research.db.repository import update_channel

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

    from podcast_research.db.repository import delete_channel

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

    from podcast_research.db.repository import get_channel
    from podcast_research.services.job_service import (
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
    from podcast_research.db.repository import (
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
    from podcast_research.db.repository import (
        detect_video_import_status,
        get_channel,
        get_channel_video_by_video_id,
        update_channel_video_status,
    )
    from podcast_research.services.job_service import (
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

    from podcast_research.db.repository import (
        detect_video_import_status,
        get_channel,
        get_channel_video_by_video_id,
    )
    from podcast_research.db.session import get_session

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

    from podcast_research.db.repository import (
        get_channel_video_by_video_id,
        update_channel_video_status,
    )
    from podcast_research.exporters.obsidian import archive_current_video_outputs
    from podcast_research.services.job_service import create_job, start_job

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
        from podcast_research.sources.import_preview import build_import_preview
        preview = build_import_preview(url, vp)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/import?msg=error:预览生成失败 — {str(e)[:120]}",
            status_code=303,
        )

    _preview_store[preview.preview_id] = preview

    # Action descriptions for the template
    from podcast_research.sources.models import ACTION_DESCRIPTIONS

    ctx = {
        "request": request,
        "preview": preview,
        "vault_path": vault_path_str,
        "action_descriptions": {
            a.value: d for a, d in ACTION_DESCRIPTIONS.items()
        },
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
        return RedirectResponse(
            url="/sources/import?msg=error:预览已过期，请重新导入", status_code=303,
        )

    from podcast_research.sources.models import ActionEnum
    try:
        action_enum = ActionEnum(action)
    except ValueError:
        return RedirectResponse(
            url=f"/sources/import?msg=error:无效的操作: {action}", status_code=303,
        )

    if action_enum == ActionEnum.skip:
        return RedirectResponse(
            url="/sources/import?msg=info:已取消导入", status_code=303,
        )

    try:
        from podcast_research.sources.import_preview import execute_import_action
        result = execute_import_action(preview, action_enum, vp)
    except Exception as e:
        return RedirectResponse(
            url=f"/sources/import?msg=error:导入失败 — {str(e)[:120]}",
            status_code=303,
        )

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
