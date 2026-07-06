"""P2-N.4.4: Canonicalization and actionability tests."""

from pathlib import Path

# ── Vault helpers ────────────────────────────────────────────────────

def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for d in ["01_Reports", "02_Topics", "03_Companies",
              "06_Claims", "07_Signals", "99_System"]:
        (vault / d).mkdir(parents=True)
    return vault


def _add_claim(vault: Path, card_id: str, *, status="active",
               claim_text="Test claim", source_reports=None,
               related_topics=None, related_companies=None,
               quality="", granularity="") -> Path:
    p = vault / "06_Claims" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f'  - "{s}"' for s in sr) if sr else "  []"
    rt = related_topics or []
    rt_yaml = "\n".join(f'  - {t}' for t in rt) if rt else "  []"
    rc = related_companies or []
    rc_yaml = "\n".join(f'  - {c}' for c in rc) if rc else "  []"
    q_line = f'quality: "{quality}"\n' if quality else ""
    g_line = f'granularity: "{granularity}"\n' if granularity else ""
    p.write_text(f"""---
type: claim
status: {status}
claim: "{claim_text}"
{q_line}{g_line}source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
---
# Claim: {claim_text}
""", encoding="utf-8")
    return p


def _add_signal(vault: Path, card_id: str, *, status="open",
                signal_text="Test signal", source_reports=None,
                related_topics=None, related_companies=None,
                tracking_status="") -> Path:
    p = vault / "07_Signals" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f'  - "{s}"' for s in sr) if sr else "  []"
    rt = related_topics or []
    rt_yaml = "\n".join(f'  - {t}' for t in rt) if rt else "  []"
    rc = related_companies or []
    rc_yaml = "\n".join(f'  - {c}' for c in rc) if rc else "  []"
    ts_line = f'tracking_status: "{tracking_status}"\n' if tracking_status else ""
    p.write_text(f"""---
type: signal
status: {status}
signal: "{signal_text}"
{ts_line}source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
---
# Signal: {signal_text}
""", encoding="utf-8")
    return p


# ── Normalization tests ──────────────────────────────────────────────

class TestNormalization:
    """Text normalization strips markdown, hashtags, boilerplate."""

    def test_strips_bold_markdown(self):
        from signalvault.workspace.canonicalize import normalize_claim_text
        result = normalize_claim_text("**AI agents are transforming enterprise**")
        assert "**" not in result
        assert "ai agents are transforming enterprise" in result

    def test_strips_hashtags(self):
        from signalvault.workspace.canonicalize import normalize_claim_text
        result = normalize_claim_text("AI agents transform enterprise #ui #agents #human")
        assert "#ui" not in result
        assert "#agents" not in result
        assert "#human" not in result
        assert "ai agents transform enterprise" in result

    def test_strips_trailing_tag_fragment(self):
        from signalvault.workspace.canonicalize import normalize_claim_text
        result = normalize_claim_text("AI agents transform enterprise `#ui #agents")
        assert "`" not in result
        assert "#ui" not in result

    def test_strips_wiki_links(self):
        from signalvault.workspace.canonicalize import normalize_text
        result = normalize_text("[[NVIDIA]] releases new [[AI Models|model]]")
        assert "[[" not in result
        assert "nvidia" in result
        assert "model" in result

    def test_normalizes_cjk_punctuation(self):
        from signalvault.workspace.canonicalize import normalize_text
        result = normalize_text("AI技术，正在改变。投资方向；重要。")
        assert "，" not in result
        assert "。" not in result
        assert "；" not in result

    def test_fingerprint_stable_after_normalization(self):
        from signalvault.workspace.canonicalize import (
            claim_fingerprint,
        )
        text1 = "**AI agents are transforming enterprise workflows with automation** `#ui #agents"
        text2 = "AI agents are transforming enterprise workflows with automation"
        fp1 = claim_fingerprint(text1)
        fp2 = claim_fingerprint(text2)
        assert fp1 == fp2

    def test_fingerprint_diff_for_different_claims(self):
        from signalvault.workspace.canonicalize import claim_fingerprint
        fp1 = claim_fingerprint("NVIDIA GPU supply chain constrained")
        fp2 = claim_fingerprint("OpenAI releases GPT-5 with agent capabilities")
        assert fp1 != fp2


