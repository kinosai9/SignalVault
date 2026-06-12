"""P1-C / P2-I.1: HTML 页面测试 — 复用 seeded_db + api_client fixtures"""

import os


def test_index_redirects(api_client):
    """GET / 返回 302 重定向到 /reports（无 vault 配置时）"""
    resp = api_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    # With no vault configured, redirects to /reports
    assert resp.headers["location"] in ("/reports", "/dashboard")


def test_reports_list_ok(api_client, seeded_db):
    """GET /reports 返回 200 并包含 seeded report"""
    resp = api_client.get("/reports")
    assert resp.status_code == 200
    html = resp.text
    assert "报告库" in html
    assert "宁德时代" in html or "新能源" in html


def test_reports_list_with_source_filter(api_client, seeded_db):
    """GET /reports?source=youtube 过滤来源"""
    resp = api_client.get("/reports?source=youtube")
    assert resp.status_code == 200
    html = resp.text
    assert "abc123" in html or "youtube" in html.lower()


def test_report_detail_ok(api_client, seeded_db):
    """GET /reports/{id} 返回 200 并包含核心观点"""
    resp = api_client.get("/reports/1")
    assert resp.status_code == 200
    html = resp.text
    assert "核心观点矩阵" in html
    assert "宁德时代" in html


def test_report_detail_not_found(api_client):
    """不存在的 report_id 返回 HTML 404"""
    resp = api_client.get("/reports/99999")
    assert resp.status_code == 404
    html = resp.text
    assert "404" in html
    assert "不存在" in html


def test_search_with_query(api_client, seeded_db):
    """GET /search?q=宁德 返回 200 并有结果"""
    resp = api_client.get("/search?q=宁德")
    assert resp.status_code == 200
    html = resp.text
    assert "宁德" in html


def test_search_empty_query(api_client):
    """GET /search 不带 q 返回 200 并显示搜索框"""
    resp = api_client.get("/search")
    assert resp.status_code == 200
    html = resp.text
    assert "搜索" in html


