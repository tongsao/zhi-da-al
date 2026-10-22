# 网关 API 请求/响应模型。响应统一 {code, message, data} 结构（沿用 schema.schemas.Response）。
import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---- 认证 ----

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserInfo(BaseModel):
    id: int
    username: str
    role: str
    display_name: Optional[str] = None
    must_change_password: bool = False

    model_config = ConfigDict(from_attributes=True)


# ---- 用户管理 ----

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: Optional[str] = None
    password: str = Field(min_length=6, max_length=128)
    role: str = "user"  # admin / user


class UserPatch(BaseModel):
    is_active: Optional[int] = None       # 1=启用 0=停用
    reset_password: Optional[str] = None  # 重置密码 → must_change_password=1


class UserListItem(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: str
    is_active: int
    must_change_password: int
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserListData(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[UserListItem]

    model_config = ConfigDict(from_attributes=True)


# ---- 密钥管理 ----

class ApiKeyCreate(BaseModel):
    key_name: str = Field(min_length=1, max_length=50)
    ip_whitelist: List[str] = []
    expires_at: Optional[datetime.datetime] = None


class ApiKeyPatch(BaseModel):
    is_active: Optional[int] = None
    expires_at: Optional[datetime.datetime] = None


class ApiKeyItem(BaseModel):
    id: int
    key_name: str
    ip_whitelist: Optional[list] = None
    is_active: int
    expires_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)