# ── Duplicate grouping tests ─────────────────────────────────────────

class TestDuplicateGrouping:
    """Canonical dedup groups markdown-variant duplicates."""

    def test_bold_vs_plain_grouped_together(self, tmp_path):
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="**AI agents are transforming enterprise workflows with automation**",
                   source_reports=["r1", "r2"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="AI agents are transforming enterprise workflows with automation",
                   source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        assert len(groups) == 1
        assert groups[0].group_size == 2

    def test_different_hashtags_grouped_together(self, tmp_path):
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="ChatGPT succeeds via UI plus model intelligence #ui #agents",
                   source_reports=["r1", "r2"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="ChatGPT succeeds via UI plus model intelligence #ui #agents #human-computer-interaction",
                   source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        # Same core text, different trailing hashtags → same group
        assert len(groups) == 1

    def test_distinct_claims_separate_groups(self, tmp_path):
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="NVIDIA GPU supply constrained",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="OpenAI releases GPT-5 with agents",
                   source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        assert len(groups) == 2

    def test_canonical_selects_more_source_reports(self, tmp_path):
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="AI agents transform enterprise",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="**AI agents transform enterprise**",
                   source_reports=["r1", "r2", "r3"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        assert len(groups) == 1
        # claim_b has 3 source_reports vs 1 → should be canonical
        assert groups[0].canonical.card_id == "claim_b"

    def test_duplicate_not_in_canonical_list(self, tmp_path):
        from signalvault.workspace.canonicalize import (
            canonical_claims,
        )
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="**AI agents transform enterprise**",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="AI agents transform enterprise",
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        canon = canonical_claims(snapshot.claims)
        assert len(canon) == 1
        assert canon[0].card_id == "claim_b"

    def test_go_go_era_claims_same_group(self, tmp_path):
        """go-go era duplicate pair should be grouped."""
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        text = ("1960年代go-go时代，投资者从保守的平衡基金转向快速交易、"
                "追求短期高利润的积极风格。平衡基金（股债混合）市场份额从"
                "1955年的40%骤降至1975年不足1%")
        _add_claim(vault, "claim_a", status="active",
                   claim_text=f"**{text}**",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text=text,
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        assert len(groups) == 1

    def test_ai_jobs_claims_same_group(self, tmp_path):
        """AI jobs duplicate pair should be grouped."""
        from signalvault.workspace.canonicalize import group_duplicate_claims
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        text = ("AI对就业的影响存在分歧：Cloudflare和Meta将裁员归因于AI，"
                "而高盛CEO则认为AI就业冲击被夸大，市场理解仍混沌。")
        _add_claim(vault, "claim_a", status="active",
                   claim_text=f"**{text}**",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text=f"{text} #labor_market #AI_impact",
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        groups = group_duplicate_claims(snapshot.claims)
        assert len(groups) == 1


# ── Actionability tests ──────────────────────────────────────────────

class TestActionability:
    """Actionability gate for claims and signals."""

    def test_watching_signal_already_followed(self, tmp_path):
        from signalvault.workspace.actionability import get_signal_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_signal(vault, "sig_001", status="watching",
                     signal_text="Test signal to watch")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        a = get_signal_actionability(snapshot.signals[0])
        assert a.is_actionable is False
        assert a.status_label == "已在跟踪"

    def test_open_high_priority_signal_is_actionable(self, tmp_path):
        from signalvault.workspace.actionability import get_signal_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_signal(vault, "sig_001", status="open",
                     signal_text="Open signal about GPU supply chain risk in semiconductor industry",
                     tracking_status="")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Manually set priority for testing
        snapshot.signals[0].review_priority = "high"
        a = get_signal_actionability(snapshot.signals[0])
        assert a.is_actionable is True
        assert a.primary_action == "follow"

    def test_verified_claim_already_accepted(self, tmp_path):
        from signalvault.workspace.actionability import get_claim_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="verified",
                    claim_text="Verified claim")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        a = get_claim_actionability(snapshot.claims[0])
        assert a.is_actionable is False
        assert a.status_label == "已采纳"

    def test_challenged_high_priority_claim_is_actionable(self, tmp_path):
        from signalvault.workspace.actionability import get_claim_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="challenged",
                    claim_text="Challenged claim")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        snapshot.claims[0].review_priority = "high"
        a = get_claim_actionability(snapshot.claims[0])
        assert a.is_actionable is True
        assert a.primary_action == "accept"

    def test_duplicate_claim_not_actionable(self, tmp_path):
        from signalvault.workspace.actionability import get_claim_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="active",
                    claim_text="Active claim")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        a = get_claim_actionability(snapshot.claims[0], is_canonical=False)
        assert a.is_actionable is False
        assert a.status_label == "重复"

    def test_resolved_signal_not_actionable(self, tmp_path):
        from signalvault.workspace.actionability import get_signal_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_signal(vault, "sig_001", status="resolved",
                     signal_text="Resolved signal about semiconductor supply chain constraints")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        a = get_signal_actionability(snapshot.signals[0])
        assert a.is_actionable is False
        assert a.status_label == "已关闭"

    def test_signal_with_active_tracking_already_followed(self, tmp_path):
        from signalvault.workspace.actionability import get_signal_actionability
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_signal(vault, "sig_001", status="open", tracking_status="active",
                     signal_text="Signal with active tracking")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        a = get_signal_actionability(snapshot.signals[0])
        assert a.is_actionable is False
        assert a.status_label == "已在跟踪"

    def test_actionable_recommendations_exclude_duplicates(self, tmp_path):
        from signalvault.workspace.actionability import (
            build_actionable_recommendations,
        )
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="challenged",
                   claim_text="**AI agents transform enterprise**",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="challenged",
                   claim_text="AI agents transform enterprise #ui #agents",
                   source_reports=["r1", "r2"])
        _add_signal(vault, "sig_001", status="open",
                    signal_text="New GPU regulation risk")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Set priorities
        for cl in snapshot.claims:
            cl.review_priority = "high"
        for s in snapshot.signals:
            s.review_priority = "high"

        recs = build_actionable_recommendations(snapshot)
        # Only 1 canonical claim + maybe 1 signal = max 2 unique items
        claim_recs = [r for r in recs if r.get('primary_action') == 'accept']
        assert len(claim_recs) <= 1  # Deduped to 1 canonical


# ── Integration: reinforced_claims dedup ─────────────────────────────

class TestReinforcedClaimsDedup:
    """Research brief reinforced_claims uses canonical dedup."""

    def test_reinforced_claims_no_duplicates(self, tmp_path):
        from signalvault.workspace.research_brief import generate_brief
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="**AI agents transform enterprise workflows with automation**",
                   source_reports=["r1", "r2"])
        _add_claim(vault, "claim_b", status="active",
                   claim_text="AI agents transform enterprise workflows with automation #ui #agents",
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        brief = generate_brief(snapshot)
        # Should only have 1 reinforced claim (canonical)
        assert len(brief.reinforced_claims) <= 1

    def test_reinforced_claims_clean_display(self, tmp_path):
        """Reinforced claims output should not have markdown bold or hashtags."""
        from signalvault.workspace.research_brief import generate_brief
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="active",
                   claim_text="**AI agents transform enterprise workflows** `#ui #agents",
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        brief = generate_brief(snapshot)
        if brief.reinforced_claims:
            text = brief.reinforced_claims[0]
            assert "**" not in text
            assert "#ui" not in text


# ── Home needs_review uses canonical ─────────────────────────────────

class TestHomeNeedsReviewCanonical:
    """Home needs_review section uses canonical dedup."""

    def test_home_shows_only_canonical(self, tmp_path):
        from signalvault.workspace.generators import generate_home_dashboard
        from signalvault.workspace.scanner import VaultScanner

        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_a", status="challenged",
                   claim_text="**AI agents transform enterprise**",
                   source_reports=["r1"])
        _add_claim(vault, "claim_b", status="challenged",
                   claim_text="AI agents transform enterprise #ui #agents",
                   source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Set priorities
        for cl in snapshot.claims:
            cl.review_priority = "high"
        content = generate_home_dashboard(snapshot)
        claim_links = content.count("[[06_Claims/")
        assert claim_links <= 1  # Only canonical, not both
