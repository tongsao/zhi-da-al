# 内存令牌桶限流器。单进程可用；跨进程/分布式需换 Redis 实现（BucketStore 接口化）。
# 模块级零 DB 依赖；配额从 .env 读取，未配置时用初始默认值。
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# 分组 → 窗口秒数 + 各维度每分钟配额
# 0 配额表示「不限」。同一接口多个维度分别建桶，任一维度超限即拒。
GROUP_RULES: dict[str, tuple[int, dict[str, int]]] = {
    "health": (60, {}),                          # 不限
    "auth_login": (60, {}),                      # 不限
    "auth_ops": (60, {"user": 60, "key": 60}),
    "key_only": (60, {"user": 60, "key": 60}),
    "qa": (
        60,
        {
            "ip": _int_env("RL_QA_IP_PER_MIN", 10),
            "user": _int_env("RL_QA_USER_PER_MIN", 30),
            "key": _int_env("RL_QA_KEY_PER_MIN", 30),
        },
    ),
    "upload": (60, {"user": _int_env("RL_UPLOAD_PER_MIN", 5), "key": _int_env("RL_UPLOAD_PER_MIN", 5)}),
    "eval_trigger": (60, {"user": _int_env("RL_EVAL_TRIGGER_PER_MIN", 1), "key": _int_env("RL_EVAL_TRIGGER_PER_MIN", 1)}),
    "doc_delete": (60, {"user": 60, "key": 60}),
    "rule_toggle": (60, {"user": 60, "key": 60}),
    "admin_mgmt": (60, {"user": 60, "key": 60}),
    "default": (60, {"user": _int_env("RL_DEFAULT_PER_MIN", 60), "key": _int_env("RL_DEFAULT_PER_MIN", 60)}),
}

# key 结构: (group, dimension, dimension_key) -> Bucket
# dimension: "ip" / "user" / "key"


class Bucket:
    __slots__ = ("capacity", "refill_rate", "tokens", "last_refill", "last_access")

    def __init__(self, window: float, rate: float):
        self.capacity = float(rate)
        self.refill_rate = rate / window if window > 0 else 0.0
        self.tokens = float(rate)
        self.last_refill = time.monotonic()
        self.last_access = time.monotonic()


class BucketStore:
    def __init__(self):
        self._buckets: dict[tuple, Bucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: Bucket, window: float):
        now = time.monotonic()
        if bucket.refill_rate > 0:
            elapsed = now - bucket.last_refill
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate)
            bucket.last_refill = now

    def consume(self, group: str, dimension: str, dimension_key: str, amount: int = 1) -> bool:
        window, dim_quotas = GROUP_RULES.get(group, GROUP_RULES["default"])
        rate = dim_quotas.get(dimension, 0)
        if rate <= 0 or window <= 0:
            return True  # 该维度不限 → 直接放行，不建桶

        key = (group, dimension, dimension_key)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = Bucket(window, rate)
                self._buckets[key] = bucket
            else:
                self._refill(bucket, window)
                bucket.last_access = now

            if bucket.tokens >= amount:
                bucket.tokens -= amount
                return True
            return False

    def prune(self):
        """清理空置桶。保留时长 = 所在分组配额窗口 × 2（分组周期可能随配额调整，按组自取）。"""
        with self._lock:
            now = time.monotonic()
            dead_keys = [
                k for k, b in self._buckets.items()
                if now - b.last_access > self._idle_seconds(k[0])
            ]
            for k in dead_keys:
                self._buckets.pop(k, None)

    @staticmethod
    def _idle_seconds(group: str) -> float:
        window, _ = GROUP_RULES.get(group, GROUP_RULES["default"])
        return window * 2 if window > 0 else 3600

    def reset(self):
        with self._lock:
            self._buckets.clear()


_bucket_store = BucketStore()


def get_bucket_store() -> BucketStore:
    return _bucket_store