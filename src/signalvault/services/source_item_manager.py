"""M4-A: SourceItem Manager - Source Lifecycle CRUD.

提供 SourceItem 的创建、查询、状态更新等操作。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from signalvault.db.models import SourceItem

logger = logging.getLogger(__name__)


class SourceItemManager:
    """SourceItem CRUD 管理器"""

    @staticmethod
    def create(
        source_type: str,
        source_uri: str,
        *,
        title: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        content_hash: str = "",
        provenance: str = "user_intake",
        source_document_id: str | None = None,
        session: Session | None = None,
    ) -> SourceItem:
        """创建新的 SourceItem

        Args:
            source_type: 来源类型（youtube_video / pdf_document / web_page / text_file）
            source_uri: 来源 URI（URL / 文件路径）
            title: 标题
            description: 描述
            metadata: 扩展元数据
            content_hash: 内容哈希
            provenance: 来源说明（user_intake / auto_discover / refresh）
            source_document_id: 关联的 SourceDocument ID
            session: 数据库会话（可选）

        Returns:
            新创建的 SourceItem 对象
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        item = SourceItem(
            source_type=source_type,
            source_uri=source_uri,
            title=title,
            description=description,
            extra_metadata=json.dumps(metadata or {}, ensure_ascii=False),
            content_hash=content_hash,
            provenance=provenance,
            status="captured",
            source_document_id=source_document_id,
        )

        session.add(item)
        session.commit()
        session.refresh(item)

        logger.info(
            f"Created SourceItem id={item.id} type={source_type} uri={source_uri[:100]}"
        )
        return item

    @staticmethod
    def get(item_id: int, session: Session | None = None) -> SourceItem | None:
        """根据 ID 获取 SourceItem"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return session.query(SourceItem).filter_by(id=item_id).first()

    @staticmethod
    def get_by_uri(source_uri: str, session: Session | None = None) -> SourceItem | None:
        """根据 URI 获取 SourceItem"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return session.query(SourceItem).filter_by(source_uri=source_uri).first()

    @staticmethod
    def get_by_hash(content_hash: str, session: Session | None = None) -> SourceItem | None:
        """根据内容哈希获取 SourceItem（用于去重）"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return session.query(SourceItem).filter_by(content_hash=content_hash).first()

    @staticmethod
    def update_status(
        item_id: int,
        status: str,
        session: Session | None = None,
    ) -> bool:
        """更新 SourceItem 状态

        Args:
            item_id: SourceItem ID
            status: 新状态（captured / processing / processed / archived / failed）
            session: 数据库会话

        Returns:
            True if updated, False if not found
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        item = session.query(SourceItem).filter_by(id=item_id).first()
        if not item:
            return False

        item.status = status
        item.updated_at = datetime.now()
        session.commit()

        logger.info(f"Updated SourceItem id={item_id} status={status}")
        return True

    @staticmethod
    def set_source_document(
        item_id: int,
        source_document_id: str,
        session: Session | None = None,
    ) -> bool:
        """关联 SourceDocument"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        item = session.query(SourceItem).filter_by(id=item_id).first()
        if not item:
            return False

        item.source_document_id = source_document_id
        item.updated_at = datetime.now()
        session.commit()

        logger.info(
            f"Linked SourceItem id={item_id} to SourceDocument id={source_document_id}"
        )
        return True

    @staticmethod
    def set_user_feedback(
        item_id: int,
        rating: str,
        notes: str = "",
        session: Session | None = None,
    ) -> bool:
        """设置用户反馈

        Args:
            item_id: SourceItem ID
            rating: 评分（valuable / neutral / irrelevant）
            notes: 用户备注
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        item = session.query(SourceItem).filter_by(id=item_id).first()
        if not item:
            return False

        item.user_rating = rating
        item.user_notes = notes
        item.updated_at = datetime.now()
        session.commit()

        logger.info(f"Set user feedback for SourceItem id={item_id} rating={rating}")
        return True

    @staticmethod
    def get_pending(
        limit: int = 100,
        session: Session | None = None,
    ) -> list[SourceItem]:
        """获取待处理的 SourceItem（status=captured）"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return (
            session.query(SourceItem)
            .filter_by(status="captured")
            .order_by(SourceItem.created_at)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_by_status(
        status: str,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[SourceItem]:
        """按状态查询 SourceItem"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        return (
            session.query(SourceItem)
            .filter_by(status=status)
            .order_by(desc(SourceItem.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def count_by_status(session: Session | None = None) -> dict[str, int]:
        """统计各状态的 SourceItem 数量"""
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        from sqlalchemy import func

        result = (
            session.query(SourceItem.status, func.count(SourceItem.id))
            .group_by(SourceItem.status)
            .all()
        )

        return {status: count for status, count in result}

    @staticmethod
    def search(
        query: str,
        source_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        session: Session | None = None,
    ) -> list[SourceItem]:
        """搜索 SourceItem

        Args:
            query: 搜索关键词（匹配 title / source_uri）
            source_type: 过滤来源类型
            status: 过滤状态
            limit: 结果数量限制
            session: 数据库会话
        """
        if session is None:
            from signalvault.db.session import get_session

            session = get_session()

        filters = []
        if query:
            filters.append(
                or_(
                    SourceItem.title.contains(query),
                    SourceItem.source_uri.contains(query),
                )
            )
        if source_type:
            filters.append(SourceItem.source_type == source_type)
        if status:
            filters.append(SourceItem.status == status)

        return (
            session.query(SourceItem)
            .filter(and_(*filters))
            .order_by(desc(SourceItem.created_at))
            .limit(limit)
            .all()
        )
