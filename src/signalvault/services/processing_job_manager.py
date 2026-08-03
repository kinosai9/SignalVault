"""M4-A: ProcessingJob Manager - Processing Pipeline Task CRUD.

提供 ProcessingJob 的创建、查询、状态更新、成本统计等操作。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from signalvault.db.models import ProcessingJob

logger = logging.getLogger(__name__)


class ProcessingJobManager:
    """ProcessingJob CRUD 管理器"""

    @staticmethod
    def create(
        source_item_id: int,
        job_type: str,
        *,
        priority: int = 5,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
        session: Session | None = None,
    ) -> ProcessingJob:
        """创建新的 ProcessingJob

        Args:
            source_item_id: 关联的 SourceItem ID
            job_type: 任务类型（extract_text / OCR / analyze / summarize / embed / sync_graph）
            priority: 优先级（0-9，越高越优先）
            params: 任务参数
            max_retries: 最大重试次数
            session: 数据库会话

        Returns:
            新创建的 ProcessingJob 对象
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = ProcessingJob(
            source_item_id=source_item_id,
            job_type=job_type,
            priority=priority,
            params=json.dumps(params or {}, ensure_ascii=False),
            max_retries=max_retries,
        )

        session.add(job)
        session.commit()
        session.refresh(job)

        logger.info(
            f"Created ProcessingJob id={job.id} type={job_type} source_item={source_item_id}"
        )
        return job

    @staticmethod
    def get(job_id: int, session: Session | None = None) -> ProcessingJob | None:
        """根据 ID 获取 ProcessingJob"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return session.query(ProcessingJob).filter_by(id=job_id).first()

    @staticmethod
    def get_next_pending(session: Session | None = None) -> ProcessingJob | None:
        """获取下一个待处理的任务（按优先级排序）

        Returns:
            优先级最高的 pending 任务，如果没有则返回 None
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return (
            session.query(ProcessingJob)
            .filter_by(status="pending")
            .order_by(desc(ProcessingJob.priority), ProcessingJob.created_at)
            .first()
        )

    @staticmethod
    def get_pending_jobs(
        limit: int = 100,
        job_type: str | None = None,
        session: Session | None = None,
    ) -> list[ProcessingJob]:
        """获取待处理任务列表

        Args:
            limit: 数量限制
            job_type: 过滤任务类型
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        query = session.query(ProcessingJob).filter_by(status="pending")

        if job_type:
            query = query.filter_by(job_type=job_type)

        return query.order_by(desc(ProcessingJob.priority), ProcessingJob.created_at).limit(limit).all()

    @staticmethod
    def mark_running(job_id: int, session: Session | None = None) -> bool:
        """标记任务为运行中

        Args:
            job_id: ProcessingJob ID
            session: 数据库会话

        Returns:
            True if updated, False if not found
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        job.status = "running"
        job.started_at = datetime.now()
        session.commit()

        logger.info(f"Marked ProcessingJob id={job_id} as running")
        return True

    @staticmethod
    def mark_completed(
        job_id: int,
        result_type: str = "",
        result_ref: int | None = None,
        session: Session | None = None,
    ) -> bool:
        """标记任务为已完成

        Args:
            job_id: ProcessingJob ID
            result_type: 结果类型（research_asset / error）
            result_ref: 关联的 ResearchAsset ID
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        job.status = "completed"
        job.completed_at = datetime.now()
        job.result_type = result_type
        if result_ref:
            job.result_ref = result_ref
        session.commit()

        logger.info(f"Marked ProcessingJob id={job_id} as completed result_type={result_type}")
        return True

    @staticmethod
    def mark_failed(
        job_id: int,
        error_message: str,
        session: Session | None = None,
    ) -> bool:
        """标记任务为失败

        Args:
            job_id: ProcessingJob ID
            error_message: 错误信息
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        job.status = "failed"
        job.completed_at = datetime.now()
        job.error_message = error_message
        job.retry_count += 1
        session.commit()

        logger.error(f"Marked ProcessingJob id={job_id} as failed: {error_message[:200]}")
        return True

    @staticmethod
    def reset_for_retry(job_id: int, session: Session | None = None) -> bool:
        """重置失败任务以重试

        Args:
            job_id: ProcessingJob ID
            session: 数据库会话

        Returns:
            True if reset, False if not found or retry count exceeded
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        if job.retry_count >= job.max_retries:
            logger.warning(
                f"ProcessingJob id={job_id} exceeded max_retries={job.max_retries}"
            )
            return False

        job.status = "pending"
        job.started_at = None
        job.completed_at = None
        job.error_message = ""
        session.commit()

        logger.info(f"Reset ProcessingJob id={job_id} for retry (attempt {job.retry_count + 1})")
        return True

    @staticmethod
    def update_cost(
        job_id: int,
        llm_calls: int = 0,
        tokens_used: int = 0,
        duration_seconds: int = 0,
        session: Session | None = None,
    ) -> bool:
        """更新成本统计

        Args:
            job_id: ProcessingJob ID
            llm_calls: LLM 调用次数
            tokens_used: Token 消耗
            duration_seconds: 执行时长
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        job.llm_calls = llm_calls
        job.tokens_used = tokens_used
        job.duration_seconds = duration_seconds
        session.commit()

        logger.info(
            f"Updated cost for ProcessingJob id={job_id}: "
            f"llm_calls={llm_calls} tokens={tokens_used} duration={duration_seconds}s"
        )
        return True

    @staticmethod
    def cancel(job_id: int, session: Session | None = None) -> bool:
        """取消任务"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        job = session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return False

        job.status = "cancelled"
        job.completed_at = datetime.now()
        session.commit()

        logger.info(f"Cancelled ProcessingJob id={job_id}")
        return True

    @staticmethod
    def count_by_status(session: Session | None = None) -> dict[str, int]:
        """统计各状态的任务数量"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        from sqlalchemy import func

        result = (
            session.query(ProcessingJob.status, func.count(ProcessingJob.id))
            .group_by(ProcessingJob.status)
            .all()
        )

        return {status: count for status, count in result}

    @staticmethod
    def get_jobs_by_source_item(
        source_item_id: int,
        session: Session | None = None,
    ) -> list[ProcessingJob]:
        """获取某个 SourceItem 的所有任务"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return (
            session.query(ProcessingJob)
            .filter_by(source_item_id=source_item_id)
            .order_by(ProcessingJob.created_at)
            .all()
        )

    @staticmethod
    def get_running_jobs(session: Session | None = None) -> list[ProcessingJob]:
        """获取所有运行中的任务"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return (
            session.query(ProcessingJob)
            .filter_by(status="running")
            .order_by(ProcessingJob.started_at)
            .all()
        )
