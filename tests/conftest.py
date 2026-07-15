"""Shared test fixtures.

Environment isolation: conftest forces LLM env vars BEFORE any signalvault
module import so that load_dotenv() never picks up a real .env file.

C1-A: AppPaths is also isolated per test session via a tmp_path-based
override so that tests never write to platform user directories.
"""

import os
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# P2-A1.1  Test environment hardening — set BEFORE importing signalvault.
# load_dotenv() does NOT overwrite existing env vars, so pre-setting these
# blocks .env values from leaking into tests.
# ---------------------------------------------------------------------------
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_MODEL"] = "mock-investment-analyst"

# P2-C.1: isolate Obsidian Vault path
os.environ["OBSIDIAN_VAULT_PATH"] = ""
os.environ["OBSIDIAN_EXPORT_ENABLED"] = "false"

# C1-A: prevent SIGNALVAULT_HOME / DATA_DIR / LOG_DIR / DB_PATH from
# leaking in from the developer's shell environment or repo .env file.
# Must SET (not pop) so load_dotenv() doesn't re-populate them from .env.
os.environ["SIGNALVAULT_HOME"] = ""
os.environ["DATA_DIR"] = ""
os.environ["LOG_DIR"] = ""
os.environ["DB_PATH"] = ""

import pytest

from signalvault.analysis.models import (
    Entity,
    ExtractionResult,
    InvestmentView,
    TrackingSignal,
)
from signalvault.db.repository import (
    save_entities,
    save_episode,
    save_investment_views,
    save_report,
    save_tracking_signals,
)
from signalvault.db.session import get_session, init_db, reset_engine

SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"


@pytest.fixture()
def db_session(monkeypatch):
    """Create a temporary database, yield session, then clean up.

    Also updates config.DB_PATH so that diagnostics and other code that
    reads the module-level constant see the actual temp path.
    """
    from signalvault import config

    reset_engine()
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path)
    # Let downstream code (diagnostics, etc.) see the real DB path
    monkeypatch.setattr(config, "DB_PATH", Path(db_path))
    session = get_session()
    yield session
    session.close()
    reset_engine()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _make_extraction(target: str = "宁德时代", direction: str = "bullish") -> ExtractionResult:
    return ExtractionResult(
        focus_areas=["新能源", "港股"],
        investment_views=[
            InvestmentView(
                target_name=target,
                target_type="stock",
                view_direction=direction,
                logic_chain=f"{target}逻辑链：行业需求增长",
                source_quote=f"关于{target}的原文引用",
                timestamp_start="00:32:10",
            )
        ],
        mentioned_entities=[
            Entity(name=target, entity_type="stock"),
        ],
        tracking_signals=[
            TrackingSignal(signal=f"关注{target}出货量", target_name=target),
        ],
    )


@pytest.fixture()
def seeded_db(db_session):
    """Pre-populate 3 reports: 2 local + 1 youtube, different targets."""
    session = db_session

    ep1 = save_episode(session, "新能源访谈", "test.srt", "srt", "hash1")
    ex1 = _make_extraction("宁德时代", "bullish")
    rep1 = save_report(session, ep1, ex1, "# 新能源报告\n宁德时代储能需求增长", analysis_depth="standard")
    save_investment_views(session, rep1, ex1.investment_views)
    save_tracking_signals(session, rep1, ex1.tracking_signals)
    save_entities(session, ex1.mentioned_entities)

    ep2 = save_episode(session, "港股策略", "test2.srt", "srt", "hash2")
    ex2 = _make_extraction("港股红利ETF", "neutral")
    rep2 = save_report(session, ep2, ex2, "# 港股策略报告\n港股红利估值偏低", analysis_depth="deep")
    save_investment_views(session, rep2, ex2.investment_views)
    save_tracking_signals(session, rep2, ex2.tracking_signals)
    save_entities(session, ex2.mentioned_entities)

    ep3 = save_episode(
        session, "AI Investment Talk", "youtube", "json", "hash3",
        source_url="https://www.youtube.com/watch?v=abc123",
        video_id="abc123",
        language="en",
    )
    ex3 = _make_extraction("NVIDIA", "bullish")
    rep3 = save_report(session, ep3, ex3, "# AI Report\nNVIDIA GPU demand is strong", analysis_depth="standard")
    save_investment_views(session, rep3, ex3.investment_views)
    save_tracking_signals(session, rep3, ex3.tracking_signals)
    save_entities(session, ex3.mentioned_entities)

    session.commit()
    return session


