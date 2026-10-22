# 认证路由：登录（含锁定计数）/ 改密 / 当前用户。
# login 是豁免路径但触发必审（MUST_AUDIT_PATHS），中间件负责落审计，这里只管业务。
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select

from gateway import security
from gateway.deps import current_user_info, get_current_user
from gateway.models import ZdUser
from gateway.schemas import ChangePasswordRequest, LoginRequest, UserInfo
from model.initDataBase import db_session
from schema.schemas import Response

router = APIRouter(prefix="/auth", tags=["认证"])


def _ok(data) -> Response:
    return Response(data=data)


def _err(code: str, message: str) -> Response:
    return Response(code=code, message=message)


@router.post("/login")
def login(body: LoginRequest) -> Response:
    with db_session() as db:
        user = db.execute(select(ZdUser).where(ZdUser.username == body.username)).scalars().first()
        if user is None or user.is_active != 1:
            # 不区分账号不存在与密码错误，避免账号探测
            return _err("4010", "用户名或密码错误")

        now = datetime.datetime.now()
        if user.locked_until is not None and user.locked_until > now:
            return _err("4230", "密码错误次数过多，账号已锁定，请稍后再试")

        if not security.verify_password(body.password, user.password_hash):
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= security.LOGIN_LOCK_THRESHOLD:
                user.locked_until = now + datetime.timedelta(minutes=security.LOGIN_LOCK_MINUTES)
                db.commit()
                return _err("4230", "密码错误次数过多，账号已锁定，请稍后再试")
            db.commit()
            return _err("4010", "用户名或密码错误")

        user.failed_attempts = 0
        user.locked_until = None
        db.commit()
        token = security.create_token(
            user.id, user.role, user.username, bool(user.must_change_password), user.pwd_changed_at
        )
    return _ok(
        {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "display_name": user.display_name,
                "must_change_password": bool(user.must_change_password),
            },
        }
    )


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, caller: dict = Depends(get_current_user)) -> Response:
    if body.new_password == body.old_password:
        return _err("4001", "新密码不能与原密码相同")
    reason = security.validate_password_strength(body.new_password)
    if reason:
        return _err("4002", reason)
    with db_session() as db:
        user = db.execute(select(ZdUser).where(ZdUser.id == caller["id"])).scalars().first()
        if user is None:
            return _err("4010", "用户不存在")
        if not security.verify_password(body.old_password, user.password_hash):
            return _err("4010", "原密码错误")
        user.password_hash = security.hash_password(body.new_password)
        user.must_change_password = 0
        user.pwd_changed_at = datetime.datetime.now()
        user.failed_attempts = 0
        user.locked_until = None
        db.commit()
    # 改密即失效旧 token（pwd_changed_at 快照比对），前端需用新密码重新登录
    return Response(data={"message": "密码已修改，请重新登录"})


@router.get("/me")
def me(info: UserInfo = Depends(current_user_info)) -> Response:
    return Response(data={"user": info.model_dump(mode="json")})