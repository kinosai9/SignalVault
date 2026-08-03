-- M4-A: Source Lifecycle 统一
-- 从 ingest_jobs 拆分为 source_items + processing_jobs
-- 日期：2026-08-03

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. 创建 source_items 表
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS source_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 来源标识
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,

    -- 内容元数据
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',

    -- 内容追踪
    content_hash TEXT DEFAULT '',
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provenance TEXT DEFAULT '',

    -- 状态管理
    status TEXT DEFAULT 'captured',

    -- 关联
    source_document_id TEXT,

    -- 用户反馈
    user_rating TEXT DEFAULT '',
    user_notes TEXT DEFAULT '',

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_source_items_type ON source_items(source_type);
CREATE INDEX IF NOT EXISTS idx_source_items_hash ON source_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_source_items_status ON source_items(status);
CREATE INDEX IF NOT EXISTS idx_source_items_captured ON source_items(captured_at);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. 创建 processing_jobs 表
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 任务定义
    source_item_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,

    -- 参数
    params TEXT DEFAULT '{}',

    -- 状态管理
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- 结果
    result_type TEXT DEFAULT '',
    result_ref INTEGER,
    error_message TEXT DEFAULT '',

    -- 成本统计
    llm_calls INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,

    -- 重试
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_source ON processing_jobs(source_item_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_type ON processing_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_priority ON processing_jobs(priority);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. 数据迁移：ingest_jobs → source_items + processing_jobs
-- ═════════════════════════════════════════════════════════════──════════════════

-- 3.1 迁移到 source_items
INSERT INTO source_items (
    source_type,
    source_uri,
    title,
    metadata,
    content_hash,
    captured_at,
    provenance,
    status,
    source_document_id,
    created_at,
    updated_at
)
SELECT
    -- source_type 映射
    CASE
        WHEN source_type = 'url_import' THEN 'web_page'
        WHEN source_type = 'file_upload' THEN 'text_file'
        WHEN source_type = 'pdf_upload' THEN 'pdf_document'
        WHEN source_type = 'zsxq_topic' THEN 'zsxq_topic'
        WHEN source_type = 'tracked_entry' THEN 'web_page'
        WHEN source_type = 'source_profile' THEN 'web_page'
        ELSE source_type
    END,
    -- source_uri（取第一个可用的）
    COALESCE(source_url, source_name, ''),
    -- title
    COALESCE(source_name, ''),
    -- metadata（JSON）
    json_object(
        'original_source_type', source_type,
        'preview_id', preview_id,
        'source_hash', source_hash
    ),
    -- content_hash
    source_hash,
    -- captured_at
    created_at,
    -- provenance
    'migrated_from_ingest_jobs',
    -- status（映射）
    CASE
        WHEN status IN ('pending_preview', 'preview_failed') THEN 'captured'
        WHEN status IN ('confirmed_archive', 'auto_archived', 'confirmed_deep_notes', 'confirmed_derived_only', 'confirmed_linked', 'overwritten') THEN 'processed'
        WHEN status IN ('skipped', 'auto_ignored', 'expired') THEN 'archived'
        WHEN status = 'failed' THEN 'failed'
        ELSE 'captured'
    END,
    -- source_document_id（空）
    NULL,
    -- created_at
    created_at,
    -- updated_at
    updated_at
FROM ingest_jobs;

-- 3.2 迁移到 processing_jobs
INSERT INTO processing_jobs (
    source_item_id,
    job_type,
    priority,
    params,
    status,
    started_at,
    completed_at,
    result_type,
    result_ref,
    error_message,
    created_at
)
SELECT
    -- source_item_id（关联新创建的 source_items）
    (SELECT id FROM source_items WHERE
        content_hash = ij.source_hash
        AND captured_at = ij.created_at
        LIMIT 1
    ),
    -- job_type（根据状态推断）
    CASE
        WHEN ij.status IN ('pending_preview', 'preview_failed') THEN 'extract_text'
        WHEN ij.status IN ('confirmed_archive', 'auto_archived') THEN 'analyze'
        ELSE 'extract_text'
    END,
    -- priority
    5,
    -- params（JSON）
    json_object(
        'action', ij.action,
        'action_label', ij.action_label
    ),
    -- status（映射）
    CASE
        WHEN ij.status = 'pending_preview' THEN 'pending'
        WHEN ij.status = 'preview_failed' THEN 'failed'
        WHEN ij.status IN ('confirmed_archive', 'auto_archived', 'skipped', 'auto_ignored', 'expired') THEN 'completed'
        ELSE 'pending'
    END,
    -- started_at
    NULL,
    -- completed_at
    CASE
        WHEN ij.status IN ('confirmed_archive', 'auto_archived', 'skipped', 'auto_ignored', 'expired') THEN ij.updated_at
        ELSE NULL
    END,
    -- result_type
    CASE
        WHEN ij.status IN ('confirmed_archive', 'auto_archived') THEN 'research_asset'
        ELSE ''
    END,
    -- result_ref（空）
    NULL,
    -- error_message
    CASE
        WHEN ij.status = 'preview_failed' THEN 'Preview failed during migration'
        ELSE ''
    END,
    -- created_at
    ij.created_at
FROM ingest_jobs ij;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 4. 创建 claims 表（M4-B）
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 判断内容
    claim_text TEXT NOT NULL,
    claim_type TEXT DEFAULT 'prediction',

    -- 置信度
    confidence REAL DEFAULT 0.0,
    confidence_source TEXT DEFAULT '',

    -- 来源追溯
    source_report_id INTEGER NOT NULL,
    source_view_id INTEGER,
    source_quote TEXT DEFAULT '',
    timestamp TEXT DEFAULT '',
    evidence_page INTEGER,

    -- 支持证据
    supporting_sources TEXT DEFAULT '[]',

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_claims_report ON claims(source_report_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 5. 更新 schema_version
-- ═══════════════════════════════════════════════════════════════════════════════

INSERT INTO schema_version (version, description, applied_at)
VALUES (4, 'M4-A: Source Lifecycle unified - source_items + processing_jobs + claims', CURRENT_TIMESTAMP);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 6. 验证迁移结果
-- ═══════════════════════════════════════════════════════════════════════════════

-- 检查迁移数量
SELECT
    'ingest_jobs' AS source_table,
    COUNT(*) AS count
FROM ingest_jobs
UNION ALL
SELECT
    'source_items' AS source_table,
    COUNT(*) AS count
FROM source_items
UNION ALL
SELECT
    'processing_jobs' AS source_table,
    COUNT(*) AS count
FROM processing_jobs;