# 网关 4 张表的 ORM 定义。
# 只在此处定义模型类，绝不 import 后执行 DB 操作（模块级无 DB 访问），
# 否则 main.py 的 `from gateway import initGateway` 顶层 import 会连带建连失败。
import datetime

from sqlalchemy import JSON, Column, Date, DateTime, Integer, String
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

from model.initDataBase import Base


class ZdUser(Base):
    __tablename__ = "zd_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, comment="登录名")
    password_hash = Column(String(255), nullable=False, comment="pbkdf2 格式串")
    display_name = Column(String(50), comment="显示名")
    role = Column(String(20), default="user", comment="admin/user")
    must_change_password = Column(Integer, default=0, comment="1=强制改密")
    is_active = Column(Integer, default=1, comment="停用即时失效")
    failed_attempts = Column(Integer, default=0, comment="连续输错计数")
    locked_until = Column(DateTime, nullable=True, comment="锁定截止时间")
    # 微秒精度：改密常发生在登录后同一秒内，秒级 DATETIME 会截断导致旧 token 漏判
    pwd_changed_at = Column(MySQLDateTime(fsp=6), nullable=False, comment="密码变更时间")
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class ZdApiKey(Base):
    __tablename__ = "zd_api_key"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_name = Column(String(50), nullable=False, comment="密钥名称")
    key_hash = Column(String(64), unique=True, nullable=False, comment="sha256(明文) hex")
    ip_whitelist = Column(JSON, nullable=True, comment="IP 数组")
    is_active = Column(Integer, default=1)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=False, comment="创建人 user id")
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


class ZdCallAudit(Base):
    __tablename__ = "zd_call_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    caller_type = Column(String(20), default="anonymous", comment="user/key/anonymous")
    caller_id = Column(String(100), nullable=True)
    method = Column(String(10), nullable=False)
    path = Column(String(255), nullable=False)
    ip = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, comment="success/unauthorized/forbidden/rate_limited/error")
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now, index=True)


class ZdModelUsage(Base):
    __tablename__ = "zd_model_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="自然日")
    model_kind = Column(String(20), nullable=False, comment="chat/rewrite/embedding")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)