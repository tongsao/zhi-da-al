# FastAPI 依赖：从中间件解析好的 caller 中取身份。
# AuthMiddleware 已把 {type, id, role, ...} 写入 request.state.caller，路由层只做解读与权限二次加固。
from fastapi import HTTPException, Request

from gateway.schemas import UserInfo


def get_current_user(request: Request) -> dict:
    """当前登录用户身份（仅用户调用的接口使用，密钥调用方不适用）。"""
    caller = getattr(request.state, "caller", None)
    if not caller or caller.get("type") != "user":
        raise HTTPException(status_code=401, detail="未登录或凭证无效")
    return caller


def require_admin(request: Request) -> dict:
    """管理员身份（管理路由依赖；中间件已拦截一次，这里防御性兜底）。"""
    caller = get_current_user(request)
    if caller.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权限访问")
    return caller


def current_user_info(request: Request) -> UserInfo:
    """查库返回最新用户信息（me 接口用），与中间件核对后的快照一致。"""
    from sqlalchemy import select
    from gateway.models import ZdUser
    from model.initDataBase import db_session

    caller = get_current_user(request)
    with db_session() as db:
        row = db.execute(select(ZdUser).where(ZdUser.id == caller["id"])).scalars().first()
        if row is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        return UserInfo(
            id=row.id,
            username=row.username,
            role=row.role,
            display_name=row.display_name,
            must_change_password=bool(row.must_change_password),
        )