# 审计查询（admin）：按调用方/路径/状态/时间段筛选，分页返回。
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from gateway.deps import require_admin
from gateway.models import ZdCallAudit
from model.initDataBase import db_session
from schema.schemas import Response

router = APIRouter(prefix="/audit", tags=["审计"])


@router.get("")
def list_audit(
    caller_type: str = "",
    caller_id: str = "",
    path: str = "",
    status: str = "",
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    _: dict = Depends(require_admin),
) -> Response:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    cond = []
    if caller_type:
        cond.append(ZdCallAudit.caller_type == caller_type)
    if caller_id:
        cond.append(ZdCallAudit.caller_id == caller_id)
    if path:
        cond.append(ZdCallAudit.path.like(f"%{path}%"))
    if status:
        cond.append(ZdCallAudit.status == status)
    if start:
        cond.append(ZdCallAudit.created_at >= start)
    if end:
        cond.append(ZdCallAudit.created_at <= end)

    with db_session() as db:
        total = db.execute(select(func.count()).select_from(ZdCallAudit).where(*cond)).scalar()
        rows = (
            db.execute(
                select(ZdCallAudit).where(*cond)
                .order_by(ZdCallAudit.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
    items = [
        {
            "id": r.id,
            "caller_type": r.caller_type,
            "caller_id": r.caller_id,
            "method": r.method,
            "path": r.path,
            "ip": r.ip,
            "status": r.status,
            "status_code": r.status_code,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return Response(data={"total": total or 0, "page": page, "page_size": page_size, "items": items})