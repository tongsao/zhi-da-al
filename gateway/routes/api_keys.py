# 密钥管理（admin）：列表 / 创建（明文仅此一次）/ 启停与到期 / 轮换。
from fastapi import APIRouter, Depends
from sqlalchemy import select

from gateway import security
from gateway.deps import require_admin
from gateway.models import ZdApiKey
from gateway.schemas import ApiKeyCreate, ApiKeyItem, ApiKeyPatch
from model.initDataBase import db_session
from schema.schemas import Response

router = APIRouter(prefix="/api-keys", tags=["密钥管理"])


def _err(code: str, message: str) -> Response:
    return Response(code=code, message=message)


@router.get("")
def list_keys(_: dict = Depends(require_admin)) -> Response:
    with db_session() as db:
        rows = db.execute(select(ZdApiKey).order_by(ZdApiKey.id.desc())).scalars().all()
    items = [ApiKeyItem.model_validate(r).model_dump(mode="json") for r in rows]
    return Response(data={"items": items})


@router.post("")
def create_key(body: ApiKeyCreate, caller: dict = Depends(require_admin)) -> Response:
    if not body.ip_whitelist:
        return _err("4001", "IP 白名单不能为空")
    plain = security.generate_api_key()
    key = ZdApiKey(
        key_name=body.key_name,
        key_hash=security.hash_api_key(plain),
        ip_whitelist=body.ip_whitelist,
        is_active=1,
        expires_at=body.expires_at,
        created_by=caller["id"],
    )
    with db_session() as db:
        db.add(key)
        db.commit()
        db.refresh(key)
    # 明文仅此一次返回；之后只能看到 key_hash，不可再查明文
    return Response(
        data={
            "id": key.id,
            "key_name": key.key_name,
            "api_key": plain,
            "ip_whitelist": key.ip_whitelist,
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        }
    )


@router.patch("/{key_id}")
def patch_key(key_id: int, body: ApiKeyPatch, _: dict = Depends(require_admin)) -> Response:
    with db_session() as db:
        key = db.execute(select(ZdApiKey).where(ZdApiKey.id == key_id)).scalars().first()
        if key is None:
            return _err("4001", "密钥不存在")
        if body.is_active is not None:
            key.is_active = body.is_active
        if body.expires_at is not None:
            key.expires_at = body.expires_at
        db.commit()
    return Response(data={"id": key_id})


@router.post("/{key_id}/rotate")
def rotate_key(key_id: int, _: dict = Depends(require_admin)) -> Response:
    plain = security.generate_api_key()
    with db_session() as db:
        key = db.execute(select(ZdApiKey).where(ZdApiKey.id == key_id)).scalars().first()
        if key is None:
            return _err("4001", "密钥不存在")
        key.key_hash = security.hash_api_key(plain)
        db.commit()
    # 新明文仅此一次返回；旧明文立即失效
    return Response(data={"id": key_id, "api_key": plain})