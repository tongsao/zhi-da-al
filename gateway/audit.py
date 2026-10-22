# 审计落库：线程池提交，不阻塞事件循环；写失败仅记日志，不阻塞业务。
import logging
from datetime import datetime

from model.initDataBase import SessionLocal, db_session
from sqlalchemy import text

from gateway.models import ZdCallAudit

logger = logging.getLogger("gateway.audit")

# 审计写失败的静默保护：DB 抖动时避免疯狂刷错误日志
_audit_pool = None


def audit_write(row: ZdCallAudit):
    """在后台线程池中落库。失败仅记日志，业务照常。"""
    try:
        with SessionLocal() as db:
            db.add(row)
            db.commit()
    except Exception as e:  # noqa: BLE001 - 审计失败不影响业务，只记日志
        logger.error("审计落库失败: %s", e)


def log_audit(
    caller_type: str,
    caller_id: str | None,
    method: str,
    path: str,
    ip: str | None,
    status: str,
    status_code: int,
    duration_ms: int | None,
):
    """组装并提交一条审计记录（异步线程池，不阻塞请求流程）。"""
    row = ZdCallAudit(
        caller_type=caller_type,
        caller_id=str(caller_id) if caller_id is not None else None,
        method=method,
        path=path,
        ip=ip,
        status=status,
        status_code=status_code,
        duration_ms=duration_ms,
        created_at=datetime.now(),
    )
    _submit(row)


def _submit(row: ZdCallAudit):
    _ensure_pool()
    try:
        _audit_pool.submit(audit_write, row)
    except RuntimeError:
        # 解释器关闭期间线程池不可用，静默丢弃
        pass


def _ensure_pool():
    global _audit_pool
    if _audit_pool is None:
        import concurrent.futures

        _audit_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="gateway-audit")


# ==== 定时清理：审计/用量保留 AUDIT_RETENTION_DAYS 天 ====
def cleanup_expired(retention_days: int = 90):
    """清理过期审计与用量行（启动时 + 每日凌晨执行，幂等）。"""
    try:
        with db_session() as db:
            n = db.execute(
                text("DELETE FROM zd_call_audit WHERE created_at < NOW() - INTERVAL :days DAY"),
                {"days": retention_days},
            ).rowcount
            db.commit()
            logger.info("清理过期审计 %s 条", n)
    except Exception as e:  # noqa: BLE001
        logger.error("清理过期审计失败: %s", e)