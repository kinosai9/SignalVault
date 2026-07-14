"""Tests for db/source_provenance.py — SourceDocument + SourceSegment CRUD."""

import pytest


# ── compute_content_hash ────────────────────────────────────────────────────

class TestContentHash:
    def test_deterministic(self):
        from signalvault.db.source_provenance import compute_content_hash
        assert compute_content_hash("hello") == compute_content_hash("hello")

    def test_different_inputs(self):
        from signalvault.db.source_provenance import compute_content_hash
        assert compute_content_hash("hello") != compute_content_hash("world")

    def test_16_chars(self):
        from signalvault.db.source_provenance import compute_content_hash
        assert len(compute_content_hash("test")) == 16

    def test_unicode(self):
        from signalvault.db.source_provenance import compute_content_hash
        h = compute_content_hash("中文字幕测试")
        assert len(h) == 16
        assert compute_content_hash("中文字幕测试") == h


# ── SourceDocument CRUD ─────────────────────────────────────────────────────

class TestSourceDocumentCRUD:
    def test_create_and_get(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document,
        )
        doc_id = create_source_document(
            db_session,
            source_type="youtube_transcript",
            title="Test Video Transcript",
            source_url="https://youtube.com/watch?v=abc123",
            content_hash="abc123def4567890",
            language="zh",
            original_language="en",
        )
        assert doc_id
        assert len(doc_id) == 8

        doc = get_source_document(db_session, doc_id)
        assert doc is not None
        assert doc["source_type"] == "youtube_transcript"
        assert doc["title"] == "Test Video Transcript"
        assert doc["source_url"] == "https://youtube.com/watch?v=abc123"
        assert doc["content_hash"] == "abc123def4567890"
        assert doc["language"] == "zh"
        assert doc["original_language"] == "en"
        assert doc["status"] == "available"
        assert doc["access_scope"] == "public_web"
        assert doc["retention_policy"] == "keep_full_text"

    def test_get_nonexistent(self, db_session):
        from signalvault.db.source_provenance import get_source_document
        assert get_source_document(db_session, "nonexist") is None

    def test_create_defaults(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document,
        )
        doc_id = create_source_document(db_session, source_type="web_page")
        doc = get_source_document(db_session, doc_id)
        assert doc["source_type"] == "web_page"
        assert doc["title"] == ""
        assert doc["status"] == "available"
        assert doc["access_scope"] == "public_web"

    def test_unique_doc_ids(self, db_session):
        from signalvault.db.source_provenance import create_source_document
        id1 = create_source_document(db_session, source_type="pdf_document")
        id2 = create_source_document(db_session, source_type="pdf_document")
        assert id1 != id2

    def test_private_zsxq_document(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document,
        )
        doc_id = create_source_document(
            db_session,
            source_type="zsxq_topic",
            title="Private Topic",
            access_scope="private_subscription",
            retention_policy="metadata_only",
        )
        doc = get_source_document(db_session, doc_id)
        assert doc["access_scope"] == "private_subscription"
        assert doc["retention_policy"] == "metadata_only"


class TestUpsertSourceDocument:
    def test_insert_new(self, db_session):
        from signalvault.db.source_provenance import upsert_source_document
        doc_id, is_new = upsert_source_document(
            db_session,
            source_type="web_page",
            content_hash="unique_hash_001",
            title="New Page",
            source_url="https://example.com",
        )
        assert is_new is True
        assert len(doc_id) == 8

    def test_upsert_existing_same_hash(self, db_session):
        from signalvault.db.source_provenance import (
            upsert_source_document,
            get_source_document,
        )
        doc_id1, is_new1 = upsert_source_document(
            db_session,
            source_type="web_page",
            content_hash="hash_xyz",
            title="Original Title",
        )
        assert is_new1 is True

        doc_id2, is_new2 = upsert_source_document(
            db_session,
            source_type="web_page",
            content_hash="hash_xyz",
            title="Updated Title",
        )
        assert is_new2 is False
        assert doc_id2 == doc_id1

        doc = get_source_document(db_session, doc_id1)
        assert doc["title"] == "Updated Title"

    def test_different_types_same_hash(self, db_session):
        from signalvault.db.source_provenance import upsert_source_document
        id1, n1 = upsert_source_document(
            db_session, source_type="youtube_transcript", content_hash="same_hash",
        )
        id2, n2 = upsert_source_document(
            db_session, source_type="pdf_document", content_hash="same_hash",
        )
        assert n1 is True
        assert n2 is True
        assert id1 != id2  # Different types, so both are new