@pytest.fixture()
def api_client(db_session):
    """Create a FastAPI TestClient backed by the temp database."""
    from fastapi.testclient import TestClient

    from signalvault.api.app import create_app

    app = create_app()
    client = TestClient(app)
    return client


# ── C1-A: AppPaths isolation ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_app_paths(tmp_path, monkeypatch):
    """C1-A: Override config._paths so tests never write to real user dirs.

    Every path (DATA_DIR, LOG_DIR, DB_PATH, config_store, …) lands under
    a per-test tmp_path.
    """
    from signalvault import config
    from signalvault.settings.app_paths import AppPaths

    test_home = tmp_path / "SignalVault"
    test_paths = AppPaths.resolve(home_override=test_home)
    monkeypatch.setattr(config, "_paths", test_paths)
    # Refresh module-level path aliases
    monkeypatch.setattr(config, "DATA_DIR", test_paths.data_dir)
    monkeypatch.setattr(config, "LOG_DIR", test_paths.log_dir)
    monkeypatch.setattr(config, "DB_PATH", test_paths.db_path)
    monkeypatch.setattr(config, "SUBTITLE_DIR", test_paths.subtitle_dir)
    monkeypatch.setattr(config, "REPORT_DIR", test_paths.report_dir)
    monkeypatch.setattr(config, "TRANSCRIPT_CACHE_DIR", test_paths.transcript_cache_dir)
    # Also wire AppPaths through config_store
    monkeypatch.setattr(
        config, "get_app_paths", lambda: test_paths,
    )


# ── P2-L.1: config_store isolation ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_config_store(tmp_path, monkeypatch):
    """P2-L.1: Isolate config_store so tests don't touch real settings."""
    import signalvault.config_store as cs
    settings_file = tmp_path / "user_settings.json"
    monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_file)
    monkeypatch.setattr(cs, "_SETTINGS_PATH", settings_file)
    # Also block legacy-path detection — otherwise _get_legacy_path()
    # finds the repo's data/user_settings.json with real vault paths.
    monkeypatch.setattr(cs, "_get_legacy_path", lambda: None)
    monkeypatch.setattr(cs, "_LEGACY_SETTINGS_PATH", None)


# ── C1-B: ConfigService + SecretStore isolation ─────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_config_service(tmp_path, monkeypatch):
    """C1-B: Replace the ConfigService singleton with a test-isolated instance.

    Every test gets a fresh ConfigService backed by tmp_path, so:
    - config.toml lives in tmp_path
    - secrets live in tmp_path
    - no real user config is read or written
    """
    from signalvault.settings.app_paths import AppPaths
    from signalvault.settings.secret_store import SecretStore
    from signalvault.settings.service import (
        ConfigService,
        _override_config_service,
    )

    test_home = tmp_path / "SignalVault"
    test_paths = AppPaths.resolve(home_override=test_home)
    test_secrets = SecretStore(test_paths.config_dir)

    # Build a ConfigService that reads the LIVE os.environ (so that
    # monkeypatch.setenv inside tests is visible to ConfigService).
    # Pass env=None to use the default behaviour (live dict lookup).
    svc = ConfigService(
        test_paths,
        env=None,  # use live os.environ, not a snapshot
        secret_store=test_secrets,
    )
    _override_config_service(svc)

    yield

    # Cleanup
    _override_config_service(None)
