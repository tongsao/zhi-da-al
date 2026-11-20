-- =====================================================
-- 统一网关建表脚本（PostgreSQL 版）
-- 与 gateway/models.py 的 ORM 定义一一对应
-- 注意：MySQL 版保留在 create_gateway_tables.sql，供回滚/对照使用
-- =====================================================

-- 用户表
CREATE TABLE IF NOT EXISTS zd_user (
    id                   SERIAL PRIMARY KEY,
    username             VARCHAR(50)  NOT NULL,
    password_hash        VARCHAR(255) NOT NULL,
    display_name         VARCHAR(50),
    role                 VARCHAR(20)  NOT NULL DEFAULT 'user',
    must_change_password INTEGER      NOT NULL DEFAULT 0,
    is_active            INTEGER      NOT NULL DEFAULT 1,
    failed_attempts      INTEGER      NOT NULL DEFAULT 0,
    locked_until         TIMESTAMP    NULL,
    -- 微秒精度：首登改密往往与登录同秒，秒级精度会导致旧 token 漏判
    pwd_changed_at       TIMESTAMP    NOT NULL,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_zd_user_username UNIQUE (username)
);
COMMENT ON TABLE zd_user IS '网关用户表';

-- API Key 表
CREATE TABLE IF NOT EXISTS zd_api_key (
    id           SERIAL PRIMARY KEY,
    key_name     VARCHAR(50)  NOT NULL,
    key_hash     CHAR(64)     NOT NULL,
    ip_whitelist JSONB        NULL,
    is_active    INTEGER      NOT NULL DEFAULT 1,
    expires_at   TIMESTAMP    NULL,
    created_by   INTEGER      NOT NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_zd_api_key_hash UNIQUE (key_hash)
);
COMMENT ON TABLE zd_api_key IS '网关API密钥表';

-- 调用审计表
CREATE TABLE IF NOT EXISTS zd_call_audit (
    id          SERIAL PRIMARY KEY,
    caller_type VARCHAR(20)  NOT NULL DEFAULT 'anonymous',
    caller_id   VARCHAR(100) NULL,
    method      VARCHAR(10)  NOT NULL,
    path        VARCHAR(255) NOT NULL,
    ip          VARCHAR(64)  NULL,
    status      VARCHAR(20)  NOT NULL,
    status_code INTEGER      NOT NULL,
    duration_ms INTEGER      NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE zd_call_audit IS '网关调用审计表';

CREATE INDEX IF NOT EXISTS idx_zd_call_audit_created_at ON zd_call_audit (created_at);
CREATE INDEX IF NOT EXISTS idx_zd_call_audit_caller ON zd_call_audit (caller_type, caller_id);
CREATE INDEX IF NOT EXISTS idx_zd_call_audit_status ON zd_call_audit (status);

-- 模型用量表（按自然日合并累计）
CREATE TABLE IF NOT EXISTS zd_model_usage (
    id            SERIAL PRIMARY KEY,
    stat_date     DATE    NOT NULL,
    model_kind    VARCHAR(20) NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_zd_model_usage_date_kind UNIQUE (stat_date, model_kind)
);
COMMENT ON TABLE zd_model_usage IS '网关模型用量表';
