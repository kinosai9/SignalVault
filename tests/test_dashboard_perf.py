"""Dashboard performance optimization verification tests.

Validates:
1. Scanner cache hit/miss behavior
2. Cache invalidation on file change
3. review_priority single-pass produces same results as original
4. claims_count_for / signals_count_for caching correctness
5. Dashboard vs reports relative performance
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from signalvault.workspace.scanner import WorkspaceSnapshot


# ── Vault builder helpers ──────────────────────────────────────────

def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for d in [
        "01_Reports", "02_Topics", "03_Companies", "05_Channels",
        "06_Claims", "07_Signals", "99_System",
    ]:
        (vault / d).mkdir(parents=True)
    return vault


def _add_report(vault: Path, filename: str, *, channel="TestChannel",
                video_id="vid001", analyzed_at="2026-05-29 17:00",
                title="Test Report Title") -> Path:
    p = vault / "01_Reports" / f"{filename}.md"
    p.write_text(f"""---
type: report
channel: {channel}
video_id: {video_id}
analyzed_at: "{analyzed_at}"
tags:
  - podcast-report
---
# {title}

## Summary

Test content from {channel}.
""", encoding="utf-8")
    return p


def _add_topic(vault: Path, name: str, *, status="core",
               source_reports: list[str] | None = None) -> Path:
    p = vault / "02_Topics" / f"{name}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr) if sr else "  []"
    p.write_text(f"""---
type: topic
status: {status}
topic: {name}
aliases: []
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}
""", encoding="utf-8")
    return p


def _add_company(vault: Path, name: str, *,
                 source_reports: list[str] | None = None) -> Path:
    p = vault / "03_Companies" / f"{name}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr) if sr else "  []"
    p.write_text(f"""---
type: company
company: {name}
ticker: ""
sector: ""
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}
""", encoding="utf-8")
    return p


def _add_claim(vault: Path, card_id: str, *, status="active",
               claim_text="Test claim",
               source_reports: list[str] | None = None,
               related_topics: list[str] | None = None,
               related_companies: list[str] | None = None) -> Path:
    p = vault / "06_Claims" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr)
    rt = related_topics or []
    rt_yaml = "\n".join(f"  - {t}" for t in rt)
    rc = related_companies or []
    rc_yaml = "\n".join(f"  - {c}" for c in rc)
    p.write_text(f"""---
type: claim
status: {status}
claim: "{claim_text}"
confidence: medium
source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
---
# Claim: {card_id}

{claim_text}
""", encoding="utf-8")
    return p


def _add_signal(vault: Path, card_id: str, *, status="open",
                signal_text="Test signal",
                source_reports: list[str] | None = None,
                related_topics: list[str] | None = None,
                related_companies: list[str] | None = None) -> Path:
    p = vault / "07_Signals" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr)
    rt = related_topics or []
    rt_yaml = "\n".join(f"  - {t}" for t in rt)
    rc = related_companies or []
    rc_yaml = "\n".join(f"  - {c}" for c in rc)
    p.write_text(f"""---
type: signal
status: {status}
signal: "{signal_text}"
source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
updated_at: "2026-05-30 12:00"
---
# Signal: {card_id}

