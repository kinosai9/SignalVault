"""P2-N.3: Knowledge Graph Quality Audit tests."""

import json

from signalvault.workspace.quality_audit import (
    _COMPANY_ALIASES,
    _NOT_COMPANY,
    _NOT_TOPIC,
    _TOPIC_ALIASES,
    _norm,
    _norm_title,
    _slug,
    run_quality_audit,
)

# ── Normalization helpers ──────────────────────────────────────────


def test_norm_lowercase_strip():
    assert _norm("  Hello World!  ") == "hello world"


def test_norm_punctuation_removed():
    assert _norm("NVIDIA Corp.") == "nvidia corp"
    assert _norm("AI Agents!!") == "ai agents"


def test_norm_title():
    assert "episode" not in _norm_title("Episode 42: AI Revolution")


def test_slug_truncation():
    s = _slug("a" * 200)
    assert len(s) <= 80


# ── Company alias normalization ────────────────────────────────────


def test_google_normalizes_to_alphabet():
    assert _COMPANY_ALIASES["google"] == "Alphabet"


def test_nvidia_normalizes():
    assert _COMPANY_ALIASES["nvidia"] == "NVIDIA"
    assert _COMPANY_ALIASES["nvda"] == "NVIDIA"


def test_openai_normalizes():
    assert _COMPANY_ALIASES["openai"] == "OpenAI"
    assert _COMPANY_ALIASES["open ai"] == "OpenAI"


# ── Topic alias normalization ──────────────────────────────────────


def test_agent_normalizes_to_ai_agents():
    assert _TOPIC_ALIASES["agent"] == "AI Agents"
    assert _TOPIC_ALIASES["ai agent"] == "AI Agents"


def test_model_normalizes_to_ai_models():
    assert _TOPIC_ALIASES["model"] == "AI Models"


def test_infrastructure_normalizes():
    assert _TOPIC_ALIASES["infrastructure"] == "AI Infrastructure"


def test_enterprise_normalizes():
    assert _TOPIC_ALIASES["enterprise"] == "Enterprise AI"


# ── Not-company guard ──────────────────────────────────────────────


def test_agent_not_company():
    assert "agent" in _NOT_COMPANY


def test_model_not_company():
    assert "model" in _NOT_COMPANY


def test_gpu_not_company():
    assert "gpu" in _NOT_COMPANY


# ── Not-topic guard ────────────────────────────────────────────────


def test_openai_not_topic():
    assert "openai" in _NOT_TOPIC


def test_anthropic_not_topic():
    assert "anthropic" in _NOT_TOPIC


def test_nvidia_not_topic():
    assert "nvidia" in _NOT_TOPIC


def test_microsoft_not_topic():
    assert "microsoft" in _NOT_TOPIC


# ── Audit: duplicate detection ─────────────────────────────────────


def test_audit_detects_duplicate_video_id_report(tmp_path, monkeypatch):
    """Duplicate video_id in DB should be detected."""
    from signalvault.db.models import Episode, Report
    from signalvault.db.session import get_session, init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    # Create two reports with same video_id
    session = get_session()
    try:
        ep1 = Episode(source="youtube", title="Test", video_id="dup123")
        session.add(ep1)
        session.flush()
        r1 = Report(episode_id=ep1.id, extraction_json="{}", report_markdown="# test")
        session.add(r1)
        session.flush()

        ep2 = Episode(source="youtube", title="Test 2", video_id="dup123")
        session.add(ep2)
        session.flush()
        r2 = Report(episode_id=ep2.id, extraction_json="{}", report_markdown="# test2")
        session.add(r2)
        session.commit()
    finally:
        session.close()

    result = run_quality_audit(db_path=str(db_path))
    assert result.total_reports >= 2
    # Should have detected duplicate
    has_dup = any(d.entity_type == "report" for d in result.duplicate_findings)
    assert has_dup, "Should detect duplicate video_id"
    reset_engine()


