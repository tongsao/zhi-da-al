# 用户管理（admin）：分页列表 / 创建 / 启停与重置密码 / 详情。
# 保护规则：禁止停用最后一个启用 admin（§8.2 / §5.3.4）。
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from gateway import security
from gateway.deps import require_admin
from gateway.models import ZdUser
from gateway.schemas import UserCreate, UserListItem, UserListData, UserPatch
from model.initDataBase import db_session
from schema.schemas import Response

router = APIRouter(prefix="/users", tags=["用户管理"])


def _err(code: str, message: str) -> Response:
    return Response(code=code, message=message)


@router.get("")
def list_users(page: int = 1, page_size: int = 10, username: str = "", _: dict = Depends(require_admin)) -> Response:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    with db_session() as db:
        cond = [ZdUser.username.like(f"%{username}%")] if username else []
        total = db.execute(select(func.count()).select_from(ZdUser).where(*cond)).scalar()
        rows = (
            db.execute(
                select(ZdUser).where(*cond)
                .order_by(ZdUser.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
    data = UserListData(
        total=total or 0,
        page=page,
        page_size=page_size,
        items=[UserListItem.model_validate(u) for u in rows],
    )
    return Response(data=data.model_dump(mode="json"))


@router.post("")
def create_user(body: UserCreate, _: dict = Depends(require_admin)) -> Response:
    if body.role not in ("admin", "user"):
        return _err("4001", "角色只能是 admin 或 user")
    reason = security.validate_password_strength(body.password)
    if reason:
        return _err("4002", reason)
    with db_session() as db:
        exists = db.execute(select(ZdUser).where(ZdUser.username == body.username)).scalars().first()
        if exists:
            return _err("4001", "用户名已存在")
        user = ZdUser(
            username=body.username,
            password_hash=security.hash_password(body.password),
            display_name=body.display_name or body.username,
            role=body.role,
            must_change_password=1,  # 新账号强制改密
            is_active=1,
            pwd_changed_at=datetime.datetime.now(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return Response(data={"id": user.id, "username": user.username})


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, _: dict = Depends(require_admin)) -> Response:
    with db_session() as db:
        user = db.execute(select(ZdUser).where(ZdUser.id == user_id)).scalars().first()
        if user is None:
            return _err("4001", "用户不存在")
        # 禁止停用最后一个启用 admin：停用前数一次剩余启用 admin
        if body.is_active == 0 and user.is_active == 1 and user.role == "admin":
            active_admins = db.execute(
                select(func.count()).select_from(ZdUser).where(ZdUser.role == "admin", ZdUser.is_active == 1)
            ).scalar()
            if active_admins <= 1:
                return _err("4001", "不能停用最后一个启用的管理员")
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.reset_password:
            reason = security.validate_password_strength(body.reset_password)
            if reason:
                return _err("4002", reason)
            user.password_hash = security.hash_password(body.reset_password)
            user.must_change_password = 1
            user.pwd_changed_at = datetime.datetime.now()
            user.failed_attempts = 0
            user.locked_until = None
        db.commit()
    return Response(data={"id": user_id})


@router.get("/{user_id}")
def get_user(user_id: int, _: dict = Depends(require_admin)) -> Response:
    with db_session() as db:
        user = db.execute(select(ZdUser).where(ZdUser.id == user_id)).scalars().first()
    if user is None:
        return Response(code="4001", message="用户不存在")
    return Response(data=UserListItem.model_validate(user).model_dump(mode="json"))