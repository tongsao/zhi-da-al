# 网关配置集中读取（.env）。所有网关模块统一从这里取值，避免散落 os.getenv。
import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default=None, required: bool = False):
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"缺少必需配置项 {name}（禁止裸奔启动）")
    return value


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


JWT_SECRET = _get("JWT_SECRET", required=True)
JWT_EXPIRE_HOURS = _int("JWT_EXPIRE_HOURS", 12)
PASSWORD_ITERATIONS = _int("PASSWORD_ITERATIONS", 100000)
LOGIN_LOCK_THRESHOLD = _int("LOGIN_LOCK_THRESHOLD", 5)
LOGIN_LOCK_MINUTES = _int("LOGIN_LOCK_MINUTES", 30)
AUDIT_RETENTION_DAYS = _int("AUDIT_RETENTION_DAYS", 90)

# 模型网关
DAILY_TOKEN_LIMIT = _int("DAILY_TOKEN_LIMIT", 0)          # 0=不限额
GATEWAY_MODEL_FALLBACK = os.getenv("GATEWAY_MODEL_FALLBACK", "false").lower() in ("1", "true", "yes")
MODEL_CONTEXT_INPUT_CHARS = _int("MODEL_CONTEXT_INPUT_CHARS", 6000)  # 单次调用输入估算（字符）

# 模型（与 agent/initChatModel.py 取值一致）
GOAI_API_KEY = os.getenv("GOAI_API_KEY", "")
GOAI_BASE_URL = os.getenv("GOAI_BASE_URL", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")


def validate() -> None:
    """启动时强制校验必须配置项，防裸奔。"""
    _get("JWT_SECRET", required=True)
    if len(JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET 长度必须 >= 32 字符")