
import uvicorn
from fastapi import FastAPI
from langfuse import Langfuse

from api import aiCheckController, chatController, ragFileController
from gateway import config as gateway_config
from gateway import initGateway
from gateway.middleware import AuditMiddleware, AuthMiddleware, RateLimitMiddleware
from model.initDataBase import Base, engine
from service.aiCheckService import initRules
from service.evalService import failStaleGenRuns

app = FastAPI(
    title="企业智达服务助手",
    version="1.0",
    description="企业智达服务助手 API",
    # 网关收敛接口面：关闭 /docs /redoc /openapi.json（评审 P1-2）
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(ragFileController.router)
app.include_router(chatController.router)
app.include_router(aiCheckController.router)

# 网关横切中间件（洋葱模型：Audit 最外层 → Auth → RateLimit → app）
# Audit 放最外层才能兜住 Auth/RateLimit 短路的 401/403/429 拒绝响应
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(AuditMiddleware)

# JWT 签名密钥必须配齐，否则拒绝启动（禁止裸奔）
gateway_config.validate()

# 自动建缺失的表（checkfirst 只建新表，不碰旧表）；DB 不可用时降级为告警，不阻断启动
try:
    Base.metadata.create_all(engine)
    gateway_router = initGateway()  # 幂等：补建网关 4 表 + admin 账号，并返回网关管理路由
    app.include_router(gateway_router)
    # 预置 AI 质检校验规则（幂等，不覆盖已有配置）
    initRules()
    # 生成评估跑在后台线程里，进程重启会把它丢掉，残留的 running 记录需标失败，否则一直挡着新评测
    stale = failStaleGenRuns()
    if stale:
        print(f"[warn] 已把 {stale} 条中断的生成评估标记为失败")
except Exception as e:
    print(f"[warn] 数据库建表失败: {e}")

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

# 应用启动时初始化一次
langfuse = Langfuse()
@app.on_event("startup")
async def startup():
    # 可在此处做健康检查
    print("Langfuse initialized")

if __name__ == '__main__':
    import asyncio

    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)

    # 只能绕过 uvicorn.Server.run()：0.46 强制 asyncio.run(loop_factory=...)，
    # 而 PyCharm 调试器的补丁版 run() 不收 loop_factory 关键字，必报 TypeError；
    # 也不能设 WindowsSelectorEventLoopPolicy——PyCharm 调试器与它不兼容，会报
    # "Task object is not callable"。所以保持默认循环(Proactor)直接驱动 serve()。
    asyncio.run(server.serve())

