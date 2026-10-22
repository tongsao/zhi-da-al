-- =============================================
-- 季报 AI 质检模块 建表脚本
-- 表前缀统一为 zd_（zd_project_info / zd_ai_check_result / zd_ai_check_rule）
-- 与 model/models.py 中 ORM 模型保持一致
-- 已存在同表结构时执行会报错，属正常现象（可用 CREATE TABLE IF NOT EXISTS 避免）
-- =============================================

-- 项目信息表：存储上游信披中心推送的结构化数据，作为校验的比对基准
CREATE TABLE IF NOT EXISTS zd_project_info (
    id            INT           NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    project_id    VARCHAR(100)  NOT NULL COMMENT '项目ID（上游唯一标识）',
    project_name  VARCHAR(255)  NULL COMMENT '项目名称',
    year          INT           NULL COMMENT '年份',
    month         INT           NULL COMMENT '月份',
    quarter_type  INT           NULL COMMENT '季度类型: 1/2/3/4',
    amount        DECIMAL(20,2) NULL COMMENT '金额（单位:元），DECIMAL 保证金融对账精度',
    discloser     VARCHAR(255)  NULL COMMENT '披露人',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_id (project_id),
    KEY idx_project_id (project_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '季报项目信息表';

-- 质检结果状态表：存储推送的披露文件信息与每次校验的状态/明细，默认状态为未质检(pending)
CREATE TABLE IF NOT EXISTS zd_ai_check_result (
    id           INT           NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    project_id   VARCHAR(100)  NOT NULL COMMENT '项目ID，关联 zd_project_info',
    file_name    VARCHAR(255)  NOT NULL COMMENT '文件名',
    file_path    VARCHAR(255)  NULL COMMENT '文件路径',
    file_type    VARCHAR(50)   NULL COMMENT '文件类型',
    status       VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '校验状态: pending=未质检/in_progress=质检中/success=一致/failed=不一致/error=质检异常',
    check_detail JSON          NULL COMMENT '校验明细: 各字段抽取值/业务值/比对结果/原因',
    recheck_from INT           NULL COMMENT '复检来源记录id，普通记录为NULL',
    error_msg    TEXT          NULL COMMENT '异常原因',
    create_date  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_date  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_project_id (project_id),
    KEY idx_file_name (file_name),
    KEY idx_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'AI质检结果状态表';

-- AI质检规则表：开发预置的校验规则（字段+比对方式+是否启用），业务在页面开关
CREATE TABLE IF NOT EXISTS zd_ai_check_rule (
    id           INT           NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    field_name   VARCHAR(50)   NOT NULL COMMENT '字段名: disclosure_date/amount/discloser/title',
    field_label  VARCHAR(50)   NOT NULL COMMENT '字段中文名',
    compare_type VARCHAR(20)   NOT NULL COMMENT '比对方式: quarter_match/amount_diff/name_normalized/string_exact',
    tolerance    DECIMAL(20,2) NULL COMMENT '容差(仅金额比对用), 默认0.01',
    enabled      INT           NOT NULL DEFAULT 1 COMMENT '是否启用: 1=启用/0=停用',
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_field_name (field_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'AI质检规则表';

-- 预置 4 条默认规则（与 service/aiCheckService.py 中 DEFAULT_RULES 一致）
INSERT INTO zd_ai_check_rule (field_name, field_label, compare_type, tolerance, enabled) VALUES
    ('disclosure_date', '披露日期', 'quarter_match', NULL, 1),
    ('amount', '金额', 'amount_diff', 0.01, 1),
    ('discloser', '披露人', 'name_normalized', NULL, 1),
    ('title', '公告标题', 'string_exact', NULL, 1)
ON DUPLICATE KEY UPDATE field_name = field_name;

-- =============================================
-- 已建库升级变更（执行 CREATE 后追加，幂等）
-- =============================================
-- 金额改 DECIMAL 保证精度
ALTER TABLE zd_project_info MODIFY amount DECIMAL(20,2) NULL COMMENT '金额（单位:元），DECIMAL 保证金融对账精度';

-- 质检结果表新增复检来源、error_msg 改 TEXT
ALTER TABLE zd_ai_check_result ADD COLUMN recheck_from INT NULL COMMENT '复检来源记录id，普通记录为NULL' AFTER check_detail;
ALTER TABLE zd_ai_check_result MODIFY error_msg TEXT NULL COMMENT '异常原因';

-- 规则表新增容差列
ALTER TABLE zd_ai_check_rule ADD COLUMN tolerance DECIMAL(20,2) NULL COMMENT '容差(仅金额比对用), 默认0.01' AFTER compare_type;
-- 既有 amount 规则补齐默认容差
UPDATE zd_ai_check_rule SET tolerance = 0.01 WHERE field_name = 'amount' AND tolerance IS NULL;
