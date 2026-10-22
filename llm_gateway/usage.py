# 用量与限额（进程内计数 + 落库）。模块级零 DB 操作，一切发生在函数体内。
# 计数键：模型角色(kind) -> (input, output)。date 切换时把"昨天"累计异步写库。
import logging
import threading
from datetime import date

from gateway import config

logger = logging.getLogger("llm_gateway.usage")

# 进程级单例
_lock = threading.Lock()
_counts: dict[str, tuple[int, int]] = {}   # kind -> (input_tokens, output_tokens)
_current_date: date | None = None
_worker_pool = None

# 批量豁免（评测后台线程）：threading.local 置位后跳过逐次 precheck，仍逐次 record
_thread_ctx = threading.local()


class QuotaExceeded(Exception):
    """日用量超限，业务层应提示「模型服务暂不可用」。"""

    def __init__(self, limit: int, used: int):
        self.limit = limit
        self.used = used
        super().__init__(f"当日模型用量超限：已用 {used}，限额 {limit}")


def set_batch(flag: bool = True) -> None:
    """标记当前线程为批量豁免模式（评测任务线程入口调用，finally 中清除）。"""
    _thread_ctx.batch = flag


def in_batch_exempt() -> bool:
    return getattr(_thread_ctx, "batch", False)


# ---- 估算 ----
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)  # 中文场景 1 汉字≈1~2 token，保守按字符数/2 估算输入


def context_input_estimate() -> int:
    """拿不到入参时按固定上下文估算本次输入 tokens（用于 precheck 兜底）。"""
    return max(1, config.MODEL_CONTEXT_INPUT_CHARS // 2)


def precheck(kind: str, estimate: int = 0) -> None:
    """校验当日累计 + 本次估算 <= 限额；DAILY_TOKEN_LIMIT=0 表示不限。"""
    limit = config.DAILY_TOKEN_LIMIT
    if limit <= 0:
        return
    with _lock:
        _rollover_locked()
        used = sum(inp + out for inp, out in _counts.values())
        if used + estimate > limit:
            raise QuotaExceeded(limit, used)


def record(kind: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    """逐次累计用量；跨天自动把昨天累计写库（线程池异步）。"""
    if input_tokens <= 0 and output_tokens <= 0:
        return
    with _lock:
        _rollover_locked()
        _counts[kind] = (_counts.get(kind, (0, 0))[0] + input_tokens,
                         _counts.get(kind, (0, 0))[1] + output_tokens)


def snapshot() -> dict[str, dict[str, int]]:
    """返回当日各角色用量快照（统计页用）。"""
    with _lock:
        return {
            kind: {"input": inp, "output": out, "total": inp + out}
            for kind, (inp, out) in _counts.items()
        }


# ---- 内部 ----
def _rollover_locked():
    global _current_date
    today = date.today()
    if _current_date is not None and _current_date != today:
        _flush_locked(_current_date, dict(_counts))
        _counts.clear()
    _current_date = today


def _flush_locked(stat_date: date, counts: dict[str, tuple[int, int]]):
    if not counts:
        return
    payload = {
        "stat_date": stat_date,
        "rows": counts,
    }
    _submit_worker(_write_usage, payload)


def _write_usage(payload):
    """线程池 worker：按唯一索引 (stat_date, model_kind) upsert。"""
    from model.initDataBase import SessionLocal  # 延迟导入：模块级不建连
    from sqlalchemy import text

    rows = payload["rows"]
    try:
        with SessionLocal() as db:
            for kind, (inp, out) in rows.items():
                db.execute(
                    text(
                        "INSERT INTO zd_model_usage (stat_date, model_kind, input_tokens, output_tokens, total_tokens) "
                        "VALUES (:d, :k, :i, :o, :t) "
                        "ON DUPLICATE KEY UPDATE input_tokens = input_tokens + :i, "
                        "output_tokens = output_tokens + :o, total_tokens = total_tokens + :t"
                    ),
                    {"d": payload["stat_date"], "k": kind, "i": inp, "o": out, "t": inp + out},
                )
            db.commit()
    except Exception as e:  # noqa: BLE001 - 用量落库失败只记日志，不阻塞模型调用
        logger.error("用量落库失败 %s: %s", payload["stat_date"], e)


def _submit_worker(fn, payload):
    global _worker_pool
    if _worker_pool is None:
        import concurrent.futures

        _worker_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="gateway-usage")
    try:
        _worker_pool.submit(fn, payload)
    except RuntimeError:
        pass  # 解释器关闭期间线程池不可用，静默丢弃


# ---- 统计页查询（直接读库，不走内存快照） ----
def query_daily(kind: str | None = None, days: int = 30):
    from model.initDataBase import db_session  # 延迟导入
    from sqlalchemy import text

    cond = "WHERE (:kind IS NULL OR model_kind = :kind)"
    with db_session() as db:
        rows = db.execute(
            text(
                f"SELECT stat_date, model_kind, input_tokens, output_tokens, total_tokens "
                f"FROM zd_model_usage {cond} "
                f"AND stat_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY) ORDER BY stat_date DESC, model_kind"
            ),
            {"kind": kind, "days": days},
        ).all()
    return [dict(r._mapping) for r in rows]
