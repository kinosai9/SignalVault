"""Large vault performance boundary tests.

Programmatically generates a vault with ~200 topics, ~500 claims,
~100 signals to test caching and computation scaling.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


# ── Large vault generator ────────────────────────────────────────────

def _make_large_vault(tmp_path: Path) -> Path:
    """Generate a vault with many entities for stress testing."""
    vault = tmp_path / "large_vault"
    for d in [
        "01_Reports", "02_Topics", "03_Companies", "05_Channels",
        "06_Claims", "07_Signals", "99_System",
    ]:
        (vault / d).mkdir(parents=True)

    # 20 reports
    for i in range(20):
        title = f"Report {i:03d}"
        p = vault / "01_Reports" / f"{title}.md"
        p.write_text(f"""---
type: report
channel: Channel{i % 5}
video_id: vid{i:03d}
analyzed_at: "2026-05-{10 + (i % 20):02d} 12:00"
tags:
  - podcast-report
---
# {title}

Content for {title}.
""", encoding="utf-8")

    # 100 topics
    for i in range(100):
        name = f"Topic {i:03d}"
        sr = [f"Report {j:03d}" for j in range(i % 10, min(i % 10 + 2, 10))]
        p = vault / "02_Topics" / f"{name}.md"
        sr_yaml = "\n".join(f"  - {s}" for s in sr)
        p.write_text(f"""---
type: topic
status: core
topic: {name}
aliases: []
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}
""", encoding="utf-8")

    # 50 companies
    for i in range(50):
        name = f"Company {i:03d}"
        sr = [f"Report {j:03d}" for j in range(i % 20, min(i % 20 + 2, 20))]
        p = vault / "03_Companies" / f"{name}.md"
        sr_yaml = "\n".join(f"  - {s}" for s in sr)
        p.write_text(f"""---
type: company
company: {name}
ticker: ""
sector: "Technology"
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}
""", encoding="utf-8")

    # 500 claims
    for i in range(500):
        card_id = f"cl{i:04d}"
        topic = f"Topic {i % 100:03d}"
        company = f"Company {i % 50:03d}"
        report = f"Report {i % 20:03d}"
        p = vault / "06_Claims" / f"{card_id}.md"
        p.write_text(f"""---
type: claim
status: active
claim: "Claim {i} about {topic} and {company}"
confidence: medium
source_reports:
  - {report}
related_topics:
  - {topic}
related_companies:
  - {company}
---
# Claim: {card_id}

This is claim number {i} about {topic} and {company}.
""", encoding="utf-8")

    # 100 signals
    for i in range(100):
        card_id = f"sig{i:04d}"
        company = f"Company {i % 50:03d}"
        topic = f"Topic {i % 100:03d}"
        report = f"Report {i % 20:03d}"
        p = vault / "07_Signals" / f"{card_id}.md"
        p.write_text(f"""---
type: signal
status: open
signal: "Signal {i} about {company} and {topic}"
source_reports:
  - {report}
related_topics:
  - {topic}
related_companies:
  - {company}
updated_at: "2026-05-30 12:00"
---
# Signal: {card_id}

Signal {i} about {company} in {topic}.
""", encoding="utf-8")

    return vault


@pytest.fixture
def large_vault(tmp_path):
    return _make_large_vault(tmp_path)


# ── Performance boundary tests ────────────────────────────────────────

class TestLargeVaultScanCache:
    def test_cache_speedup_on_large_vault(self, large_vault):
        """Cached scan should be at least 10x faster than uncached."""
        from signalvault.workspace.scanner_cache import (
            scan_with_cache,
            invalidate_cache,
        )
        invalidate_cache(large_vault)

        t0 = time.perf_counter()
        scan_with_cache(large_vault)
        first = time.perf_counter() - t0

        t0 = time.perf_counter()
        scan_with_cache(large_vault)
        second = time.perf_counter() - t0

        ratio = first / second if second > 0 else float("inf")
        assert ratio > 10, (
            f"Cache speedup is {ratio:.1f}x, expected > 10x. "
            f"First: {first:.3f}s, Cached: {second:.3f}s"
        )

    def test_scan_completes_in_reasonable_time(self, large_vault):
        """Large vault (500 claims, 100 topics) scan < 5 seconds."""
        from signalvault.workspace.scanner import VaultScanner
        t0 = time.perf_counter()
        scanner = VaultScanner(large_vault)
        snap = scanner.scan()
        elapsed = time.perf_counter() - t0
        assert len(snap.claims) == 500
        assert len(snap.topics) == 100
        assert elapsed < 5.0, (
            f"Large vault scan took {elapsed:.2f}s, expected < 5s"
        )

    def test_count_caching_efficiency(self, large_vault):
        """After first call, claims_count_for should be near-instant."""
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(large_vault)
        snap = scanner.scan()

        # First call builds cache
        t0 = time.perf_counter()
        _ = snap.claims_count_for("Topic 050")
        first = time.perf_counter() - t0

        # Subsequent calls hit cache
        t0 = time.perf_counter()
        for i in range(100):
            _ = snap.claims_count_for(f"Topic {i % 100:03d}")
        cached_total = time.perf_counter() - t0

        avg_cached = cached_total / 100
        assert avg_cached * 100 < first, (
            f"Cached lookup ({avg_cached:.6f}s) should be "
            f"much faster than first ({first:.4f}s)"
        )

    def test_signals_count_caching_efficiency(self, large_vault):
        """After first call, signals_count_for should be near-instant."""
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(large_vault)
        snap = scanner.scan()

        t0 = time.perf_counter()
        _ = snap.signals_count_for("Topic 050")
        first = time.perf_counter() - t0

        t0 = time.perf_counter()
        _ = snap.signals_count_for("Topic 050")
        second = time.perf_counter() - t0

        assert second < first / 5, (
            f"Cached signals_count_for ({second:.4f}s) "
            f"should be much faster than first ({first:.4f}s)"
        )
