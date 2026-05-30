"""P1-D: SQLite FTS5 全文搜索索引。

表: report_search_fts (FTS5 虚拟表)
    - 可直接重建，不作为主数据源
    - 若 SQLite 不支持 FTS5，记录日志并允许调用方 fallback
    - CJK 预处理：在连续 CJK 字符间插入空格，确保每个字符为独立 FTS token
"""

import logging
import re
from typing import Any

_CJK_RE = re.compile(r"([一-鿿㐀-䶿])")


def _tokenize_for_fts(text: str) -> str:
    """在 CJK 字符间插入空格，使得 FTS5 unicode61 能逐字索引。"""
    if not text:
        return ""
    text = _CJK_RE.sub(r" \1 ", text)
    return re.sub(r"\s+", " ", text).strip()

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FTS_TABLE = "report_search_fts"


def _has_fts5(session: Session) -> bool:
    """检查 SQLite 是否编译了 FTS5 支持。"""
    try:
        result = session.execute(
            text("SELECT sqlite_compile_option_get('SQLITE_ENABLE_FTS5')")  # SQLite 3.38+
        ).scalar()
        if result:
            return True
    except Exception:
        pass
    try:
        session.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(x)"))
        session.execute(text("DROP TABLE IF EXISTS _fts5_test"))
        session.commit()
        return True
    except Exception:
        return False