class TestListSourceDocuments:
    def test_list_all(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            list_source_documents,
        )
        create_source_document(db_session, source_type="youtube_transcript", title="A")
        create_source_document(db_session, source_type="web_page", title="B")
        create_source_document(db_session, source_type="pdf_document", title="C")

        docs = list_source_documents(db_session)
        assert len(docs) == 3

    def test_filter_by_type(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            list_source_documents,
        )
        create_source_document(db_session, source_type="youtube_transcript", title="A")
        create_source_document(db_session, source_type="web_page", title="B")

        docs = list_source_documents(db_session, source_type="web_page")
        assert len(docs) == 1
        assert docs[0]["title"] == "B"

    def test_filter_by_status(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            list_source_documents,
        )
        create_source_document(db_session, source_type="web_page", title="OK")
        create_source_document(
            db_session, source_type="web_page", title="Gone", status="expired",
        )

        docs = list_source_documents(db_session, status="expired")
        assert len(docs) == 1
        assert docs[0]["title"] == "Gone"

    def test_limit_offset(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            list_source_documents,
        )
        for i in range(5):
            create_source_document(db_session, source_type="web_page", title=f"P{i}")

        docs = list_source_documents(db_session, limit=2, offset=1)
        assert len(docs) == 2


class TestCountSourceDocuments:
    def test_count_empty(self, db_session):
        from signalvault.db.source_provenance import count_source_documents
        assert count_source_documents(db_session) == 0

    def test_count_by_type(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            count_source_documents,
        )
        create_source_document(db_session, source_type="youtube_transcript")
        create_source_document(db_session, source_type="youtube_transcript")
        create_source_document(db_session, source_type="web_page")

        assert count_source_documents(db_session, source_type="youtube_transcript") == 2
        assert count_source_documents(db_session) == 3


class TestUpdateStatus:
    def test_update_existing(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document,
            update_source_document_status,
        )
        doc_id = create_source_document(db_session, source_type="web_page")
        assert update_source_document_status(db_session, doc_id, "degraded") is True
        doc = get_source_document(db_session, doc_id)
        assert doc["status"] == "degraded"

    def test_update_nonexistent(self, db_session):
        from signalvault.db.source_provenance import update_source_document_status
        assert update_source_document_status(db_session, "nonexist", "expired") is False


class TestGetByUrl:
    def test_find_by_url(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document_by_url,
        )
        create_source_document(
            db_session,
            source_type="web_page",
            source_url="https://example.com/page1",
            title="Page 1",
        )
        doc = get_source_document_by_url(db_session, "https://example.com/page1")
        assert doc is not None
        assert doc["title"] == "Page 1"

    def test_url_not_found(self, db_session):
        from signalvault.db.source_provenance import get_source_document_by_url
        assert get_source_document_by_url(db_session, "https://no-such.example.com") is None

    def test_url_with_type_filter(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            get_source_document_by_url,
        )
        create_source_document(
            db_session,
            source_type="youtube_transcript",
            source_url="https://youtube.com/watch?v=xyz",
        )
        # Same URL as youtube_transcript, but searching as web_page should not find
        doc = get_source_document_by_url(
            db_session, "https://youtube.com/watch?v=xyz", source_type="web_page",
        )
        assert doc is None
        # Without type filter should find
        doc2 = get_source_document_by_url(db_session, "https://youtube.com/watch?v=xyz")
        assert doc2 is not None


# ── SourceSegment CRUD ──────────────────────────────────────────────────────

