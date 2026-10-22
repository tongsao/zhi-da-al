# 网关横切中间件（纯 ASGI 实现）：Audit → Auth → RateLimit。
# Audit 在最外层，Auth/RateLimit 短路的 401/403/429 拒绝响应也能被审计捕获。
# 不用 BaseHTTPMiddleware：新版 Starlette 的 call_next 会聚合缓冲整个响应体，
# 会破坏 /api/v1/qa/chat 的 SSE 流式效果。这里逐事件转发，body 零缓冲。
import datetime
import json
import time

import jwt
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from gateway import audit, groups, ratelimit, security
from gateway.models import ZdApiKey, ZdUser
from model.initDataBase import db_session


async def _send_json(scope, receive, send, status: int, code: str, message: str):
    body = json.dumps({"code": code, "message": message, "data": None}, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


# ---- Auth：身份识别 + 准入判定 ----

def _resolve_key(plain: str, ip: str):
    """按 X-Api-Key 识别密钥调用方；is_active/expires_at/IP 白名单任一不满足 → 未授权。"""
    digest = security.hash_api_key(plain)
    with db_session() as db:
        row = db.execute(select(ZdApiKey).where(ZdApiKey.key_hash == digest)).scalars().first()
    if row is None or row.is_active != 1:
        return None
    if row.expires_at is not None and row.expires_at < datetime.datetime.now():
        return None
    whitelist = row.ip_whitelist or []
    if whitelist and ip not in whitelist:
        return None
    return {"type": "key", "id": row.id, "role": None, "name": row.key_name}


def _resolve_user(token: str):
    """按 JWT 识别用户并核对 DB 状态：停用/改密后旧 token 即时失效。"""
    try:
        payload = security.decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    try:
        uid = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    with db_session() as db:
        row = db.execute(select(ZdUser).where(ZdUser.id == uid)).scalars().first()
    if row is None or row.is_active != 1:
        return None
    # 改密后旧 token 作废：DB 当前密码变更时间晚于签发快照 → 拒绝（快照为整数微秒，见 security.create_token）
    snapshot = payload.get("pwd_changed_at")
    if snapshot is not None and int(row.pwd_changed_at.timestamp() * 1_000_000) > snapshot:
        return None
    return {
        "type": "user",
        "id": row.id,
        "role": row.role,
        "username": row.username,
        "must_change_password": row.must_change_password,
    }


async def _resolve_credential(request: Request):
    api_key = request.headers.get("x-api-key")
    if api_key:
        ip = request.client.host if request.client else ""
        return await run_in_threadpool(_resolve_key, api_key, ip)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return await run_in_threadpool(_resolve_user, auth[7:].strip())
    return None


def _check_access(access: str, caller) -> bool:
    if access == "exempt":
        return True
    if access == "key":
        return caller is not None and caller["type"] == "key"
    if access == "user":
        return caller is not None and caller["type"] == "user"
    if access == "admin":
        return caller is not None and caller["type"] == "user" and caller["role"] == "admin"
    return caller is not None  # user_or_key


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        path = request.url.path

        if groups.is_exempt(path):
            scope.setdefault("state", {})["caller"] = None
            return await self.app(scope, receive, send)

        caller = await _resolve_credential(request)

        access, _ = groups.match_rule(request.method, path)
        if not _check_access(access, caller):
            # 拒绝也要把 caller 落 scope，供外层 AuditMiddleware 记录真实调用方
            scope.setdefault("state", {})["caller"] = caller
            if caller is None:
                return await _send_json(scope, receive, send, 401, "4010", "未登录或凭证无效")
            return await _send_json(scope, receive, send, 403, "4030", "无权限访问")

        # 强制改密：凭证有效但功能受限，只放行改密与查自身（caller 为 None 时跳过——404 等无凭证路径）
        if caller and caller["type"] == "user" and caller["must_change_password"] and path not in groups.MUST_CHANGE_ALLOWED_PATHS:
            scope.setdefault("state", {})["caller"] = caller
            return await _send_json(scope, receive, send, 403, "4031", "请先修改初始密码")

        scope.setdefault("state", {})["caller"] = caller
        return await self.app(scope, receive, send)


# ---- RateLimit：按 IP/用户/密钥 维度消费令牌桶 ----

class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        access, limit_group = groups.match_rule(request.method, request.url.path)
        if access == "exempt":
            return await self.app(scope, receive, send)

        caller = scope.setdefault("state", {}).get("caller")
        ip = request.client.host if request.client else "unknown"
        dims = [("ip", ip)]
        if caller:
            dims.append((caller["type"], str(caller["id"])))

        store = ratelimit.get_bucket_store()
        for dim, dim_key in dims:
            if not store.consume(limit_group, dim, dim_key):
                return await _send_json(scope, receive, send, 429, "4290", "请求过于频繁，请稍后重试")
        return await self.app(scope, receive, send)


# ---- Audit：全程计时收尾，线程池落库不阻塞 ----

def _status_of(status_code: int, biz_code: str | None = None) -> str:
    # 业务层错误响应 HTTP 恒为 200，只有拿到 body 里的业务码才能还原真实状态；
    # 无业务码（中间件/框架短路）时回落到 HTTP 状态码映射
    if biz_code is not None:
        if biz_code in ("4010", "4230"):
            return "unauthorized"
        if biz_code in ("4030", "4031"):
            return "forbidden"
        if biz_code in ("4290", "4291"):
            return "rate_limited"
        return "success" if biz_code == "0" else "error"
    if 200 <= status_code < 300:
        return "success"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 429:
        return "rate_limited"
    return "error"


def _extract_biz_code(parts: list[bytes]) -> str | None:
    """从响应 body 里取业务码；非 JSON / 无 code 字段返回 None。"""
    body = b"".join(parts).decode("utf-8", "ignore")
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or "code" not in data:
        return None
    return str(data["code"])


class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        path = request.url.path
        if groups.is_audit_exempt(path):
            return await self.app(scope, receive, send)

        start = time.monotonic()
        status_code = 0
        recorded = False
        # 认证类路径（login/change-password）响应是小 JSON：等 body 收完解析业务码，
        # 才能区分「HTTP 200 + code 4010」这类业务层失败；其余路径（含 SSE）创建即落库
        must_audit = groups.is_must_audit(path)
        body_parts: list[bytes] = []
        biz_code: str | None = None

        def do_record():
            nonlocal recorded
            if recorded:
                return
            recorded = True
            caller = scope.setdefault("state", {}).get("caller")
            audit.log_audit(
                caller_type=(caller or {}).get("type", "anonymous"),
                caller_id=(caller or {}).get("id"),
                method=request.method,
                path=path,
                ip=request.client.host if request.client else None,
                status=_status_of(status_code, biz_code),
                status_code=status_code,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        async def wrapped_send(message):
            nonlocal status_code, biz_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                if not must_audit:
                    do_record()  # SSE 长流在响应创建时刻即落库，不阻塞流式转发
            elif message["type"] == "http.response.body":
                if must_audit:
                    body_parts.append(message["body"])
                    if not message.get("more_body", False):
                        biz_code = _extract_biz_code(body_parts)
                        do_record()
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception:
            status_code = 500
            do_record()
            raise
