"""Tests for services/translate_service.py — batch translation with status tracking."""

import json
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeProvider:
    """Fake LLM provider for testing translate_service."""
    def __init__(self, fail_on=None):
        self.calls = []
        self._fail_on = fail_on or set()

    def translate_text(self, text, source_lang="en", target_lang="zh"):
        self.calls.append((text, source_lang, target_lang))
        if text in self._fail_on:
            raise RuntimeError(f"Simulated failure for: {text[:30]}")
        return f"[ZH] {text}"


def _make_segment(session, source_doc_id, seq, text, status="not_needed", translated=""):
    from signalvault.db.models import SourceSegment
    seg = SourceSegment(
        source_doc_id=source_doc_id,
        segment_id=f"seg_{seq}",
        sequence_index=seq,
        segment_type="timestamp",
        text_original=text,
        text_translated=translated,
        translation_status=status,
    )
    session.add(seg)
    session.flush()
    return seg


def _make_source_doc(session, source_doc_id="test_doc_001", source_type="youtube_transcript"):
    from signalvault.db.models import SourceDocument
    doc = SourceDocument(
        source_doc_id=source_doc_id,
        source_type=source_type,
        title="Test Document",
    )
    session.add(doc)
    session.flush()
    return doc


# ── Tests ────────────────────────────────────────────────────────────────────

class TestTranslateSegments:
    def test_all_translated(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_all_new"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "Hello world")
        _make_segment(db_session, doc_id, 1, "Second segment")
        _make_segment(db_session, doc_id, 2, "Third one")

        provider = FakeProvider()
        result = translate_segments(db_session, doc_id, provider)

        assert result["total"] == 3
        assert result["translated"] == 3
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert len(provider.calls) == 3

        # Verify persistence
        from signalvault.db.models import SourceSegment
        segs = (
            db_session.query(SourceSegment)
            .filter(SourceSegment.source_doc_id == doc_id)
            .order_by(SourceSegment.sequence_index)
            .all()
        )
        assert all(s.translation_status == "translated" for s in segs)
        assert segs[0].text_translated == "[ZH] Hello world"

    def test_skips_already_translated(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_mixed_status"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "New one", status="not_needed")
        _make_segment(db_session, doc_id, 1, "Already done", status="translated", translated="[ZH] Already done")
        _make_segment(db_session, doc_id, 2, "Also new", status="not_needed")

        provider = FakeProvider()
        result = translate_segments(db_session, doc_id, provider)

        assert result["total"] == 3
        assert result["translated"] == 2  # only the two new ones
        assert result["skipped"] == 1     # the already-translated one
        assert result["failed"] == 0
        assert len(provider.calls) == 2   # only called for the two new ones

    def test_empty_segments_set_not_needed(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_with_empty"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "Valid text")
        _make_segment(db_session, doc_id, 1, "")        # empty
        _make_segment(db_session, doc_id, 2, "   ")      # whitespace only

        provider = FakeProvider()
        result = translate_segments(db_session, doc_id, provider)

        assert result["translated"] == 1  # only the valid one
        assert result["skipped"] == 2     # two empty ones
        assert len(provider.calls) == 1

        from signalvault.db.models import SourceSegment
        segs = (
            db_session.query(SourceSegment)
            .filter(SourceSegment.source_doc_id == doc_id)
            .order_by(SourceSegment.sequence_index)
            .all()
        )
        assert segs[1].translation_status == "not_needed"
        assert segs[2].translation_status == "not_needed"

    def test_failure_does_not_abort_others(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_partial_fail"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "Good segment")
        _make_segment(db_session, doc_id, 1, "BAD_SEGMENT_WILL_FAIL")
        _make_segment(db_session, doc_id, 2, "Another good one")

        provider = FakeProvider(fail_on={"BAD_SEGMENT_WILL_FAIL"})
        result = translate_segments(db_session, doc_id, provider)

        assert result["translated"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 0
        assert len(provider.calls) == 3  # all attempted

        from signalvault.db.models import SourceSegment
        segs = (
            db_session.query(SourceSegment)
            .filter(SourceSegment.source_doc_id == doc_id)
            .order_by(SourceSegment.sequence_index)
            .all()
        )
        assert segs[0].translation_status == "translated"
        assert segs[1].translation_status == "failed"
        assert segs[2].translation_status == "translated"

    def test_progress_callback(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_progress"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "A")
        _make_segment(db_session, doc_id, 1, "B")
        _make_segment(db_session, doc_id, 2, "C")

        progress = []
        provider = FakeProvider()
        result = translate_segments(
            db_session, doc_id, provider,
            progress_callback=lambda t, total: progress.append((t, total)),
        )

        assert len(progress) == 3
        assert progress[0] == (1, 3)  # after first translated
        assert progress[1] == (2, 3)  # after second
        assert progress[2] == (3, 3)  # after third

    def test_empty_doc_no_segments(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_empty"
        _make_source_doc(db_session, doc_id)

        provider = FakeProvider()
        result = translate_segments(db_session, doc_id, provider)

        assert result["total"] == 0
        assert result["translated"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 0

    def test_translation_metadata_written(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_meta"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "Translate me")

        provider = FakeProvider()
        translate_segments(db_session, doc_id, provider)

        from signalvault.db.models import SourceSegment
        seg = (
            db_session.query(SourceSegment)
            .filter(SourceSegment.source_doc_id == doc_id)
            .first()
        )
        meta = json.loads(seg.translation_metadata_json)
        assert meta["source_lang"] == "en"
        assert meta["target_lang"] == "zh"
        assert meta["status"] == "success"
        assert "translated_at" in meta

    def test_failure_metadata_written(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_fail_meta"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "FAIL_ME")

        provider = FakeProvider(fail_on={"FAIL_ME"})
        translate_segments(db_session, doc_id, provider)

        from signalvault.db.models import SourceSegment
        seg = (
            db_session.query(SourceSegment)
            .filter(SourceSegment.source_doc_id == doc_id)
            .first()
        )
        meta = json.loads(seg.translation_metadata_json)
        assert "error:" in meta["status"]

    def test_custom_languages(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_lang"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "Bonjour")

        provider = FakeProvider()
        result = translate_segments(
            db_session, doc_id, provider,
            source_lang="fr", target_lang="en",
        )

        assert result["translated"] == 1
        # Verify the provider was called with custom languages
        assert provider.calls[0][1] == "fr"
        assert provider.calls[0][2] == "en"

    def test_all_already_translated(self, db_session):
        from signalvault.services.translate_service import translate_segments
        doc_id = "doc_all_done"
        _make_source_doc(db_session, doc_id)
        _make_segment(db_session, doc_id, 0, "A", status="translated", translated="[ZH] A")
        _make_segment(db_session, doc_id, 1, "B", status="translated", translated="[ZH] B")

        provider = FakeProvider()
        result = translate_segments(db_session, doc_id, provider)

        assert result["translated"] == 0
        assert result["skipped"] == 2
        assert len(provider.calls) == 0


class TestMakeTranslationMeta:
    def test_json_structure(self):
        from signalvault.services.translate_service import _make_translation_meta
        result = _make_translation_meta("en", "zh", "success")
        data = json.loads(result)
        assert data["source_lang"] == "en"
        assert data["target_lang"] == "zh"
        assert data["status"] == "success"
        assert "translated_at" in data

    def test_failure_status(self):
        from signalvault.services.translate_service import _make_translation_meta
        result = _make_translation_meta("ja", "en", "error: timeout")
        data = json.loads(result)
        assert data["source_lang"] == "ja"
        assert data["status"] == "error: timeout"