class TestSourceSegmentCRUD:
    def test_create_and_get(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            get_segments,
        )
        doc_id = create_source_document(db_session, source_type="youtube_transcript")

        segments = [
            {
                "segment_id": "yt_001",
                "sequence_index": 0,
                "segment_type": "timestamp",
                "text_original": "Hello world",
                "start_time": "00:00:01.000",
                "end_time": "00:00:05.000",
                "content_hash": "h1",
            },
            {
                "segment_id": "yt_002",
                "sequence_index": 1,
                "segment_type": "timestamp",
                "text_original": "Second segment",
                "start_time": "00:00:05.000",
                "end_time": "00:00:10.000",
                "content_hash": "h2",
            },
        ]
        count = create_source_segments(db_session, doc_id, segments)
        assert count == 2

        results = get_segments(db_session, doc_id)
        assert len(results) == 2
        assert results[0]["segment_id"] == "yt_001"
        assert results[0]["text_original"] == "Hello world"
        assert results[1]["segment_id"] == "yt_002"

    def test_filter_by_type(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            get_segments,
        )
        doc_id = create_source_document(db_session, source_type="pdf_document")

        create_source_segments(db_session, doc_id, [
            {"segment_id": "p1", "segment_type": "page", "page_number": 1, "sequence_index": 0},
            {"segment_id": "c1", "segment_type": "comment", "sequence_index": 1},
        ])

        pages = get_segments(db_session, doc_id, segment_type="page")
        assert len(pages) == 1
        assert pages[0]["page_number"] == 1

    def test_empty_segments(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            get_segments,
        )
        doc_id = create_source_document(db_session, source_type="web_page")
        count = create_source_segments(db_session, doc_id, [])
        assert count == 0
        results = get_segments(db_session, doc_id)
        assert results == []

    def test_pdf_page_segment(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            get_segments,
        )
        doc_id = create_source_document(db_session, source_type="pdf_document")

        create_source_segments(db_session, doc_id, [
            {
                "segment_id": "page_1",
                "sequence_index": 0,
                "segment_type": "page",
                "text_original": "Page one content",
                "page_number": 1,
                "char_start": 0,
                "char_end": 100,
            },
        ])
        results = get_segments(db_session, doc_id)
        assert len(results) == 1
        assert results[0]["page_number"] == 1
        assert results[0]["text_original"] == "Page one content"
        assert results[0]["char_start"] == 0
        assert results[0]["char_end"] == 100

    def test_zsxq_segments(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            get_segments,
        )
        doc_id = create_source_document(
            db_session,
            source_type="zsxq_topic",
            access_scope="private_subscription",
        )
        create_source_segments(db_session, doc_id, [
            {
                "segment_id": "body_1",
                "segment_type": "topic_body",
                "text_original": "Topic full text here",
                "sequence_index": 0,
            },
            {
                "segment_id": "comment_1",
                "segment_type": "comment",
                "text_original": "User comment",
                "sequence_index": 1,
            },
        ])
        all_segs = get_segments(db_session, doc_id)
        assert len(all_segs) == 2

        body = get_segments(db_session, doc_id, segment_type="topic_body")
        assert len(body) == 1
        assert body[0]["segment_type"] == "topic_body"


class TestFindSegmentByLocator:
    def test_find_by_page(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            find_segment_by_locator,
        )
        doc_id = create_source_document(db_session, source_type="pdf_document")
        create_source_segments(db_session, doc_id, [
            {"segment_id": "p1", "segment_type": "page", "page_number": 1, "sequence_index": 0},
            {"segment_id": "p2", "segment_type": "page", "page_number": 2, "sequence_index": 1},
        ])
        seg = find_segment_by_locator(db_session, doc_id, page_number=2)
        assert seg is not None
        assert seg["segment_id"] == "p2"

    def test_find_by_timestamp(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            find_segment_by_locator,
        )
        doc_id = create_source_document(db_session, source_type="youtube_transcript")
        create_source_segments(db_session, doc_id, [
            {"segment_id": "t1", "segment_type": "timestamp", "start_time": "00:01:00", "sequence_index": 0},
            {"segment_id": "t2", "segment_type": "timestamp", "start_time": "00:02:00", "sequence_index": 1},
        ])
        seg = find_segment_by_locator(db_session, doc_id, timestamp="00:02:00")
        assert seg is not None
        assert seg["segment_id"] == "t2"

    def test_not_found(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            find_segment_by_locator,
        )
        doc_id = create_source_document(db_session, source_type="pdf_document")
        assert find_segment_by_locator(db_session, doc_id, page_number=99) is None


