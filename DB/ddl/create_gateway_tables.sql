-- =====================================================
-- 统一网关建表脚本（独立于业务表，仅网关 4 张表）
-- 与 gateway/models.py 的 ORM 定义一一对应
-- 表名全小写（MySQL 无大小写歧义），与现有业务表风格一致
-- =====================================================

-- 用户表
CREATE TABLE IF NOT EXISTS zd_user (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    username           VARCHAR(50)  NOT NULL,
    password_hash      VARCHAR(255) NOT NULL,
    display_name       VARCHAR(50),
    role               VARCHAR(20)  NOT NULL DEFAULT 'user',
    must_change_password TINYINT     NOT NULL DEFAULT 0,
    is_active          TINYINT      NOT NULL DEFAULT 1,
    failed_attempts    INT          NOT NULL DEFAULT 0,
    locked_until       DATETIME     NULL,
    -- 微秒精度：首登改密往往与登录同秒，秒级 DATETIME 会导致旧 token 漏判
    pwd_changed_at     DATETIME(6)  NOT NULL,
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_zd_user_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='网关用户表';

-- API Key 表
CREATE TABLE IF NOT EXISTS zd_api_key (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    key_name       VARCHAR(50)  NOT NULL,
    key_hash       CHAR(64)     NOT NULL,
    ip_whitelist   JSON         NULL,
    is_active      TINYINT      NOT NULL DEFAULT 1,
    expires_at     DATETIME     NULL,
    created_by     INT          NOT NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_zd_api_key_hash (key_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='网关API密钥表';

-- 调用审计表
CREATE TABLE IF NOT EXISTS zd_call_audit (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    caller_type  VARCHAR(20)  NOT NULL DEFAULT 'anonymous',
    caller_id    VARCHAR(100) NULL,
    method       VARCHAR(10)  NOT NULL,
    path         VARCHAR(255) NOT NULL,
    ip           VARCHAR(64)  NULL,
    status       VARCHAR(20)  NOT NULL,
    status_code  INT          NOT NULL,
    duration_ms  INT          NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_zd_call_audit_created_at (created_at),
    KEY idx_zd_call_audit_caller (caller_type, caller_id),
    KEY idx_zd_call_audit_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='网关调用审计表';

-- 模型用量表（按自然日合并累计）
CREATE TABLE IF NOT EXISTS zd_model_usage (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    stat_date     DATE         NOT NULL,
    model_kind    VARCHAR(20)  NOT NULL,
    input_tokens  INT          NOT NULL DEFAULT 0,
    output_tokens INT          NOT NULL DEFAULT 0,
    total_tokens  INT          NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_zd_model_usage_date_kind (stat_date, model_kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='网关模型用量表';
