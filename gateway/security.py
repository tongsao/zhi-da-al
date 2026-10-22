# 安全原语：密码哈希、JWT 签发/校验、API Key 生成/摘要。
# 全部为纯函数/无状态，零 DB 依赖，模块级不做任何 I/O。
import base64
import datetime
import hashlib
import hmac
import re
import secrets

import jwt

from gateway import config

JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = config.JWT_EXPIRE_HOURS
PASSWORD_ITERATIONS = config.PASSWORD_ITERATIONS
LOGIN_LOCK_THRESHOLD = config.LOGIN_LOCK_THRESHOLD
LOGIN_LOCK_MINUTES = config.LOGIN_LOCK_MINUTES
SALT_BYTES = 16


# ---- 密码哈希：pbkdf2_sha256$iterations$salt_b64$hash_b64 ----
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, hash_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(digest, expected)
    except ValueError:
        # 格式串不匹配（历史脏数据/手工改库），一律按校验失败处理
        return False


# ---- 密码策略：长度 8-64，至少含大写/小写/数字/特殊字符四类中的 3 类 ----
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 64

def validate_password_strength(password: str) -> str | None:
    """不满足策略时返回原因字符串，合规返回 None。"""
    if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        return "密码长度需在 8-64 位之间"
    classes = [
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ]
    if sum(classes) < 3:
        return "密码需至少包含大写字母、小写字母、数字、特殊字符中的 3 类"
    return None


# ---- JWT ----
def create_token(user_id: int, role: str, username: str, must_change_password: bool, pwd_changed_at: datetime.datetime) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "username": username,
        "must_change_password": must_change_password,
        # 库里存 naive 本地时间，.timestamp() 按系统时区解释；微秒精度可分辨同秒内的改密
        "pwd_changed_at": int(pwd_changed_at.timestamp() * 1_000_000),
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    # 过期/签名错误统一抛 jwt.ExpiredSignatureError / jwt.InvalidTokenError，由调用方转 401
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ---- API Key ----
def generate_api_key() -> str:
    return "zd_" + secrets.token_urlsafe(32)


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()