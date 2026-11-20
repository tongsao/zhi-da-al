-- =============================================
-- 季报 AI 质检模块 建表脚本（PostgreSQL 版）
-- 表前缀统一为 zd_（zd_project_info / zd_ai_check_result / zd_ai_check_rule）
-- 与 model/models.py 中 ORM 模型保持一致
-- 注意：MySQL 版保留在 create_ai_check_tables.sql，供回滚/对照使用
-- =============================================

-- 项目信息表：存储上游信披中心推送的结构化数据，作为校验的比对基准
CREATE TABLE IF NOT EXISTS zd_project_info (
    id           SERIAL        PRIMARY KEY,
    project_id   VARCHAR(100)  NOT NULL,
    project_name VARCHAR(255)  NULL,
    year         INTEGER       NULL,
    month        INTEGER       NULL,
    quarter_type INTEGER       NULL,
    amount       DECIMAL(20,2) NULL,
    discloser    VARCHAR(255)  NULL,
    created_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_project_id UNIQUE (project_id)
);
COMMENT ON TABLE zd_project_info IS '季报项目信息表';
COMMENT ON COLUMN zd_project_info.amount IS '金额（单位:元），DECIMAL 保证金融对账精度';

CREATE INDEX IF NOT EXISTS idx_project_id ON zd_project_info (project_id);

-- 质检结果状态表：存储推送的披露文件信息与每次校验的状态/明细，默认状态为未质检(pending)
CREATE TABLE IF NOT EXISTS zd_ai_check_result (
    id           SERIAL       PRIMARY KEY,
    project_id   VARCHAR(100) NOT NULL,
    file_name    VARCHAR(255) NOT NULL,
    file_path    VARCHAR(255) NULL,
    file_type    VARCHAR(50)  NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',
    check_detail JSONB        NULL,
    recheck_from INTEGER      NULL,
    error_msg    TEXT         NULL,
    create_date  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_date  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE zd_ai_check_result IS 'AI质检结果状态表';
COMMENT ON COLUMN zd_ai_check_result.status IS '校验状态: pending=未质检/in_progress=质检中/success=一致/failed=不一致/error=质检异常';
COMMENT ON COLUMN zd_ai_check_result.check_detail IS '校验明细: 各字段抽取值/业务值/比对结果/原因';

CREATE INDEX IF NOT EXISTS idx_ai_check_project_id ON zd_ai_check_result (project_id);
CREATE INDEX IF NOT EXISTS idx_ai_check_file_name ON zd_ai_check_result (file_name);
CREATE INDEX IF NOT EXISTS idx_ai_check_status ON zd_ai_check_result (status);

-- AI质检规则表：开发预置的校验规则（字段+比对方式+是否启用），业务在页面开关
CREATE TABLE IF NOT EXISTS zd_ai_check_rule (
    id           SERIAL        PRIMARY KEY,
    field_name   VARCHAR(50)   NOT NULL,
    field_label  VARCHAR(50)   NOT NULL,
    compare_type VARCHAR(20)   NOT NULL,
    tolerance    DECIMAL(20,2) NULL,
    enabled      INTEGER       NOT NULL DEFAULT 1,
    created_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_field_name UNIQUE (field_name)
);
COMMENT ON TABLE zd_ai_check_rule IS 'AI质检规则表';

-- 预置 4 条默认规则（与 service/aiCheckService.py 中 DEFAULT_RULES 一致）
INSERT INTO zd_ai_check_rule (field_name, field_label, compare_type, tolerance, enabled) VALUES
    ('disclosure_date', '披露日期', 'quarter_match', NULL, 1),
    ('amount', '金额', 'amount_diff', 0.01, 1),
    ('discloser', '披露人', 'name_normalized', NULL, 1),
    ('title', '公告标题', 'string_exact', NULL, 1)
ON CONFLICT (field_name) DO NOTHING;

-- =============================================
-- 向量表由 langchain-postgres PGVector 自动创建：
--   langchain_pg_collection / langchain_pg_embedding
-- 无需在建表脚本中重复定义
-- =============================================