def ensure_fts_table(session: Session) -> bool:
    """创建 FTS5 虚拟表（如不存在且 SQLite 支持 FTS5）。返回是否可用的 bool。"""
    if not _has_fts5(session):
        logger.warning("SQLite 未编译 FTS5 支持，搜索将使用 LIKE fallback")
        return False
    try:
        # 如果旧表结构不兼容（如 contentless → 常规），先删除
        session.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        session.commit()
        session.execute(text(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
                report_id UNINDEXED,
                title,
                source_type,
                focus_areas,
                executive_summary,
                report_markdown,
                targets_text,
                entities_text,
                views_text,
                signals_text,
                source_url,
                video_id,
                tokenize='unicode61 remove_diacritics 2'
            )
        """))
        session.commit()
        return True
    except Exception:
        logger.warning("FTS5 表创建失败，搜索将使用 LIKE fallback", exc_info=True)
        return False


def rebuild_search_index(session: Session) -> int:
    """清空并重建 FTS 索引，返回索引的报告数量。"""
    if not ensure_fts_table(session):
        return 0

    from podcast_research.db.models import (
        EntityRecord,
        Episode,
        InvestmentViewRecord,
        Report,
        TrackingSignalRecord,
    )

    session.execute(text(f"DELETE FROM {FTS_TABLE}"))

    reports = session.query(Report).all()
    count = 0
    for report in reports:
        episode = session.query(Episode).filter_by(id=report.episode_id).first()
        views = session.query(InvestmentViewRecord).filter_by(report_id=report.id).all()
        signals = session.query(TrackingSignalRecord).filter_by(report_id=report.id).all()

        # 聚合 entities：从 extraction_json 中提取
        entities_text = _extract_entities_text(report.extraction_json)
        views_text = " | ".join(
            f"{v.target_name} {v.target_type} {v.view_direction} {v.logic_chain} {v.risk_warning or ''} {v.source_quote or ''} {v.evidence_detail or ''}"
            for v in views
        )
        targets_text = " | ".join(
            f"{v.target_name} {v.ticker or ''} {v.normalized_target_name or ''}" for v in views
        )
        signals_text = " | ".join(
            f"{s.target_name} {s.signal or ''} {s.trigger_condition or ''} {s.source_quote or ''}"
            for s in signals
        )

        title = episode.video_id or episode.title if episode else ""
        source_type = _infer_source_type_from_episode(episode)
        source_url = (episode.source_url or "") if episode else ""
        video_id = (episode.video_id or "") if episode else ""

        session.execute(
            text(
                f"INSERT INTO {FTS_TABLE}"
                " (report_id, title, source_type, focus_areas, executive_summary,"
                "  report_markdown, targets_text, entities_text, views_text, signals_text,"
                "  source_url, video_id)"
                " VALUES (:rid, :title, :st, :fa, :es, :rm, :tt, :et, :vt, :sigt, :su, :vi)"
            ),
            {
                "rid": report.id,
                "title": _tokenize_for_fts(title),
                "st": source_type,
                "fa": _tokenize_for_fts(report.focus_areas or ""),
                "es": _tokenize_for_fts(report.executive_summary or ""),
                "rm": _tokenize_for_fts(report.report_markdown or ""),
                "tt": _tokenize_for_fts(targets_text[:2000]),
                "et": _tokenize_for_fts(entities_text[:2000]),
                "vt": _tokenize_for_fts(views_text[:4000]),
                "sigt": _tokenize_for_fts(signals_text[:2000]),
                "su": source_url,
                "vi": video_id,
            },
        )
        count += 1

    session.commit()
    logger.info("FTS index rebuilt: %d reports indexed", count)
    return count


def _extract_entities_text(extraction_json: str) -> str:
    """从 extraction_json 中提取 entity name/type 用作索引。"""
    import json

    try:
        data = json.loads(extraction_json)
        entities = data.get("mentioned_entities", [])
        parts = []
        for e in entities:
            name = e.get("name", "") or e.get("entity_name", "") or ""
            etype = e.get("entity_type", "") or e.get("type", "") or ""
            parts.append(f"{name} {etype}")
        return " | ".join(parts)
    except (json.JSONDecodeError, TypeError):
        return ""


def _infer_source_type_from_episode(episode) -> str:
    if episode is None:
        return "local"
    if episode.video_id:
        return "youtube"
    if episode.source_url and ("youtube.com" in episode.source_url or "youtu.be" in episode.source_url):
        return "youtube"
    return "local"


def search_fts(session: Session, keyword: str, limit: int = 20) -> list[dict] | None:
    """使用 FTS5 全文搜索。返回 None 表示 FTS 不可用（需 fallback）。"""
    if not ensure_fts_table(session):
        return None

    # 检查是否已有索引数据
    cnt = session.execute(text(f"SELECT COUNT(*) FROM {FTS_TABLE}")).scalar()
    if cnt == 0:
        indexed = rebuild_search_index(session)
        if indexed == 0:
            return None

    try:
        safe_kw = _escape_fts_query(keyword)
        rows = session.execute(
            text(
                f"SELECT report_id, title, source_type, video_id,"
                f"  snippet({FTS_TABLE}, 2, '<mark>', '</mark>', '', 48) AS excerpt,"
                f"  rank AS score"
                f" FROM {FTS_TABLE}"
                f" WHERE {FTS_TABLE} MATCH :kw"
                f" ORDER BY rank"
                f" LIMIT :lim"
            ),
            {"kw": safe_kw, "lim": limit},
        ).fetchall()

        results = []
        seen_ids: set[int] = set()
        for row in rows:
            rid = row[0]
            if rid in seen_ids:
                continue
            seen_ids.add(rid)

            excerpt = _clean_fts_excerpt(row[4] or "")
            results.append({
                "report_id": rid,
                "match_type": "fts",
                "match_excerpt": excerpt or keyword,
                "source_type": row[2] or "local",
                "title": row[1] or "",
                "video_id": row[3] or "",
                "created_at": None,
                "score": row[5],
            })

        return results[:limit]
    except Exception:
        logger.warning("FTS5 查询失败，回退到 LIKE 搜索", exc_info=True)
        return None


def _escape_fts_query(keyword: str) -> str:
    """转义 FTS5 查询中的特殊字符，CJK 字符间插空格后 AND 匹配。"""
    special = '!"#$%&()*+,./:;<=>?@[\\]^`{|}~\x00'
    escaped = ""
    for ch in keyword:
        if ch in special:
            escaped += " "
        else:
            escaped += ch
    # CJK 字符间距化，与索引时的 tokenize 一致
    tokenized = _tokenize_for_fts(escaped)
    terms = [t for t in tokenized.split() if t]
    if not terms:
        return '""'
    return " AND ".join(terms)


def _clean_fts_excerpt(text: str) -> str:
    """清理 FTS snippet 输出的标记，确保终端安全。"""
    import re

    text = re.sub(r"<mark>|</mark>", "", text)
    text = "".join(c for c in text if ord(c) <= 0xFFFF)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 80:
        text = text[:80] + "..."
    return text