class TestCountSegments:
    def test_count(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            count_segments,
        )
        doc_id = create_source_document(db_session, source_type="web_page")
        create_source_segments(db_session, doc_id, [
            {"segment_id": f"s{i}", "sequence_index": i} for i in range(5)
        ])
        assert count_segments(db_session, doc_id) == 5


class TestDeleteSegments:
    def test_delete_all(self, db_session):
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            count_segments,
            delete_segments,
        )
        doc_id = create_source_document(db_session, source_type="web_page")
        create_source_segments(db_session, doc_id, [
            {"segment_id": "s1", "sequence_index": 0},
            {"segment_id": "s2", "sequence_index": 1},
        ])
        assert count_segments(db_session, doc_id) == 2
        deleted = delete_segments(db_session, doc_id)
        assert deleted == 2
        assert count_segments(db_session, doc_id) == 0

    def test_delete_none(self, db_session):
        from signalvault.db.source_provenance import delete_segments
        assert delete_segments(db_session, "nonexist") == 0


# ── Integration: end-to-end provenance chain ────────────────────────────────

class TestProvenanceChain:
    def test_full_cycle_youtube(self, db_session):
        """Simulate a YouTube transcript being stored as SourceDocument + Segments."""
        from signalvault.db.source_provenance import (
            compute_content_hash,
            create_source_document,
            create_source_segments,
            get_segments,
            get_source_document,
            count_segments,
        )
        # 1. Create the SourceDocument
        full_text = "[00:00:01] Welcome\n[00:00:05] Today we discuss AI"
        doc_id = create_source_document(
            db_session,
            source_type="youtube_transcript",
            title="AI Investment Interview",
            source_url="https://youtube.com/watch?v=test123",
            content_hash=compute_content_hash(full_text),
            language="en",
            original_language="en",
            access_scope="public_web",
        )

        # 2. Create segments from transcript
        segments = [
            {
                "segment_id": "seg_0",
                "sequence_index": 0,
                "segment_type": "timestamp",
                "text_original": "Welcome",
                "start_time": "00:00:01.000",
                "end_time": "00:00:04.999",
                "content_hash": compute_content_hash("Welcome"),
            },
            {
                "segment_id": "seg_1",
                "sequence_index": 1,
                "segment_type": "timestamp",
                "text_original": "Today we discuss AI",
                "start_time": "00:00:05.000",
                "end_time": "00:00:10.000",
                "content_hash": compute_content_hash("Today we discuss AI"),
            },
        ]
        created = create_source_segments(db_session, doc_id, segments)
        assert created == 2

        # 3. Verify the chain
        doc = get_source_document(db_session, doc_id)
        assert doc["source_type"] == "youtube_transcript"
        assert doc["title"] == "AI Investment Interview"

        segs = get_segments(db_session, doc_id)
        assert len(segs) == 2
        assert segs[0]["segment_type"] == "timestamp"
        assert segs[0]["start_time"] == "00:00:01.000"
        assert count_segments(db_session, doc_id) == 2

    def test_full_cycle_pdf(self, db_session):
        """Simulate a PDF being stored with page-level segments."""
        from signalvault.db.source_provenance import (
            create_source_document,
            create_source_segments,
            find_segment_by_locator,
        )
        doc_id = create_source_document(
            db_session,
            source_type="pdf_document",
            title="Annual Report 2025",
            source_path="/uploads/report.pdf",
            access_scope="uploaded_private",
        )
        segments = [
            {"segment_id": "page_1", "segment_type": "page", "page_number": 1,
             "text_original": "Cover page", "sequence_index": 0},
            {"segment_id": "page_2", "segment_type": "page", "page_number": 2,
             "text_original": "Executive summary...", "sequence_index": 1},
            {"segment_id": "page_3", "segment_type": "page", "page_number": 3,
             "text_original": "Financial data...", "sequence_index": 2},
        ]
        create_source_segments(db_session, doc_id, segments)

        # Locate page 3
        seg = find_segment_by_locator(db_session, doc_id, page_number=3)
        assert seg is not None
        assert seg["text_original"] == "Financial data..."
