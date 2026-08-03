"""M4-A: ProcessingJob Manager 测试。

验证 ProcessingJob CRUD 操作、状态机和成本统计。
"""

from __future__ import annotations

import pytest

from signalvault.db.session import get_session, init_db, reset_engine
from signalvault.services.source_item_manager import SourceItemManager
from signalvault.services.processing_job_manager import ProcessingJobManager


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """每个测试使用独立的数据库。"""
    from signalvault.db.session import init_engine

    # 使用临时文件作为数据库
    db_file = tmp_path / "test.db"
    init_engine(str(db_file))
    init_db(str(db_file))
    yield
    reset_engine()


@pytest.fixture
def sample_source_item():
    """创建测试用的 SourceItem。"""
    return SourceItemManager.create(
        source_type="youtube_video",
        source_uri="https://www.youtube.com/watch?v=test123",
    )


def test_create_processing_job(sample_source_item):
    """创建 ProcessingJob 并验证字段。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
        params={"language": "zh"},
    )

    assert job.id is not None
    assert job.source_item_id == sample_source_item.id
    assert job.job_type == "extract_text"
    assert job.status == "pending"
    assert job.priority == 5
    assert job.max_retries == 3


def test_get_processing_job_by_id(sample_source_item):
    """通过 ID 获取 ProcessingJob。"""
    created = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    retrieved = ProcessingJobManager.get(created.id)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.job_type == "analyze"


def test_get_next_pending_job(sample_source_item):
    """获取下一个待处理的任务（按优先级排序）。"""
    # 创建不同优先级的任务
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
        priority=3,
    )
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
        priority=9,  # 更高优先级
    )

    next_job = ProcessingJobManager.get_next_pending()
    assert next_job is not None
    assert next_job.priority == 9
    assert next_job.job_type == "extract_text"


def test_get_pending_jobs_with_filter(sample_source_item):
    """获取待处理任务列表（带类型过滤）。"""
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
    )
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    jobs = ProcessingJobManager.get_pending_jobs(job_type="analyze")
    assert len(jobs) >= 1
    assert all(job.job_type == "analyze" for job in jobs)


def test_mark_job_running(sample_source_item):
    """标记任务为运行中。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
    )

    success = ProcessingJobManager.mark_running(job.id)
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.status == "running"
    assert updated.started_at is not None


def test_mark_job_completed(sample_source_item):
    """标记任务为已完成。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    success = ProcessingJobManager.mark_completed(
        job.id, result_type="research_asset", result_ref=123
    )
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.status == "completed"
    assert updated.completed_at is not None
    assert updated.result_type == "research_asset"
    assert updated.result_ref == 123


def test_mark_job_failed(sample_source_item):
    """标记任务为失败。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    success = ProcessingJobManager.mark_failed(
        job.id, error_message="LLM API timeout"
    )
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.status == "failed"
    assert updated.error_message == "LLM API timeout"
    assert updated.retry_count == 1


def test_reset_for_retry(sample_source_item):
    """重置失败任务以重试。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
        max_retries=3,  # 允许 3 次重试
    )

    # 标记为失败（retry_count = 1）
    ProcessingJobManager.mark_failed(job.id, "Error 1")

    # 第一次重试应该成功（retry_count 1 < max_retries 3）
    success = ProcessingJobManager.reset_for_retry(job.id)
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.status == "pending"
    assert updated.started_at is None
    assert updated.error_message == ""

    # 模拟重试后又失败（retry_count = 2）
    ProcessingJobManager.mark_failed(job.id, "Error 2")

    # 还可以再重试一次（retry_count 2 < max_retries 3）
    success = ProcessingJobManager.reset_for_retry(job.id)
    assert success is True

    # 第三次失败后（retry_count = 3），重试次数耗尽
    ProcessingJobManager.mark_failed(job.id, "Error 3")
    success = ProcessingJobManager.reset_for_retry(job.id)
    assert success is False


def test_update_cost(sample_source_item):
    """更新成本统计。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    success = ProcessingJobManager.update_cost(
        job.id, llm_calls=3, tokens_used=5000, duration_seconds=120
    )
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.llm_calls == 3
    assert updated.tokens_used == 5000
    assert updated.duration_seconds == 120


def test_cancel_job(sample_source_item):
    """取消任务。"""
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    success = ProcessingJobManager.cancel(job.id)
    assert success is True

    updated = ProcessingJobManager.get(job.id)
    assert updated.status == "cancelled"
    assert updated.completed_at is not None


def test_count_by_status(sample_source_item):
    """统计各状态的任务数量。"""
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
    )
    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )
    ProcessingJobManager.mark_running(job.id)

    counts = ProcessingJobManager.count_by_status()
    assert counts.get("pending", 0) >= 1
    assert counts.get("running", 0) >= 1


def test_get_jobs_by_source_item(sample_source_item):
    """获取某个 SourceItem 的所有任务。"""
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
    )
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    jobs = ProcessingJobManager.get_jobs_by_source_item(sample_source_item.id)
    assert len(jobs) >= 2
    assert all(job.source_item_id == sample_source_item.id for job in jobs)


def test_get_running_jobs(sample_source_item):
    """获取所有运行中的任务。"""
    job1 = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="extract_text",
    )
    job2 = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
    )

    ProcessingJobManager.mark_running(job1.id)
    ProcessingJobManager.mark_running(job2.id)

    running = ProcessingJobManager.get_running_jobs()
    assert len(running) >= 2
    assert all(job.status == "running" for job in running)


def test_priority_ordering(sample_source_item):
    """验证优先级排序：高优先级任务先被取出。"""
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="low_priority",
        priority=1,
    )
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="high_priority",
        priority=10,
    )
    ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="medium_priority",
        priority=5,
    )

    next_job = ProcessingJobManager.get_next_pending()
    assert next_job.priority == 10
    assert next_job.job_type == "high_priority"


def test_params_json_storage(sample_source_item):
    """验证 params 字段正确存储和读取 JSON。"""
    import json

    params = {
        "focus": "AI investment",
        "depth": "deep",
        "limit": 10,
        "metadata": {"nested": "value"},
    }

    job = ProcessingJobManager.create(
        source_item_id=sample_source_item.id,
        job_type="analyze",
        params=params,
    )

    retrieved = ProcessingJobManager.get(job.id)
    retrieved_params = json.loads(retrieved.params)

    assert retrieved_params["focus"] == "AI investment"
    assert retrieved_params["depth"] == "deep"
    assert retrieved_params["metadata"]["nested"] == "value"