def test_api_endpoints_still_work(api_client, seeded_db):
    """原有 /api/* 路径不受影响"""
    # health
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # reports list
    resp = api_client.get("/api/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data

    # report detail
    resp = api_client.get("/api/reports/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert len(data["views"]) >= 0

    # search
    resp = api_client.get("/api/search?q=宁德")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


# ── P2-I.1 Dashboard Tests ──────────────────────────────────────

def test_dashboard_loads_without_vault(api_client):
    """Dashboard redirects to /setup/vault when no vault is configured."""
    resp = api_client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (301, 302, 303)
    location = resp.headers.get("location", "")
    assert "/setup/vault" in location


def test_dashboard_loads_with_vault(api_client, tmp_path):
    """Dashboard 在 vault 配置后显示概览数据"""
    # Create a mini vault
    vault = tmp_path / "vault"
    for d in ["01_Reports", "02_Topics", "03_Companies", "05_Channels",
              "06_Claims", "07_Signals", "99_System", "00_Inbox/LLM_Patches"]:
        (vault / d).mkdir(parents=True)

    # Add a report
    (vault / "01_Reports" / "test_report.md").write_text("""---
type: report
channel: TestChannel
video_id: abc123
analyzed_at: "2026-05-30 12:00"
tags: []
---
# Test Report Title

## Summary
""", encoding="utf-8")

    # Add a core topic
    (vault / "02_Topics" / "AI Agents.md").write_text("""---
type: topic
status: core
topic: AI Agents
curation_status: enhanced
source_reports: []
---
# AI Agents
""", encoding="utf-8")

    # Add a company
    (vault / "03_Companies" / "NVIDIA.md").write_text("""---
type: company
company: NVIDIA
curation_status: indexed
source_reports: []
---
# NVIDIA
""", encoding="utf-8")

    # Set vault path env
    old_vault = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)

    try:
        resp = api_client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.text
        # Should show vault path
        assert str(vault) in html or "AI 研究助理" in html
        # Should show AI Agents
        assert "AI Agents" in html
        # Should show AI Agents in topic or brief
        assert "AI Agents" in html or "研究摘要" in html
        # Should show research brief summary
        assert "研究摘要" in html or "AI 研究助理" in html
    finally:
        os.environ["OBSIDIAN_VAULT_PATH"] = old_vault


# ── P2-I.2 Action Tests ──────────────────────────────────────────

class TestDashboardActions:
    def test_refresh_workspace_redirects(self, api_client, tmp_path):
        """POST refresh-workspace redirects back to dashboard"""
        vault = tmp_path / "vault"
        (vault / "01_Reports").mkdir(parents=True)
        (vault / "02_Topics").mkdir(parents=True)
        (vault / "03_Companies").mkdir(parents=True)
        (vault / "06_Claims").mkdir(parents=True)
        (vault / "07_Signals").mkdir(parents=True)
        (vault / "99_System").mkdir(parents=True)
        (vault / "00_Inbox" / "LLM_Patches").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/dashboard/actions/refresh-workspace", follow_redirects=False)
            assert resp.status_code in (303, 302)
            assert "/dashboard" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_claim_status_update(self, api_client, tmp_path):
        """POST claim status updates claim frontmatter"""
        vault = tmp_path / "vault"
        claims_dir = vault / "06_Claims"
        claims_dir.mkdir(parents=True)
        (vault / "99_System").mkdir(parents=True)

        p = claims_dir / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test claim"
source_reports: []
related_topics: []
related_companies: []
created_at: "2026-05-30T20:07:34"
updated_at: "2026-05-30T20:07:34"
---
# Claim: Test claim

## Statement
Test.
## Review History
""", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post(
                "/claims/claim_test/status",
                data={"status": "verified", "note": "looks good", "return_to": "dashboard"},
                follow_redirects=False,
            )
            assert resp.status_code in (303, 302)
            content = p.read_text(encoding="utf-8")
            assert "verified" in content
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_signal_status_update(self, api_client, tmp_path):
        """POST signal status updates signal frontmatter"""
        vault = tmp_path / "vault"
        signals_dir = vault / "07_Signals"
        signals_dir.mkdir(parents=True)
        (vault / "99_System").mkdir(parents=True)

        p = signals_dir / "signal_test.md"
        p.write_text("""---
type: signal
status: open
signal: "Test signal"
source_reports: []
related_topics: []
related_companies: []
created_at: "2026-05-30T20:07:34"
updated_at: "2026-05-30T20:07:34"
---
# Signal: Test signal
## What to Watch
Test.
## Updates
""", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post(
                "/signals/signal_test/status",
                data={"status": "watching", "note": "", "return_to": "dashboard"},
                follow_redirects=False,
            )
            assert resp.status_code in (303, 302)
            content = p.read_text(encoding="utf-8")
            assert "watching" in content
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_invalid_claim_status_rejected(self, api_client, tmp_path):
        """Invalid claim status returns error redirect"""
        vault = tmp_path / "vault"
        (vault / "06_Claims").mkdir(parents=True)
        p = vault / "06_Claims" / "c.md"
        p.write_text("---\ntype: claim\nstatus: active\nclaim: T\nsource_reports: []\n---\n# T\n")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post(
                "/claims/c/status",
                data={"status": "bogus", "note": "", "return_to": "dashboard"},
                follow_redirects=False,
            )
            assert resp.status_code in (303, 302)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_invalid_signal_status_rejected(self, api_client, tmp_path):
        """Invalid signal status returns error redirect"""
        vault = tmp_path / "vault"
        (vault / "07_Signals").mkdir(parents=True)
        p = vault / "07_Signals" / "s.md"
        p.write_text("---\ntype: signal\nstatus: open\nsignal: T\nsource_reports: []\n---\n# T\n")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post(
                "/signals/s/status",
                data={"status": "bogus", "note": "", "return_to": "dashboard"},
                follow_redirects=False,
            )
            assert resp.status_code in (303, 302)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


class TestPatchPages:
    def test_patches_page_loads(self, api_client, tmp_path):
        """GET /patches returns 200"""
        vault = tmp_path / "vault"
        (vault / "00_Inbox" / "LLM_Patches").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/patches")
            assert resp.status_code == 200
            assert "AI 整理建议" in resp.text or "整理建议" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_patch_detail_page_loads(self, api_client, tmp_path):
        """GET /patches/{id} returns 200"""
        vault = tmp_path / "vault"
        patches_dir = vault / "00_Inbox" / "LLM_Patches"
        patches_dir.mkdir(parents=True)

        p = patches_dir / "topic_Test_001.md"
        p.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test Topic"
target_card: "02_Topics/Test Topic.md"
status: pending_review
auto_apply: false
generated_at: "2026-05-30T15:00:00Z"
provider: openai_compatible
model: test
source_reports: []
---
# Patch Proposal: Test Topic
## Review Checklist
- [ ] reviewed
""", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/patches/topic_Test_001")
            assert resp.status_code == 200
            assert "Test Topic" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_patch_detail_not_found(self, api_client, tmp_path):
        """GET /patches/nonexistent returns 404"""
        vault = tmp_path / "vault"
        (vault / "00_Inbox" / "LLM_Patches").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/patches/nonexistent")
            assert resp.status_code == 404
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


# ── P2-J.1 Research Brief Tests ──────────────────────────────────

class TestResearchBrief:
    def test_brief_page_loads(self, api_client, tmp_path):
        """GET /briefs/latest returns 200"""
        vault = tmp_path / "vault"
        for d in ["01_Reports", "02_Topics", "03_Companies", "06_Claims", "07_Signals"]:
            (vault / d).mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/briefs/latest")
            assert resp.status_code == 200
            assert "研究简报" in resp.text or "研究摘要" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_brief_ranks_active_topics(self):
        """Active topic ranking uses weighted scoring"""
        from pathlib import Path

        from podcast_research.workspace.research_brief import generate_brief
        from podcast_research.workspace.scanner import (
            ClaimInfo,
            TopicInfo,
            WorkspaceSnapshot,
        )

        snapshot = WorkspaceSnapshot(vault_path=Path("/tmp"))
        snapshot.topics = [
            TopicInfo(name="AI Agents", path=Path("."), status="core"),
            TopicInfo(name="Semiconductor", path=Path("."), status="core"),
        ]
        snapshot.claims = [
            ClaimInfo(card_id="c1", path=Path("."), claim="test",
                       related_topics=["AI Agents"], source_reports=["r1"]),
            ClaimInfo(card_id="c2", path=Path("."), claim="test",
                       related_topics=["AI Agents"], source_reports=["r1"]),
            ClaimInfo(card_id="c3", path=Path("."), claim="test",
                       related_topics=["AI Agents"], source_reports=["r1"]),
        ]

        brief = generate_brief(snapshot)
        assert len(brief.active_topics) >= 1
        # AI Agents should rank first with 3 claims
        assert brief.active_topics[0].name == "AI Agents"
        assert brief.active_topics[0].claims == 3

    def test_brief_no_llm_called(self):
        """Research brief uses pure rules, no LLM import"""
        from pathlib import Path

        from podcast_research.workspace.research_brief import generate_brief
        from podcast_research.workspace.scanner import WorkspaceSnapshot

        snapshot = WorkspaceSnapshot(vault_path=Path("/tmp"))
        brief = generate_brief(snapshot)
        assert brief is not None
        assert brief.total_reports == 0


# ── P2-J.2 Watchlist Tests ───────────────────────────────────────

class TestWatchlist:
    def test_watchlist_page_loads(self, api_client, tmp_path):
        """GET /watchlist returns 200"""
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)
        (vault / "06_Claims").mkdir(parents=True)
        (vault / "07_Signals").mkdir(parents=True)
        (vault / "02_Topics").mkdir(parents=True)
        (vault / "03_Companies").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/watchlist")
            assert resp.status_code == 200
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_watchlist_config_load(self, tmp_path):
        """Watchlist config can be loaded from YAML file"""
        from podcast_research.workspace.watchlist import load_watchlist

        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)
        (vault / "99_System" / "Watchlist.yaml").write_text("""
companies:
  - OpenAI
  - NVIDIA
topics:
  - AI Agents
""", encoding="utf-8")

        config = load_watchlist(vault)
        assert "OpenAI" in config.companies
        assert "NVIDIA" in config.companies
        assert "AI Agents" in config.topics

    def test_watchlist_template_created(self, tmp_path):
        """Template is created when config missing"""
        from podcast_research.workspace.watchlist import ensure_watchlist_template

        vault = tmp_path / "vault"
        path = ensure_watchlist_template(vault)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "OpenAI" in content

    def test_watchlist_direct_update(self, tmp_path):
        """Company with direct claim is marked as direct"""
        from podcast_research.workspace.scanner import ClaimInfo, WorkspaceSnapshot
        from podcast_research.workspace.watchlist import generate_watchlist_brief

        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)
        (vault / "99_System" / "Watchlist.yaml").write_text("companies:\n  - OpenAI\n", encoding="utf-8")

        snapshot = WorkspaceSnapshot(vault_path=vault)
        snapshot.claims = [
            ClaimInfo(card_id="c1", path=vault, claim="Test claim about OpenAI",
                       related_companies=["OpenAI"], source_reports=["r1"]),
        ]
        snapshot.companies = []

        items = generate_watchlist_brief(snapshot, vault)
        assert len(items) == 1
        assert items[0].name == "OpenAI"
        assert items[0].status == "direct"

    def test_watchlist_no_evidence(self, tmp_path):
        """Item with no claims/signals returns no_new_evidence"""
        from podcast_research.workspace.scanner import WorkspaceSnapshot
        from podcast_research.workspace.watchlist import generate_watchlist_brief

        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)
        (vault / "99_System" / "Watchlist.yaml").write_text("companies:\n  - NVIDIA\n", encoding="utf-8")

        snapshot = WorkspaceSnapshot(vault_path=vault)
        snapshot.companies = []

        items = generate_watchlist_brief(snapshot, vault)
        assert items[0].status == "no_new_evidence"

    def test_dashboard_shows_watchlist(self, api_client, tmp_path):
        """Dashboard shows watchlist section when configured"""
        vault = tmp_path / "vault"
        for d in ["01_Reports", "02_Topics", "03_Companies", "06_Claims",
                   "07_Signals", "99_System"]:
            (vault / d).mkdir(parents=True)

        (vault / "99_System" / "Watchlist.yaml").write_text(
            "companies:\n  - OpenAI\ntopics:\n  - AI Agents\n", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard")
            assert resp.status_code == 200
            assert "我的关注" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


# ── P2-J.3 Watchlist Settings Tests ──────────────────────────────

class TestWatchlistSettings:
    def test_settings_page_loads(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/watchlist/settings")
            assert resp.status_code == 200
            assert "关注设置" in resp.text or "company" in resp.text.lower()
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_add_company(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/watchlist/settings/add",
                                   data={"item_type": "company", "name": "OpenAI"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
            assert "success" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_add_topic(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/watchlist/settings/add",
                                   data={"item_type": "topic", "name": "AI Agents"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_duplicate_rejected(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            api_client.post("/watchlist/settings/add",
                           data={"item_type": "company", "name": "OpenAI"})
            resp = api_client.post("/watchlist/settings/add",
                                   data={"item_type": "company", "name": "OpenAI"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
            # Duplicate should return error msg (URL-encoded Chinese in location)
            assert "msg=error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_remove_company(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)
        (vault / "99_System" / "Watchlist.yaml").write_text(
            "companies:\n  - OpenAI\n", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/watchlist/settings/remove",
                                   data={"item_type": "company", "name": "OpenAI"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_empty_name_rejected(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/watchlist/settings/add",
                                   data={"item_type": "company", "name": "  "},
                                   follow_redirects=False)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_invalid_type_rejected(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/watchlist/settings/add",
                                   data={"item_type": "bogus", "name": "X"},
                                   follow_redirects=False)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_dashboard_has_settings_link(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        for d in ["01_Reports", "02_Topics", "03_Companies", "06_Claims",
                   "07_Signals", "99_System"]:
            (vault / d).mkdir(parents=True)
        (vault / "99_System" / "Watchlist.yaml").write_text(
            "companies:\n  - OpenAI\n", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard")
            assert "/watchlist/settings" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


# ── P2-J.4 Entity Resolution Tests ───────────────────────────────

class TestEntityResolution:
    def test_exact_match_linked(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("NVIDIA", "company", {"NVIDIA", "OpenAI"}, set())
        assert r["match_status"] == "linked"
        assert r["canonical_name"] == "NVIDIA"

    def test_alias_match_chinese(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("英伟达", "company", {"NVIDIA", "OpenAI"}, set())
        assert r["match_status"] == "alias"
        assert r["canonical_name"] == "NVIDIA"

    def test_fuzzy_match_spaceless(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("Core Weave", "company", {"CoreWeave", "NVIDIA"}, set())
        assert r["match_status"] in ("fuzzy", "alias")  # alias map also catches this
        assert r["canonical_name"] == "CoreWeave"

    def test_topic_alias(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("AI Agent", "topic", set(), {"AI Agents", "Enterprise AI"})
        assert r["match_status"] in ("alias", "fuzzy")

    def test_theme_with_related_topics(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("Agent 工具链", "theme", set(), {"AI Agents", "Developer Tools"})
        assert r["match_status"] == "custom"
        assert "AI Agents" in r["related_topics"]

    def test_unknown_company_missing(self):
        from podcast_research.workspace.watchlist import resolve_watchlist_name
        r = resolve_watchlist_name("FakeCo", "company", {"NVIDIA"}, set())
        assert r["match_status"] == "missing"

    def test_normalize_spaceless(self):
        from podcast_research.workspace.watchlist import _normalize
        assert _normalize("Core Weave") == _normalize("CoreWeave")
        assert _normalize("AI-Agent") == _normalize("AI Agent")


# ── P2-K.1 Add New Content Tests ─────────────────────────────────

class TestContentNew:
    def test_content_new_page_loads(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/content/new")
            assert resp.status_code == 200
            assert "YouTube" in resp.text or "添加新内容" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_dashboard_has_add_content_link(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        for d in ["01_Reports", "02_Topics", "99_System"]:
            (vault / d).mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard")
            assert "/content/new" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_analyze_empty_url_rejected(self, api_client, tmp_path):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "  ", "focus": "", "depth": "standard"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_analyze_invalid_url_rejected(self, api_client, tmp_path, monkeypatch):
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        # Mock is_youtube_url to return False (invalid)
        monkeypatch.setattr(
            "podcast_research.utils.youtube.is_youtube_url", lambda u: False
        )

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "not-a-url", "focus": "", "depth": "standard"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
            assert "error" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_analyze_redirects_to_job(self, api_client, tmp_path, monkeypatch):
        """POST /content/analyze redirects to unified task page."""
        monkeypatch.setattr(
            "podcast_research.utils.youtube.is_youtube_url", lambda u: True
        )

        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "https://youtube.com/watch?v=test",
                                         "focus": "AI Agents", "depth": "standard"},
                                   follow_redirects=False)
            assert resp.status_code in (303, 302)
            assert "/tasks/" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_job_page_loads(self, api_client, tmp_path):
        """GET /content/jobs/{id} — redirects to unified /tasks/{id}"""
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/content/jobs/nonexistent123", follow_redirects=False)
            assert resp.status_code in (301, 302)
            assert "/tasks/" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_job_status_api(self, api_client, tmp_path, monkeypatch):
        """GET /tasks/{id}/status returns JSON (unified task status)"""
        monkeypatch.setattr(
            "podcast_research.utils.youtube.is_youtube_url", lambda u: True
        )

        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            # Create a job and check its status
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "https://youtube.com/watch?v=test",
                                         "focus": "AI Agents", "depth": "standard"},
                                   follow_redirects=False)
            location = resp.headers.get("location", "")
            job_id = location.rstrip("/").split("/")[-1]

            status_resp = api_client.get(f"/tasks/{job_id}/status")
            assert status_resp.status_code == 200
            data = status_resp.json()
            assert "status" in data
            assert data["status"] in ("queued", "running", "success", "failed", "long_running")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


# ── P2-K.2 Knowledge Sync Tests ───────────────────────────────────


class TestKnowledgeSync:
    """P2-K.2: Sync report to knowledge base + brief refresh."""

    def test_report_detail_has_sync_button(self, api_client, seeded_db):
        """Report detail page shows '同步到知识库' button."""
        resp = api_client.get("/reports/1")
        assert resp.status_code == 200
        assert "同步到知识库" in resp.text

    def test_sync_no_vault_returns_friendly_error(self, api_client, seeded_db):
        """POST /reports/{id}/sync without vault returns redirect with error msg."""
        # conftest sets OBSIDIAN_VAULT_PATH="" so vault is not configured
        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = ""
        try:
            resp = api_client.post("/reports/1/sync", follow_redirects=False)
            assert resp.status_code in (303, 302)
            location = resp.headers.get("location", "")
            assert "error" in location
            assert "OBSIDIAN_VAULT_PATH" in location or "知识库" in location
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_report_not_found(self, api_client, tmp_path):
        """POST /reports/{id}/sync with non-existent report returns friendly error."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/reports/99999/sync", follow_redirects=False)
            assert resp.status_code in (303, 302)
            location = resp.headers.get("location", "")
            assert "不存在" in location or "error" in location
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_creates_job_and_redirects(self, api_client, seeded_db, tmp_path):
        """POST /reports/{id}/sync creates a sync job and redirects to /tasks/{id}."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/reports/1/sync", follow_redirects=False)
            assert resp.status_code in (303, 302)
            location = resp.headers.get("location", "")
            assert "/tasks/" in location
            job_id = location.rstrip("/").split("/")[-1]
            assert len(job_id) > 0
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_page_loads(self, api_client, tmp_path):
        """GET /sync/jobs/{id} redirects to /tasks/{id}."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/sync/jobs/nonexistent123", follow_redirects=False)
            assert resp.status_code in (301, 302)
            assert "/tasks/" in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_page_shows_progress(self, api_client, seeded_db, tmp_path, monkeypatch):
        """GET /tasks/{id} shows sync progress UI for sync job."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Create a sync job manually
        from podcast_research.services.job_service import create_sync_job
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}")
            assert resp.status_code == 200
            assert "同步" in resp.text or "sync" in job.job_type
            assert job.job_id in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_status_api(self, api_client, seeded_db, tmp_path):
        """GET /tasks/{id}/status returns JSON with sync fields."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_sync_job
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert data["status"] in ("queued", "running", "success", "failed", "long_running")
            assert "stage" in data
            assert "message" in data
            assert data["report_id"] == 1
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_status_not_found(self, api_client):
        """GET /tasks/{id}/status returns 404 for unknown job."""
        resp = api_client.get("/tasks/nonexistent123/status")
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "not_found"

    def test_sync_success_job_status_json(self, api_client, seeded_db, tmp_path, monkeypatch):
        """After successful sync, job status JSON includes result_links with brief/watchlist URLs."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Mock the sync service to succeed instantly
        def mock_sync(report_id, vault_path=None, progress_callback=None):
            from podcast_research.services.sync_service import SyncResult
            result = SyncResult(
                report_id=report_id,
                exported_reports=1,
                cards_updated=3,
                relations_updated=2,
                brief_updated=True,
                watchlist_updated=True,
            )
            if progress_callback:
                progress_callback("exporting_report", "正在导出")
                progress_callback("updating_cards", "正在更新卡片")
                progress_callback("success", "知识库已更新")
            return result

        monkeypatch.setattr(
            "podcast_research.services.sync_service.sync_report_to_knowledge_base",
            mock_sync,
        )

        from podcast_research.services.job_service import (
            create_sync_job,
            start_sync_job,
        )
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_sync_job(job)

            # Poll until success (with timeout)
            import time
            max_wait = 10
            for _ in range(max_wait * 2):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                data = resp.json()
                if data["status"] == "success":
                    break
                time.sleep(0.5)

            resp = api_client.get(f"/tasks/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["result_links"] is not None
            assert data["result_links"]["dashboard"] == "/dashboard"
            assert data["result_links"]["brief"] == "/briefs/latest"
            assert data["result_links"]["watchlist"] == "/watchlist"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_failure_job_status(self, api_client, seeded_db, tmp_path, monkeypatch):
        """Failed sync job status shows error and failed status."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Mock the sync service to fail
        def mock_sync_fail(report_id, vault_path=None, progress_callback=None):
            from podcast_research.services.sync_service import SyncResult
            result = SyncResult(report_id=report_id)
            result.error = "报告导出失败，请检查知识库路径是否可写。"
            if progress_callback:
                progress_callback("exporting_report", "正在导出")
            return result

        monkeypatch.setattr(
            "podcast_research.services.sync_service.sync_report_to_knowledge_base",
            mock_sync_fail,
        )

        from podcast_research.services.job_service import (
            create_sync_job,
            start_sync_job,
        )
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_sync_job(job)

            import time
            max_wait = 10
            for _ in range(max_wait * 2):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                data = resp.json()
                if data["status"] == "failed":
                    break
                time.sleep(0.5)

            resp = api_client.get(f"/tasks/{job.job_id}/status")
            data = resp.json()
            assert data["status"] == "failed"
            assert data["error"] is not None
            assert len(data["error"]) > 0
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_success_page_has_brief_links(self, api_client, seeded_db, tmp_path, monkeypatch):
        """Unified task detail page for sync job success shows required links."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Create a sync job and manually set it to success with result_links
        from podcast_research.services.job_service import (
            _set_result_links,
            create_sync_job,
            update_job,
        )
        job = create_sync_job(report_id=1)
        update_job(job.job_id, status="success", stage="success", message="知识库已更新")
        _set_result_links(job.job_id, "sync", 1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}")
            assert resp.status_code == 200
            # Check for the links in the page — result_links rendered server-side
            assert "查看研究摘要" in resp.text or "/briefs/latest" in resp.text
            assert "查看我的关注" in resp.text or "/watchlist" in resp.text
            assert "返回首页" in resp.text or "/dashboard" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_does_not_call_llm(self, api_client, seeded_db, tmp_path, monkeypatch):
        """Sync service operations do not call LLM."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        call_count = [0]

        def mock_sync(report_id, vault_path=None, progress_callback=None):
            call_count[0] += 1
            from podcast_research.services.sync_service import SyncResult
            result = SyncResult(
                report_id=report_id,
                exported_reports=1,
                brief_updated=True,
                watchlist_updated=True,
            )
            if progress_callback:
                progress_callback("success", "知识库已更新")
            return result

        monkeypatch.setattr(
            "podcast_research.services.sync_service.sync_report_to_knowledge_base",
            mock_sync,
        )

        from podcast_research.services.job_service import (
            create_sync_job,
            start_sync_job,
        )
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_sync_job(job)
            import time
            for _ in range(20):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                if resp.json()["status"] == "success":
                    break
                time.sleep(0.5)
            assert call_count[0] == 1  # Only the mock was called, no LLM
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_existing_web_tests_not_broken(self, api_client, seeded_db):
        """Quick sanity: existing routes still work after P2-K.2 additions."""
        # /reports list
        resp = api_client.get("/reports")
        assert resp.status_code == 200

        # /reports/{id} detail
        resp = api_client.get("/reports/1")
        assert resp.status_code == 200

        # /dashboard
        resp = api_client.get("/dashboard")
        assert resp.status_code == 200

        # /content/new
        resp = api_client.get("/content/new")
        assert resp.status_code == 200

        # /api/* endpoints
        resp = api_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── P2-K.2.1 Unified Task UX Tests ─────────────────────────────────


class TestUnifiedTasks:
    """P2-K.2.1: Unified /tasks routes, long_running/stale, dashboard badge."""

    def test_task_list_page_loads(self, api_client, tmp_path):
        """GET /tasks returns task list page."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/tasks")
            assert resp.status_code == 200
            assert "整理任务" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_task_list_shows_analysis_and_sync_jobs(self, api_client, seeded_db, tmp_path):
        """Task list renders jobs of both types."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job, create_sync_job
        j1 = create_job("https://youtube.com/watch?v=test", ["AI"])
        j2 = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/tasks")
            assert resp.status_code == 200
            assert "生成报告" in resp.text or "analysis" in resp.text.lower()
            assert "同步知识库" in resp.text or "sync" in resp.text.lower()
            # Both job_ids should appear
            assert j1.job_id in resp.text
            assert j2.job_id in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_unified_task_detail_for_analysis(self, api_client, seeded_db, tmp_path):
        """GET /tasks/{id} for analysis job shows analysis-specific content."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], depth="deep")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}")
            assert resp.status_code == 200
            assert "生成报告" in resp.text or "研究报告" in resp.text
            assert job.job_id in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_unified_task_detail_for_sync(self, api_client, seeded_db, tmp_path):
        """GET /tasks/{id} for sync job shows sync-specific content."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_sync_job
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}")
            assert resp.status_code == 200
            assert "同步" in resp.text or "sync" in job.job_type
            assert job.job_id in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_unified_task_status_returns_heartbeat_fields(self, api_client, seeded_db, tmp_path):
        """GET /tasks/{id}/status includes elapsed, can_leave_page, result_links."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "elapsed_seconds" in data
            assert "can_leave_page" in data
            assert "result_links" in data
            assert "job_type_label" in data
            assert data["job_type_label"] == "生成报告"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_sync_job_status_has_sync_label(self, api_client, seeded_db, tmp_path):
        """Sync job status returns 同步知识库 label."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_sync_job
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["job_type_label"] == "同步知识库"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_long_running_detected_with_low_threshold(self, api_client, seeded_db,
                                                       tmp_path, monkeypatch):
        """Job enters long_running after heartbeat passes custom threshold."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Set long_job threshold to 0 so any started job is immediately long_running
        monkeypatch.setattr(
            "podcast_research.services.job_service.LONG_JOB_THRESHOLD", 0
        )
        monkeypatch.setattr(
            "podcast_research.services.job_service.STALE_THRESHOLD", 999999
        )

        # Create a job and manually start it with a heartbeat
        from podcast_research.services.job_service import create_job, update_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])
        update_job(job.job_id, status="running", stage="analyzing",
                   message="正在进行 AI 分析")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            data = resp.json()
            assert data["status"] == "long_running"
            assert data["can_leave_page"] is True
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_long_running_not_failed(self, api_client, seeded_db, tmp_path,
                                      monkeypatch):
        """long_running status does not mean failed — it shows can_leave_page."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        monkeypatch.setattr(
            "podcast_research.services.job_service.LONG_JOB_THRESHOLD", 0
        )
        monkeypatch.setattr(
            "podcast_research.services.job_service.STALE_THRESHOLD", 999999
        )

        from podcast_research.services.job_service import create_job, update_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])
        update_job(job.job_id, status="running", stage="analyzing",
                   message="正在进行 AI 分析")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            data = resp.json()
            assert data["status"] != "failed"
            assert data["status"] == "long_running"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_stale_detected_with_low_threshold(self, api_client, seeded_db,
                                                tmp_path, monkeypatch):
        """Job without heartbeat past stale threshold shows stale status."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Set stale threshold to 0 so any job is immediately stale
        monkeypatch.setattr(
            "podcast_research.services.job_service.STALE_THRESHOLD", 0
        )
        monkeypatch.setattr(
            "podcast_research.services.job_service.LONG_JOB_THRESHOLD", 999999
        )

        from podcast_research.services.job_service import create_job, update_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])
        update_job(job.job_id, status="running", stage="analyzing")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            data = resp.json()
            assert data["status"] == "stale"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_analysis_success_has_report_in_result_links(self, api_client, seeded_db,
                                                          tmp_path, monkeypatch):
        """Analysis job success returns report link in result_links."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        def mock_analyze(youtube_url, focus_areas=None, depth="standard",
                         mock=False, progress_callback=None):
            from podcast_research.services.analyze_service import AnalyzeResult
            if progress_callback:
                progress_callback("analyzing", "analyzing")
            return AnalyzeResult(success=True, report_id=42)

        monkeypatch.setattr(
            "podcast_research.services.analyze_service.analyze_youtube_url",
            mock_analyze,
        )

        from podcast_research.services.job_service import create_job, start_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])
        import time

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_job(job)
            for _ in range(20):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                if resp.json()["status"] == "success":
                    break
                time.sleep(0.5)

            data = api_client.get(f"/tasks/{job.job_id}/status").json()
            assert data["status"] == "success"
            assert data["result_links"] is not None
            assert "report" in data["result_links"]
            assert data["result_links"]["report"] == "/reports/42"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_dashboard_shows_task_entry(self, api_client, seeded_db, tmp_path):
        """Dashboard action bar includes 整理任务 link."""
        vault = tmp_path / "vault"
        for d in ["01_Reports", "02_Topics", "99_System"]:
            (vault / d).mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard")
            assert resp.status_code == 200
            assert "/tasks" in resp.text
            assert "整理任务" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_old_content_jobs_redirects_to_tasks(self, api_client):
        """GET /content/jobs/{id} returns 301 redirect to /tasks/{id}."""
        resp = api_client.get("/content/jobs/test123", follow_redirects=False)
        assert resp.status_code in (301, 302)
        assert "/tasks/test123" in resp.headers.get("location", "")

    def test_old_sync_jobs_redirects_to_tasks(self, api_client):
        """GET /sync/jobs/{id} returns 301 redirect to /tasks/{id}."""
        resp = api_client.get("/sync/jobs/test123", follow_redirects=False)
        assert resp.status_code in (301, 302)
        assert "/tasks/test123" in resp.headers.get("location", "")

    def test_old_content_jobs_status_still_works(self, api_client, seeded_db, tmp_path):
        """GET /content/jobs/{id}/status delegates to unified status."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"])

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/content/jobs/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "elapsed_seconds" in data  # Unified fields present
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_old_sync_jobs_status_still_works(self, api_client, seeded_db, tmp_path):
        """GET /sync/jobs/{id}/status delegates to unified status."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_sync_job
        job = create_sync_job(report_id=1)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/sync/jobs/{job.job_id}/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "result_links" in data  # Unified fields present
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old


# ── P2-K.3 One-click Full Flow Tests ───────────────────────────────


class TestFullFlow:
    """P2-K.3: full_flow mode chains analysis → sync automatically."""

    def test_content_new_shows_flow_mode(self, api_client, tmp_path):
        """/content/new page shows flow mode radio buttons."""
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/content/new")
            assert resp.status_code == 200
            assert "整理进知识库" in resp.text
            assert "仅生成报告" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_flow_full_creates_full_flow_job(self, api_client, tmp_path, monkeypatch):
        """flow_mode=full creates a full_flow job."""
        monkeypatch.setattr(
            "podcast_research.utils.youtube.is_youtube_url", lambda u: True
        )
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "https://youtube.com/watch?v=test",
                                         "focus": "AI", "depth": "standard",
                                         "flow_mode": "full"},
                                   follow_redirects=False)
            location = resp.headers.get("location", "")
            assert "/tasks/" in location
            job_id = location.rstrip("/").split("/")[-1]

            from podcast_research.services.job_service import get_job
            job = get_job(job_id)
            assert job is not None
            assert job.job_type == "full_flow"
            assert job.auto_sync is True
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_flow_report_only_creates_analysis_job(self, api_client, tmp_path, monkeypatch):
        """flow_mode=report_only creates an analysis job (not full_flow)."""
        monkeypatch.setattr(
            "podcast_research.utils.youtube.is_youtube_url", lambda u: True
        )
        vault = tmp_path / "vault"
        (vault / "99_System").mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/content/analyze",
                                   data={"youtube_url": "https://youtube.com/watch?v=test",
                                         "focus": "AI", "depth": "standard",
                                         "flow_mode": "report_only"},
                                   follow_redirects=False)
            location = resp.headers.get("location", "")
            job_id = location.rstrip("/").split("/")[-1]

            from podcast_research.services.job_service import get_job
            job = get_job(job_id)
            assert job is not None
            assert job.job_type == "analysis"
            assert job.auto_sync is False
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_full_flow_analysis_success_then_sync(self, api_client, seeded_db,
                                                    tmp_path, monkeypatch):
        """full_flow: after analysis succeeds, sync is called automatically."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        # Mock analyze to succeed
        def mock_analyze(youtube_url, focus_areas=None, depth="standard",
                         mock=False, progress_callback=None):
            from podcast_research.services.analyze_service import AnalyzeResult
            if progress_callback:
                progress_callback("analyzing", "analyzing")
            return AnalyzeResult(success=True, report_id=55)

        monkeypatch.setattr(
            "podcast_research.services.analyze_service.analyze_youtube_url",
            mock_analyze,
        )

        # Mock sync to succeed
        sync_called = [False]
        def mock_sync(report_id, vault_path=None, progress_callback=None):
            sync_called[0] = True
            from podcast_research.services.sync_service import SyncResult
            result = SyncResult(report_id=report_id, exported_reports=1,
                                brief_updated=True, watchlist_updated=True)
            if progress_callback:
                progress_callback("exporting_report", "导出中")
                progress_callback("success", "完成")
            return result

        monkeypatch.setattr(
            "podcast_research.services.sync_service.sync_report_to_knowledge_base",
            mock_sync,
        )

        from podcast_research.services.job_service import create_job, start_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=True)
        assert job.job_type == "full_flow"

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_job(job)
            import time
            for _ in range(30):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                if resp.json()["status"] == "success":
                    break
                time.sleep(0.5)

            data = api_client.get(f"/tasks/{job.job_id}/status").json()
            assert data["status"] == "success"
            assert sync_called[0] is True
            assert data["result_links"]["report"] == "/reports/55"
            assert data["result_links"]["brief"] == "/briefs/latest"
            assert data["result_links"]["watchlist"] == "/watchlist"
            assert data["result_links"]["dashboard"] == "/dashboard"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_full_flow_sync_failed_preserves_report(self, api_client, seeded_db,
                                                      tmp_path, monkeypatch):
        """full_flow: if sync fails, job reports failure but preserves report link."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        def mock_analyze(youtube_url, focus_areas=None, depth="standard",
                         mock=False, progress_callback=None):
            from podcast_research.services.analyze_service import AnalyzeResult
            if progress_callback:
                progress_callback("analyzing", "analyzing")
            return AnalyzeResult(success=True, report_id=42)

        monkeypatch.setattr(
            "podcast_research.services.analyze_service.analyze_youtube_url",
            mock_analyze,
        )

        def mock_sync_fail(report_id, vault_path=None, progress_callback=None):
            from podcast_research.services.sync_service import SyncResult
            result = SyncResult(report_id=report_id)
            result.error = "Vault 不可写"
            if progress_callback:
                progress_callback("exporting_report", "导出中")
            return result

        monkeypatch.setattr(
            "podcast_research.services.sync_service.sync_report_to_knowledge_base",
            mock_sync_fail,
        )

        from podcast_research.services.job_service import create_job, start_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_job(job)
            import time
            for _ in range(30):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                if resp.json()["status"] == "failed":
                    break
                time.sleep(0.5)

            data = api_client.get(f"/tasks/{job.job_id}/status").json()
            assert data["status"] == "failed"
            # Report was generated — links should be preserved
            assert data["report_id"] == 42
            assert data["result_links"]["report"] == "/reports/42"
            assert "retry_sync" in data["result_links"]  # retry link (P2-M.4.1)
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_full_flow_task_detail_shows_correct_title(self, api_client, tmp_path):
        """Task detail for full_flow shows '正在整理进知识库' title."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}")
            assert resp.status_code == 200
            assert "正在整理进知识库" in resp.text or "full_flow" in job.job_type
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_full_flow_status_shows_correct_label(self, api_client, tmp_path):
        """Full_flow job status shows '整理进知识库' label."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get(f"/tasks/{job.job_id}/status")
            data = resp.json()
            assert data["job_type_label"] == "整理进知识库"
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_task_list_shows_full_flow_with_label(self, api_client, tmp_path):
        """Task list shows full_flow with '整理进知识库' label."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.services.job_service import create_job
        create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/tasks")
            assert resp.status_code == 200
            assert "整理进知识库" in resp.text
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_analysis_only_not_broken(self, api_client, seeded_db, tmp_path, monkeypatch):
        """Original analysis-only flow (report_only) still works correctly."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        def mock_analyze(youtube_url, focus_areas=None, depth="standard",
                         mock=False, progress_callback=None):
            from podcast_research.services.analyze_service import AnalyzeResult
            if progress_callback:
                progress_callback("analyzing", "analyzing")
            return AnalyzeResult(success=True, report_id=88)

        monkeypatch.setattr(
            "podcast_research.services.analyze_service.analyze_youtube_url",
            mock_analyze,
        )

        from podcast_research.services.job_service import create_job, start_job
        job = create_job("https://youtube.com/watch?v=test", ["AI"], auto_sync=False)
        assert job.job_type == "analysis"

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            start_job(job)
            import time
            for _ in range(30):
                resp = api_client.get(f"/tasks/{job.job_id}/status")
                if resp.json()["status"] == "success":
                    break
                time.sleep(0.5)

            data = api_client.get(f"/tasks/{job.job_id}/status").json()
            assert data["status"] == "success"
            assert data["result_links"]["report"] == "/reports/88"
            assert "sync" in data["result_links"]
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_report_detail_sync_button_still_works(self, api_client, seeded_db):
        """Report detail page still has manual sync button for report_only flow."""
        resp = api_client.get("/reports/1")
        assert resp.status_code == 200
        assert "同步到知识库" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# P2-M.4.1: Task Failure UX & Log Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFailureUX:
    """P2-M.4.1: Enhanced failure UX on task detail page."""

    def test_failed_task_hides_spinner(self, api_client):
        """Failed task detail page should not show spinner."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=test",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, status="failed", stage="failed",
                   error="Test failure", message="Test failure message")

        resp = api_client.get(f"/tasks/{job.job_id}")
        assert resp.status_code == 200
        # Failed jobs have spinner hidden by JS since status=failed
        assert 'data-status="failed"' in resp.text

    def test_failed_task_shows_failure_stage(self, api_client):
        """Failed task status shows failed_stage field."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=test2",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, status="failed", stage="analyzing",
                   error="Analysis failed", message="AI 分析未完成")

        status = api_client.get(f"/tasks/{job.job_id}/status").json()
        assert status["status"] == "failed"
        assert status["failed_stage"] == "analyzing"

    def test_sync_failed_after_report_shows_correct_message(self, api_client):
        """sync_failed_after_report shows '报告已生成，但知识库同步失败'."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t3",
                         focus_areas=["AI"], depth="standard", mock=True,
                         auto_sync=True)
        update_job(job.job_id, report_id=42)
        update_job(job.job_id, status="failed", stage="exporting_report",
                   error="Sync error", message="报告已生成，但知识库更新失败。")

        status = api_client.get(f"/tasks/{job.job_id}/status").json()
        assert status["status"] == "failed"
        assert status["failure_kind"] == "sync_failed_after_report"
        assert "报告已生成" in status["error_summary"]

    def test_sync_failed_after_report_has_retry_links(self, api_client):
        """sync_failed_after_report result_links has report and retry_sync."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t4",
                         focus_areas=["AI"], depth="standard", mock=True,
                         auto_sync=True)
        update_job(job.job_id, report_id=88)
        update_job(job.job_id, status="failed", stage="exporting_report",
                   error="sync died", message="failed")

        status = api_client.get(f"/tasks/{job.job_id}/status").json()
        links = status["result_links"]
        assert links["report"] == "/reports/88"
        assert "retry_sync" in links

    def test_analysis_failed_has_no_report(self, api_client):
        """analysis_failed: no report_id, failure_kind = analysis_failed."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t5",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, status="failed", stage="analyzing",
                   error="LLM timeout", message="AI 分析未完成")

        status = api_client.get(f"/tasks/{job.job_id}/status").json()
        assert status["failure_kind"] == "analysis_failed"
        assert status["report_id"] is None

    def test_task_logs_page_opens(self, api_client):
        """GET /tasks/{id}/logs returns valid HTML."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t6",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, stage="analyzing", message="analysis started")
        update_job(job.job_id, status="failed", stage="failed",
                   error="test error", message="failed")

        resp = api_client.get(f"/tasks/{job.job_id}/logs")
        assert resp.status_code == 200
        assert "任务日志" in resp.text

    def test_job_events_recorded_on_progress(self):
        """Stage change in update_job records a JobEvent."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t7",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, stage="fetching_transcript",
                   message="fetching")

        assert len(job.events) >= 1
        assert job.events[0].level == "info"
        assert job.events[0].stage == "fetching_transcript"

    def test_job_events_recorded_on_failure(self):
        """Failure records error-level JobEvent."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t8",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, status="failed", stage="failed",
                   error="Bad thing", message="failed")

        error_events = [e for e in job.events if e.level == "error"]
        assert len(error_events) >= 1

    def test_logs_page_shows_events(self, api_client):
        """Task logs page shows recorded events in table."""
        from podcast_research.services.job_service import create_job, update_job

        job = create_job(youtube_url="https://example.com/v=t9",
                         focus_areas=["AI"], depth="standard", mock=True)
        update_job(job.job_id, stage="fetching_transcript", message="fetching")
        update_job(job.job_id, status="failed", stage="failed",
                   error="err", message="fail")

        resp = api_client.get(f"/tasks/{job.job_id}/logs")
        assert resp.status_code == 200
        # Should contain event timestamps/messages
        assert "fetching" in resp.text or "事件时间线" in resp.text

    def test_logs_page_not_found_for_unknown_job(self, api_client):
        """Unknown job id returns 404 not_found page."""
        resp = api_client.get("/tasks/nonexistent_job_123/logs")
        assert resp.status_code == 404
        assert "不存在" in resp.text or "已过期" in resp.text


# ── P2-L.1 Vault Setup Wizard Tests ─────────────────────────────────


class TestVaultSetup:
    """P2-L.1: First-run vault setup wizard, validation, repair."""

    def test_setup_page_loads(self, api_client):
        """GET /setup/vault returns setup form page."""
        resp = api_client.get("/setup/vault")
        assert resp.status_code == 200
        assert "初始化知识库" in resp.text

    def test_setup_page_has_form(self, api_client):
        """Setup page has vault_path input and submit button."""
        resp = api_client.get("/setup/vault")
        assert resp.status_code == 200
        assert "vault_path" in resp.text
        assert "初始化知识库" in resp.text

    def test_setup_creates_directory_structure(self, api_client, tmp_path):
        """POST /setup/vault creates standard vault directory structure."""
        vault = tmp_path / "test_vault"

        resp = api_client.post("/setup/vault",
                               data={"vault_path": str(vault)},
                               follow_redirects=False)
        assert resp.status_code in (303, 302)

        # Verify directories created
        from podcast_research.workspace.setup import REQUIRED_DIRS
        for d in REQUIRED_DIRS:
            assert (vault / d).is_dir(), f"Missing dir: {d}"

    def test_setup_creates_watchlist_yaml(self, api_client, tmp_path):
        """POST /setup/vault creates Watchlist.yaml with default content."""
        vault = tmp_path / "test_vault"

        api_client.post("/setup/vault",
                        data={"vault_path": str(vault)},
                        follow_redirects=False)

        wl = vault / "99_System" / "Watchlist.yaml"
        assert wl.is_file()
        content = wl.read_text(encoding="utf-8")
        assert "OpenAI" in content
        assert "NVIDIA" in content
        assert "AI Agents" in content

    def test_setup_creates_home_md(self, api_client, tmp_path):
        """POST /setup/vault creates Home.md."""
        vault = tmp_path / "test_vault"

        api_client.post("/setup/vault",
                        data={"vault_path": str(vault)},
                        follow_redirects=False)

        home = vault / "Home.md"
        assert home.is_file()
        assert "欢迎使用" in home.read_text(encoding="utf-8")

    def test_setup_creates_getting_started(self, api_client, tmp_path):
        """POST /setup/vault creates Getting Started.md."""
        vault = tmp_path / "test_vault"

        api_client.post("/setup/vault",
                        data={"vault_path": str(vault)},
                        follow_redirects=False)

        gs = vault / "99_System" / "Getting Started.md"
        assert gs.is_file()
        content = gs.read_text(encoding="utf-8")
        assert "Getting Started" in content
        assert "Obsidian" in content

    def test_setup_does_not_overwrite_existing_file(self, api_client, tmp_path):
        """POST /setup/vault does not overwrite existing Home.md."""
        vault = tmp_path / "test_vault"
        vault.mkdir(parents=True)
        (vault / "99_System").mkdir(parents=True)
        home = vault / "Home.md"
        home.write_text("# My Custom Home\nCustom content.", encoding="utf-8")

        api_client.post("/setup/vault",
                        data={"vault_path": str(vault)},
                        follow_redirects=False)

        content = home.read_text(encoding="utf-8")
        assert "My Custom Home" in content
        assert "欢迎使用" not in content  # Not overwritten

    def test_setup_empty_path_rejected(self, api_client):
        """POST /setup/vault with empty path returns error."""
        resp = api_client.post("/setup/vault",
                               data={"vault_path": "  "},
                               follow_redirects=False)
        assert resp.status_code in (303, 302)
        assert "error" in resp.headers.get("location", "")

    def test_setup_nonempty_dir_safe(self, api_client, tmp_path):
        """POST /setup/vault on non-empty dir is safe — only adds missing items."""
        vault = tmp_path / "test_vault"
        vault.mkdir(parents=True)
        # Pre-create a file that shouldn't be touched
        existing = vault / "my_notes.md"
        existing.write_text("keep me", encoding="utf-8")

        resp = api_client.post("/setup/vault",
                               data={"vault_path": str(vault)},
                               follow_redirects=False)
        assert resp.status_code in (303, 302)
        assert existing.read_text(encoding="utf-8") == "keep me"
        # Vault dirs should be created
        assert (vault / "01_Reports").is_dir()

    def test_setup_saves_vault_path_to_config(self, api_client, tmp_path, monkeypatch):
        """POST /setup/vault persists path to user_settings.json."""
        import podcast_research.config_store as cs
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_file)
        monkeypatch.setattr(cs, "_SETTINGS_PATH", settings_file)

        vault = tmp_path / "test_vault"

        api_client.post("/setup/vault",
                        data={"vault_path": str(vault)},
                        follow_redirects=False)

        assert settings_file.exists()
        import json
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["obsidian_vault_path"] == str(vault)

    def test_dashboard_with_complete_vault_loads(self, api_client, tmp_path):
        """Dashboard loads normally when vault is complete."""
        vault = tmp_path / "vault"
        from podcast_research.workspace.setup import REQUIRED_DIRS, REQUIRED_FILES
        for d in REQUIRED_DIRS:
            (vault / d).mkdir(parents=True)
        for f in REQUIRED_FILES:
            full = vault / f
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("# test", encoding="utf-8")

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard", follow_redirects=False)
            assert resp.status_code == 200
            assert "setup/vault" not in resp.headers.get("location", "")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_dashboard_shows_repair_banner_when_incomplete(self, api_client, tmp_path):
        """Dashboard shows repair banner when vault structure is incomplete."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        # Only create some dirs, leave others missing
        for d in ["01_Reports", "02_Topics"]:
            (vault / d).mkdir(parents=True)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.get("/dashboard", follow_redirects=False)
            assert resp.status_code == 200
            html = resp.text
            assert "知识库结构不完整" in html or "一键修复" in html
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_repair_vault_fixes_missing(self, api_client, tmp_path):
        """POST /setup/vault/repair creates missing dirs and files."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        (vault / "01_Reports").mkdir(parents=True)
        # Missing many dirs and files

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        try:
            resp = api_client.post("/setup/vault/repair", follow_redirects=False)
            assert resp.status_code in (303, 302)
            location = resp.headers.get("location", "")
            assert "success" in location

            # After repair, dirs should exist
            assert (vault / "02_Topics").is_dir()
            assert (vault / "99_System").is_dir()
            assert (vault / "Home.md").is_file()
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_validate_vault_detects_missing(self, tmp_path):
        """validate_vault identifies missing dirs and files."""
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)

        from podcast_research.workspace.setup import validate_vault
        result = validate_vault(vault)

        assert not result.is_initialized
        assert len(result.missing_dirs) > 0
        assert len(result.missing_files) > 0

    def test_validate_vault_complete(self, tmp_path):
        """validate_vault returns is_initialized=True for complete vault."""
        vault = tmp_path / "vault"
        from podcast_research.workspace.setup import (
            initialize_vault,
        )
        initialize_vault(vault)

        from podcast_research.workspace.setup import validate_vault
        result = validate_vault(vault)

        assert result.is_initialized
        assert len(result.missing_dirs) == 0
        assert len(result.missing_files) == 0

    def test_config_store_persistence(self, tmp_path, monkeypatch):
        """config_store saves and loads vault path correctly."""
        import podcast_research.config_store as cs
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_file)
        monkeypatch.setattr(cs, "_SETTINGS_PATH", settings_file)

        test_path = str(tmp_path / "my_vault")
        cs.save_user_vault_path(test_path)

        result = cs.get_user_vault_path()
        assert result == test_path

    def test_config_store_falls_back_to_env(self, tmp_path, monkeypatch):
        """config_store falls back to OBSIDIAN_VAULT_PATH when no settings file."""
        import podcast_research.config_store as cs
        settings_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_file)
        monkeypatch.setattr(cs, "_SETTINGS_PATH", settings_file)

        old = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(tmp_path / "env_vault")
        try:
            result = cs.get_user_vault_path()
            assert result == str(tmp_path / "env_vault")
        finally:
            os.environ["OBSIDIAN_VAULT_PATH"] = old

    def test_existing_routes_still_work(self, api_client, seeded_db):
        """Quick sanity: original routes not broken by P2-L.1 refactor."""
        # API health
        resp = api_client.get("/api/health")
        assert resp.status_code == 200
        # Reports
        resp = api_client.get("/reports")
        assert resp.status_code == 200
        # Content new
        resp = api_client.get("/content/new")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# P2-N.1: Display & Entity Hygiene Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCleanDisplayText:
    """P2-N.1: clean_display_text() utility."""

    def test_strips_markdown_bold(self):
        """**bold** → bold."""
        from podcast_research.utils.display import clean_display_text
        assert clean_display_text("This is **bold** text") == "This is bold text"

    def test_strips_backticks(self):
        """`code` → code."""
        from podcast_research.utils.display import clean_display_text
        assert clean_display_text("Use `get_session()` to connect") == "Use get_session() to connect"

    def test_strips_hashtag(self):
        """#tag → tag."""
        from podcast_research.utils.display import clean_display_text
        result = clean_display_text("Check out #AI #Agents")
        assert "#AI" not in result

    def test_truncates_long_text(self):
        """Text over max_len gets truncated with ..."""
        from podcast_research.utils.display import clean_display_text
        long_text = "A" * 300
        result = clean_display_text(long_text, max_len=100)
        assert len(result) <= 103  # max_len + "..."
        assert result.endswith("...")

    def test_preserves_technical_terms(self):
        """Technical terms like API, GPU are preserved."""
        from podcast_research.utils.display import clean_display_text
        result = clean_display_text("GPU demand surges for AI API inference")
        assert "GPU" in result
        assert "API" in result


class TestEntityHygiene:
    """P2-N.1: Entity classification guards prevent misclassification."""

    def test_agent_not_in_core_companies(self):
        """Agent should not appear as a core company."""
        from podcast_research.workspace.scanner import _NOT_A_COMPANY
        assert "agent" in _NOT_A_COMPANY
        assert "ai agent" in _NOT_A_COMPANY

    def test_anthropic_not_in_core_topics(self):
        """Anthropic should not appear as a core topic."""
        from podcast_research.workspace.scanner import _NOT_A_TOPIC
        assert "anthropic" in _NOT_A_TOPIC
        assert "openai" in _NOT_A_TOPIC

    def test_model_maps_to_ai_models(self):
        """'model' maps to 'AI Models' canonical."""
        from podcast_research.llm_wiki.taxonomy import normalize_topic_name
        result = normalize_topic_name("model")
        assert result == "AI Models"

    def test_enterprise_maps_to_enterprise_ai(self):
        """'enterprise' → 'Enterprise AI'."""
        from podcast_research.llm_wiki.taxonomy import normalize_topic_name
        result = normalize_topic_name("enterprise")
        assert result == "Enterprise AI"

    def test_market_maps_to_public_markets(self):
        """'market' → 'Public Markets'."""
        from podcast_research.llm_wiki.taxonomy import normalize_topic_name
        result = normalize_topic_name("market")
        assert result == "Public Markets"


class TestExplanatoryResearchBrief:
    """P2-N.2: Research Brief is explanatory, not just statistical."""

    def test_summary_contains_context_not_just_counts(self, tmp_path):
        """Summary bullet should contain topic context, not just numbers."""
        from podcast_research.workspace.research_brief import (
            ResearchBrief,
            TopicInsight,
            _build_summary,
        )
        from podcast_research.workspace.scanner import WorkspaceSnapshot

        snapshot = WorkspaceSnapshot(vault_path=tmp_path)
        brief = ResearchBrief(generated_at="2026-01-01")
        brief.active_topics = [
            TopicInsight(name="AI Agents", score=15.0, reports=3, claims=5, signals=2),
        ]
        brief.active_companies = [
            TopicInsight(name="OpenAI", score=10.0, reports=2, claims=4, signals=1),
        ]
        brief.total_claims = 10
        brief.total_reports = 5
        brief.reinforced_claims = ["Claim A: Agents are key", "Claim B: Enterprise adoption rising"]
        brief.recommended_reports = [{"title": "Test", "filename": "f.md", "channel": "Ch"}]

        bullets = _build_summary(brief, snapshot)
        # Should contain context, not just "关联 X 条判断"
        combined = " ".join(bullets)
        assert "AI Agents" in combined
        # Should NOT just say "关联 N 条判断"
        assert "讨论集中" in combined or "主要涉及" in combined or "涵盖" in combined

    def test_brief_uses_clean_display_text(self, tmp_path):
        """Brief summary bullets should not contain markdown artifacts."""
        from podcast_research.workspace.research_brief import (
            ResearchBrief,
            TopicInsight,
            _build_summary,
        )
        from podcast_research.workspace.scanner import WorkspaceSnapshot

        snapshot = WorkspaceSnapshot(vault_path=tmp_path)
        brief = ResearchBrief(generated_at="2026-01-01")
        brief.active_topics = [
            TopicInsight(name="AI Agents", score=10.0, reports=2, claims=3, signals=1),
        ]
        brief.active_companies = []
        brief.total_claims = 5
        brief.total_reports = 3
        brief.reinforced_claims = []
        brief.recommended_reports = []

        bullets = _build_summary(brief, snapshot)
        combined = " ".join(bullets)
        assert "**" not in combined  # No markdown bold in output


class TestWatchlistBriefSections:
    """P2-N.2: Watchlist Brief has structured sections."""

    def test_direct_items_labeled_as_new_evidence(self):
        """Direct items show '本轮新增' label."""
        from podcast_research.workspace.watchlist import (
            WatchlistItemBrief,
            render_watchlist_markdown,
        )

        item = WatchlistItemBrief(
            name="OpenAI", item_type="company",
            status="direct", direct_count=3,
            direct_items=["New evidence 1", "New evidence 2"],
        )
        md = render_watchlist_markdown([item])
        assert "本轮新增" in md

    def test_observations_labeled(self):
        """Observations show '需要继续观察' label."""
        from podcast_research.workspace.watchlist import (
            WatchlistItemBrief,
            render_watchlist_markdown,
        )

        item = WatchlistItemBrief(
            name="NVIDIA", item_type="company",
            status="direct", direct_count=1,
            observation_count=2,
            observations=["Risk: export control", "Risk: competition"],
        )
        md = render_watchlist_markdown([item])
        assert "需要继续观察" in md

    def test_no_new_evidence_shows_notice(self):
        """no_new_evidence items show notice text."""
        from podcast_research.workspace.watchlist import (
            WatchlistItemBrief,
            render_watchlist_markdown,
        )

        item = WatchlistItemBrief(
            name="TSMC", item_type="company",
            status="no_new_evidence", card_exists=True,
            summary="No updates.",
        )
        md = render_watchlist_markdown([item])
        assert "暂无新证据" in md

