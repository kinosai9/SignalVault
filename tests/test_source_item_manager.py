"""M4-A: SourceItem Manager 测试。

验证 SourceItem CRUD 操作。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from signalvault.db.session import get_session, reset_engine
from signalvault.services.source_item_manager import SourceItemManager


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """每个测试使用独立的数据库。"""
    from signalvault.db.session import init_engine, init_db

    # 使用临时文件作为数据库
    db_file = tmp_path / "test.db"
    init_engine(str(db_file))
    init_db(str(db_file))
    yield
    reset_engine()


def test_create_source_item():
    """创建 SourceItem 并验证字段。"""
    item = SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=test123",
        title="Test Video",
        metadata={"video_id": "test123", "duration": 600},
    )

    assert item.id is not None
    assert item.source_type == "youtube_video"
    assert item.source_uri == "https://www.youtube.com/watch?v=test123"
    assert item.title == "Test Video"
    assert item.status == "captured"
    assert item.provenance == "user_intake"


def test_get_source_item_by_id():
    """通过 ID 获取 SourceItem。"""
    created = SourceItemManager.create(
        source_type="pdf_document",
        source_uri="/path/to/report.pdf",
    )

    retrieved = SourceItemManager.get(created.id)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.source_type == "pdf_document"


def test_get_source_item_by_uri():
    """通过 URI 获取 SourceItem。"""
    SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/article",
    )

    retrieved = SourceItemManager.get_by_uri("https://example.com/article")
    assert retrieved is not None
    assert retrieved.source_type == "web_page"


def test_get_source_item_by_hash():
    """通过内容哈希获取 SourceItem（用于去重）。"""
    SourceItemManager.create(
        source_type="text_file",
        source_uri="/path/to/notes.txt",
        content_hash="abc123def456",
    )

    retrieved = SourceItemManager.get_by_hash("abc123def456")
    assert retrieved is not None
    assert retrieved.content_hash == "abc123def456"


def test_update_status():
    """更新 SourceItem 状态。"""
    item = SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/test",
    )

    assert item.status == "captured"

    success = SourceItemManager.update_status(item.id, "processing")
    assert success is True

    updated = SourceItemManager.get(item.id)
    assert updated.status == "processing"


def test_set_source_document():
    """关联 SourceDocument。"""
    item = SourceItemManager.create(
        source_type="pdf_document",
        source_uri="/path/to/doc.pdf",
    )

    success = SourceItemManager.set_source_document(item.id, "source_doc_001")
    assert success is True

    updated = SourceItemManager.get(item.id)
    assert updated.source_document_id == "source_doc_001"


def test_set_user_feedback():
    """设置用户反馈。"""
    item = SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/test",
    )

    success = SourceItemManager.set_user_feedback(
        item.id, rating="valuable", notes="High-quality source"
    )
    assert success is True

    updated = SourceItemManager.get(item.id)
    assert updated.user_rating == "valuable"
    assert updated.user_notes == "High-quality source"


def test_get_pending_items():
    """获取待处理的 SourceItem 列表。"""
    # 使用唯一 URI 避免测试污染
    import uuid

    unique_id = str(uuid.uuid4())[:8]
    SourceItemManager.create(
        source_type="web_page",
        source_uri=f"https://example.com/pending1-{unique_id}",
    )
    SourceItemManager.create(
        source_type="web_page",
        source_uri=f"https://example.com/pending2-{unique_id}",
    )
    processed = SourceItemManager.create(
        source_type="web_page",
        source_uri=f"https://example.com/processed-{unique_id}",
    )
    SourceItemManager.update_status(processed.id, "processed")

    # 只检查当前测试创建的 items
    pending = SourceItemManager.get_pending(limit=10)
    test_items = [item for item in pending if unique_id in item.source_uri]
    assert len(test_items) == 2
    assert all(item.status == "captured" for item in test_items)


def test_count_by_status():
    """统计各状态的 SourceItem 数量。"""
    SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/captured1",
    )
    SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/captured2",
    )
    item = SourceItemManager.create(
        source_type="web_page",
        source_uri="https://example.com/processed",
    )
    SourceItemManager.update_status(item.id, "processed")

    counts = SourceItemManager.count_by_status()
    assert counts.get("captured", 0) >= 2
    assert counts.get("processed", 0) >= 1


def test_search_by_title():
    """搜索 SourceItem（按标题）。"""
    SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=ai",
        title="AI Investment Trends 2024",
    )
    SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=nvidia",
        title="NVIDIA GPU Architecture",
    )

    results = SourceItemManager.search(query="AI")
    assert len(results) >= 1
    assert any("AI" in item.title for item in results)


def test_search_with_filters():
    """搜索 SourceItem（带过滤条件）。"""
    SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=test1",
        title="Test Video 1",
    )
    SourceItemManager.create(
        source_type="pdf_document",
        source_uri="/path/to/test.pdf",
        title="Test PDF",
    )

    results = SourceItemManager.search(
        query="Test", source_type="pdf_document"
    )
    assert len(results) >= 1
    assert all(item.source_type == "pdf_document" for item in results)


def test_metadata_field_workaround():
    """验证 metadata 字段使用 extra_metadata 属性名避开保留字。"""
    item = SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=test",
        metadata={"key": "value", "number": 42},
    )

    # 从数据库重新读取
    retrieved = SourceItemManager.get(item.id)
    assert retrieved is not None

    # 验证 extra_metadata 字段可访问
    import json

    metadata_dict = json.loads(retrieved.extra_metadata)
    assert metadata_dict["key"] == "value"
    assert metadata_dict["number"] == 42