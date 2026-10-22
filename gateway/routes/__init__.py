# 网关路由汇总：统一挂载 gateway_router（前缀 /api/v1）。
# 子路由各自 import 不碰 DB；DB 操作全部收敛在接口函数体内。
from fastapi import APIRouter

from gateway.routes import api_keys, audit, auth, usage, users

gateway_router = APIRouter(prefix="/api/v1")
gateway_router.include_router(auth.router)
gateway_router.include_router(users.router)
gateway_router.include_router(api_keys.router)
gateway_router.include_router(audit.router)
gateway_router.include_router(usage.router)