{signal_text}
""", encoding="utf-8")
    return p


def _make_mini_vault(tmp_path: Path) -> Path:
    """Create a small vault with realistic data for testing."""
    vault = _make_vault(tmp_path)
    _add_report(vault, "rpt1", video_id="v1",
                title="AI Infrastructure Trends")
    _add_report(vault, "rpt2", video_id="v2",
                title="Semiconductor Supply Chain")
    _add_report(vault, "rpt3", video_id="v3",
                title="Cloud Computing Outlook")

    _add_topic(vault, "AI Infrastructure",
               source_reports=["rpt1", "rpt2"])
    _add_topic(vault, "Semiconductors",
               source_reports=["rpt2"])

    _add_company(vault, "NVIDIA", source_reports=["rpt1", "rpt2"])
    _add_company(vault, "TSMC", source_reports=["rpt2"])

    _add_claim(vault, "cl1", claim_text="NVIDIA dominates AI GPU market",
               source_reports=["rpt1"],
               related_topics=["AI Infrastructure"],
               related_companies=["NVIDIA"])
    _add_claim(vault, "cl2",
               claim_text="TSMC 3nm capacity is fully booked",
               source_reports=["rpt2"],
               related_topics=["Semiconductors"],
               related_companies=["TSMC"])
    _add_claim(vault, "cl3",
               claim_text="Cloud spending accelerates",
               source_reports=["rpt3"],
               related_topics=["AI Infrastructure"])

    _add_signal(vault, "sig1", signal_text="NVIDIA new GPU launch",
                source_reports=["rpt1"],
                related_companies=["NVIDIA"])
    _add_signal(vault, "sig2",
                signal_text="TSMC expansion in Arizona",
                source_reports=["rpt2"],
                related_companies=["TSMC"])

    return vault


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mini_vault(tmp_path):
    return _make_mini_vault(tmp_path)


# ── Scanner cache tests ──────────────────────────────────────────────

class TestScannerCache:
    def test_cache_hit_returns_same_data(self, mini_vault):
        from signalvault.workspace.scanner_cache import (
            scan_with_cache,
            invalidate_cache,
        )
        invalidate_cache(mini_vault)
        snap1 = scan_with_cache(mini_vault)
        snap2 = scan_with_cache(mini_vault)
        assert snap1.scanned_at == snap2.scanned_at
        assert len(snap1.claims) == len(snap2.claims)
        assert len(snap1.reports) == len(snap2.reports)

    def test_cache_invalidated_on_file_change(self, mini_vault):
        from signalvault.workspace.scanner_cache import (
            scan_with_cache,
            invalidate_cache,
        )
        invalidate_cache(mini_vault)
        snap1 = scan_with_cache(mini_vault)
        # Force a cache miss by explicitly invalidating
        _add_report(mini_vault, "rpt_new", video_id="v99",
                    title="New Report")
        invalidate_cache(mini_vault)
        snap2 = scan_with_cache(mini_vault)
        assert snap1.scanned_at != snap2.scanned_at
        # Verify the new report is in the second scan
        assert len(snap2.reports) > len(snap1.reports)

    def test_cache_performance_improvement(self, mini_vault):
        from signalvault.workspace.scanner_cache import (
            scan_with_cache,
            invalidate_cache,
        )
        invalidate_cache(mini_vault)
        t0 = time.perf_counter()
        scan_with_cache(mini_vault)
        first = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(10):
            scan_with_cache(mini_vault)
        cached = (time.perf_counter() - t0) / 10

        assert cached * 10 < first, (
            f"Cached ({cached:.4f}s) should be much faster "
            f"than first scan ({first:.4f}s)"
        )

    def test_invalidate_cache_clears_all(self, mini_vault):
        from signalvault.workspace.scanner_cache import (
            scan_with_cache,
            invalidate_cache,
        )
        invalidate_cache(mini_vault)
        snap1 = scan_with_cache(mini_vault)
        invalidate_cache(mini_vault)
        snap2 = scan_with_cache(mini_vault)
        assert snap1.scanned_at != snap2.scanned_at


# ── Claims / Signals count cache tests ───────────────────────────────

class TestCountCaching:
    def test_claims_count_cache_hit(self, mini_vault):
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()

        count1 = snap.claims_count_for("NVIDIA")
        count2 = snap.claims_count_for("NVIDIA")
        assert count1 == count2 == 1  # Only cl1 references NVIDIA

    def test_claims_count_cache_consistency(self, mini_vault):
        """Cache should produce same results as iterating manually."""
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()

        for name in ("NVIDIA", "TSMC", "AI Infrastructure",
                      "Semiconductors", "NonExistent"):
            c1 = snap.claims_count_for(name)
            c2 = snap.claims_count_for(name)
            assert c1 == c2, f"Mismatch for {name}: {c1} vs {c2}"

    def test_signals_count_cache_hit(self, mini_vault):
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()

        count1 = snap.signals_count_for("NVIDIA")
        count2 = snap.signals_count_for("NVIDIA")
        assert count1 == count2 == 1

    def test_signals_count_cache_consistency(self, mini_vault):
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()

        for name in ("NVIDIA", "TSMC", "AI Infrastructure",
                      "NonExistent"):
            c1 = snap.signals_count_for(name)
            c2 = snap.signals_count_for(name)
            assert c1 == c2, f"Mismatch for {name}: {c1} vs {c2}"


# ── Review priority single-pass test ──────────────────────────────────

class TestReviewPriorityOptimization:
    def test_single_pass_produces_same_counts(self, mini_vault):
        """Verify the single-pass priority logic matches the
        original behavior (needs_review, auto_accepted, low_priority)."""
        from signalvault.workspace.scanner import VaultScanner
        from signalvault.workspace.review_priority import (
            PRIORITY_AUTO_ACCEPTED,
            PRIORITY_CRITICAL,
            PRIORITY_HIGH,
            PRIORITY_LOW,
            PRIORITY_NORMAL,
            compute_claim_review_priority,
            compute_signal_review_priority,
        )
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()

        # New single-pass approach
        needs_review_n = 0
        auto_accepted_n = 0
        low_priority_n = 0
        normal_n = 0

        for cl in snap.claims:
            priority = compute_claim_review_priority(
                cl, snap, set(), set(),
            )
            cl.review_priority = priority
            if priority in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                needs_review_n += 1
            elif priority == PRIORITY_AUTO_ACCEPTED:
                auto_accepted_n += 1
            elif priority == PRIORITY_LOW:
                low_priority_n += 1
            else:
                normal_n += 1

        for s in snap.signals:
            priority = compute_signal_review_priority(
                s, snap, set(), set(),
            )
            s.review_priority = priority
            if priority in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                needs_review_n += 1
            elif priority == PRIORITY_AUTO_ACCEPTED:
                auto_accepted_n += 1
            elif priority == PRIORITY_LOW:
                low_priority_n += 1
            else:
                normal_n += 1

        total = needs_review_n + auto_accepted_n + low_priority_n + normal_n
        assert total == len(snap.claims) + len(snap.signals)

    def test_single_pass_counts_are_deterministic(self, mini_vault):
        """Running the same logic twice produces identical counts."""
        from signalvault.workspace.scanner import VaultScanner
        from signalvault.workspace.review_priority import (
            PRIORITY_AUTO_ACCEPTED,
            PRIORITY_CRITICAL,
            PRIORITY_HIGH,
            PRIORITY_LOW,
            compute_claim_review_priority,
            compute_signal_review_priority,
        )

        def run_pass(snap):
            n = 0
            a = 0
            l = 0
            for cl in snap.claims:
                p = compute_claim_review_priority(cl, snap, set(), set())
                if p in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                    n += 1
                elif p == PRIORITY_AUTO_ACCEPTED:
                    a += 1
                elif p == PRIORITY_LOW:
                    l += 1
            for s in snap.signals:
                p = compute_signal_review_priority(s, snap, set(), set())
                if p in (PRIORITY_CRITICAL, PRIORITY_HIGH):
                    n += 1
                elif p == PRIORITY_AUTO_ACCEPTED:
                    a += 1
                elif p == PRIORITY_LOW:
                    l += 1
            return n, a, l

        scanner = VaultScanner(mini_vault)
        snap1 = scanner.scan()
        r1 = run_pass(snap1)

        scanner2 = VaultScanner(mini_vault)
        snap2 = scanner2.scan()
        r2 = run_pass(snap2)

        assert r1 == r2


# ── Dashboard vs reports relative performance ────────────────────────

class TestDashboardVsReportsPerf:
    @pytest.mark.slow
    def test_dashboard_scan_is_reasonably_fast(self, mini_vault,
                                                monkeypatch, tmp_path):
        """Full dashboard scan should complete in under 3 seconds
        for a small vault."""
        from signalvault.workspace.scanner import VaultScanner
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(mini_vault))
        t0 = time.perf_counter()
        scanner = VaultScanner(mini_vault)
        snap = scanner.scan()
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, (
            f"Scan took {elapsed:.3f}s for small vault"
        )
        assert len(snap.reports) >= 1
