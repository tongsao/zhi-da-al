# 用量查询（admin）：今日各类模型用量与限额剩余 / 近 90 日逐日趋势。
import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends

from gateway import config
from gateway.deps import require_admin
from llm_gateway import usage as model_usage
from schema.schemas import Response

router = APIRouter(prefix="/usage", tags=["用量"])


@router.get("/today")
def usage_today(_: dict = Depends(require_admin)) -> Response:
    snap = model_usage.snapshot()  # {kind: {input, output, total}}
    used = sum(v["total"] for v in snap.values())
    limit = config.DAILY_TOKEN_LIMIT
    data = {
        "date": datetime.date.today().isoformat(),
        "limit": limit,
        "used": used,
        "remaining": (limit - used) if limit > 0 else None,
        "items": snap,
    }
    return Response(data=data)


@router.get("/trend")
def usage_trend(days: int = 90, _: dict = Depends(require_admin)) -> Response:
    days = min(max(1, days), 90)
    rows = model_usage.query_daily(days=days)  # [{stat_date, model_kind, total_tokens, ...}]
    by_date: dict[str, int] = defaultdict(int)
    for r in rows:
        by_date[str(r["stat_date"])] += r["total_tokens"]
    items = [{"date": d, "total_tokens": v} for d, v in sorted(by_date.items(), reverse=True)]
    return Response(data={"days": days, "items": items})