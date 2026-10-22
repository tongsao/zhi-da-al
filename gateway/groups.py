# 网关路由分组规则：路径匹配 → 准入类型 / 限流分组 / 是否豁免 / 是否必审。
# 业务 controller 零改动，全靠这套前缀匹配表。

# 豁免路径（不校验凭证）
EXEMPT_PATHS = {
    "/",
    "/health",
    "/api/v1/health",
    "/api/v1/auth/login",
}

# 审计豁免路径（不落审计表）
AUDIT_EXEMPT_PATHS = {"/", "/health", "/api/v1/health"}

# 认证类路径（必审，登录失败也要记）
MUST_AUDIT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/change-password",
}

# 强制改密例外：must_change 状态下仍可访问的接口（只有改密与查自身）
MUST_CHANGE_ALLOWED_PATHS = {
    "/api/v1/auth/change-password",
    "/api/v1/auth/me",
}

# 规则表：每项 (method, path, 准入类型, 限流分组)。
# 准入类型: exempt=豁免 / user=仅用户 / key=仅密钥 / user_or_key=用户或密钥 / admin=仅管理员
# 限流分组名与 GROUP_RULES 对齐。method 大写；path 用前缀匹配（天然兼容路径参数）。
ROUTE_GROUPS: list[tuple[str, str, str, str]] = [
    ("GET", "/", "exempt", "health"),
    ("GET", "/api/v1/health", "exempt", "health"),
    ("POST", "/api/v1/auth/login", "exempt", "auth_login"),
    ("POST", "/api/v1/auth/change-password", "user", "auth_ops"),
    ("GET", "/api/v1/auth/me", "user", "auth_ops"),
    # 信披推送：仅密钥
    ("POST", "/api/v1/ai-check/projects", "key", "key_only"),
    ("POST", "/api/v1/ai-check/files", "key", "key_only"),
    # 问答（含流式与历史）
    ("POST", "/api/v1/qa/chat", "user_or_key", "qa"),
    ("POST", "/api/v1/qa/feedback", "user_or_key", "qa"),
    ("GET", "/api/v1/qa/chat/conversation_id", "user_or_key", "qa"),
    ("GET", "/api/v1/qa/chat/gethistory", "user_or_key", "qa"),
    ("DELETE", "/api/v1/qa/chat/conversation_id", "user_or_key", "qa"),
    ("POST", "/api/v1/qa/chat/stop", "user_or_key", "qa"),
    ("GET", "/api/v1/qa/feedback/stats", "user_or_key", "qa"),
    ("GET", "/api/v1/qa/feedback/list", "user_or_key", "qa"),
    # 文件上传
    ("POST", "/api/v1/documents", "user_or_key", "upload"),
    # 评测触发（仅 admin）
    ("POST", "/api/v1/eval/run", "admin", "eval_trigger"),
    ("POST", "/api/v1/eval/gen/run", "admin", "eval_trigger"),
    ("POST", "/api/v1/eval/gen/runs", "admin", "eval_trigger"),
    # 删除文档（仅 admin）
    ("DELETE", "/api/v1/documents", "admin", "doc_delete"),
    # 规则开关（仅 admin）
    ("PUT", "/api/v1/ai-check/rules", "admin", "rule_toggle"),
    # 网关管理路由（仅 admin）
    ("GET", "/api/v1/users", "admin", "admin_mgmt"),
    ("POST", "/api/v1/users", "admin", "admin_mgmt"),
    ("PATCH", "/api/v1/users", "admin", "admin_mgmt"),
    ("GET", "/api/v1/users/", "admin", "admin_mgmt"),
    ("GET", "/api/v1/api-keys", "admin", "admin_mgmt"),
    ("POST", "/api/v1/api-keys", "admin", "admin_mgmt"),
    ("PATCH", "/api/v1/api-keys", "admin", "admin_mgmt"),
    ("POST", "/api/v1/api-keys/", "admin", "admin_mgmt"),
    ("GET", "/api/v1/audit", "admin", "admin_mgmt"),
    ("GET", "/api/v1/usage", "admin", "admin_mgmt"),
    # 兜底：其余 /api/v1/* → 用户或密钥；非 /api/v1 路径（根/静态）→ 豁免
]

# 兜底组：所有 /api/v1/* 未匹配时
FALLBACK_ACCESS = "user_or_key"
FALLBACK_GROUP = "default"


def match_rule(method: str, path: str) -> tuple[str, str]:
    """返回 (准入类型, 限流分组)。

    规则从上到下取首个命中；方法严格匹配，路径前缀匹配（支持 /users/12 这类带参）。
    """
    method = (method or "GET").upper()
    for rule_method, rule_path, access, limit_group in ROUTE_GROUPS:
        if method != rule_method:
            continue
        if path == rule_path or path.startswith(rule_path + "/"):
            return access, limit_group

    # 兜底：/api/v1 前缀 → 用户或密钥入口；其余（根/静态）→ 豁免
    if path.startswith("/api/v1") or path == "/":
        return FALLBACK_ACCESS, FALLBACK_GROUP
    return "exempt", "health"


def is_exempt(path: str) -> bool:
    return path in EXEMPT_PATHS


def is_audit_exempt(path: str) -> bool:
    return path in AUDIT_EXEMPT_PATHS


def is_must_audit(path: str) -> bool:
    return path in MUST_AUDIT_PATHS