def test_audit_json_output(tmp_path, monkeypatch):
    """Audit JSON output is valid."""
    from signalvault.db.models import Episode, Report
    from signalvault.db.session import get_session, init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    session = get_session()
    try:
        ep = Episode(source="youtube", title="Test", video_id="vid1", source_url="https://youtu.be/vid1")
        session.add(ep)
        session.flush()
        r = Report(episode_id=ep.id, extraction_json='{"views":[]}', report_markdown="# test",
                    llm_provider="mock")
        session.add(r)
        session.commit()
    finally:
        session.close()

    result = run_quality_audit(db_path=str(db_path))

    # Export JSON
    json_path = tmp_path / "audit.json"
    from signalvault.workspace.quality_audit import export_audit_json
    export_audit_json(result, json_path)
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "summary" in data
    assert "blocking_issues" in data
    reset_engine()


def test_audit_markdown_output(tmp_path, monkeypatch):
    """Audit Markdown output is valid."""
    from signalvault.db.models import Episode, Report
    from signalvault.db.session import get_session, init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    session = get_session()
    try:
        ep = Episode(source="youtube", title="Test", video_id="vid1", source_url="https://youtu.be/vid1")
        session.add(ep)
        session.flush()
        r = Report(episode_id=ep.id, extraction_json='{"views":[]}', report_markdown="# test",
                    llm_provider="mock")
        session.add(r)
        session.commit()
    finally:
        session.close()

    result = run_quality_audit(db_path=str(db_path))

    md_path = tmp_path / "audit.md"
    from signalvault.workspace.quality_audit import export_audit_markdown
    export_audit_markdown(result, md_path)
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "Knowledge Graph Quality Audit" in text
    assert "Summary" in text
    reset_engine()


# ── Prompt rule guards ─────────────────────────────────────────────


def test_not_company_guard_has_agent():
    """Agent must not be classified as company."""
    assert "agent" in _NOT_COMPANY


def test_not_topic_guard_has_known_companies():
    """Known companies must not be classified as topics."""
    for name in ["openai", "anthropic", "nvidia", "microsoft", "google"]:
        assert name in _NOT_TOPIC, f"{name} must be in NOT_TOPIC"


# ── Entity confusion detection ─────────────────────────────────────


def test_entity_confusion_topic_to_company(tmp_path):
    """Topic card for a known company should be detected."""
    vault = tmp_path / "vault"
    (vault / "02_Topics").mkdir(parents=True)
    (vault / "02_Topics" / "Anthropic.md").write_text(
        "---\ntype: topic\ntopic: Anthropic\n---\n# Anthropic\n",
        encoding="utf-8",
    )
    (vault / "03_Companies").mkdir(parents=True)

    from signalvault.workspace.quality_audit import _audit_entity_hygiene
    from signalvault.workspace.quality_models import QualityAuditResult
    result = QualityAuditResult()
    _audit_entity_hygiene(result, vault)
    confusions = [e for e in result.entity_confusions if e.name == "Anthropic"]
    assert len(confusions) >= 1
    assert confusions[0].suggested_type == "company"


def test_entity_confusion_company_to_topic(tmp_path):
    """Company card for a generic name should be detected."""
    vault = tmp_path / "vault"
    (vault / "03_Companies").mkdir(parents=True)
    (vault / "03_Companies" / "Agent.md").write_text(
        "---\ntype: company\ncompany: Agent\n---\n# Agent\n",
        encoding="utf-8",
    )
    (vault / "02_Topics").mkdir(parents=True)

    from signalvault.workspace.quality_audit import _audit_entity_hygiene
    from signalvault.workspace.quality_models import QualityAuditResult
    result = QualityAuditResult()
    _audit_entity_hygiene(result, vault)
    confusions = [e for e in result.entity_confusions if e.name == "Agent"]
    assert len(confusions) >= 1
    assert confusions[0].suggested_type == "topic"


def test_orphan_claim_detection(tmp_path):
    """Claim without source reports should be detected as orphan."""
    vault = tmp_path / "vault"
    (vault / "06_Claims").mkdir(parents=True)
    (vault / "06_Claims" / "orphan_claim.md").write_text(
        "---\ntype: claim\nclaim: test claim\n---\n# Test\n",
        encoding="utf-8",
    )

    from signalvault.workspace.quality_audit import _audit_graph_integrity
    from signalvault.workspace.quality_models import QualityAuditResult
    result = QualityAuditResult()
    _audit_graph_integrity(result, vault)
    assert len(result.orphan_claims) >= 1
