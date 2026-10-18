
import uvicorn
from fastapi import FastAPI
from langfuse import Langfuse

from api import chatController, ragFileController
from model.initDataBase import Base, engine
from service.evalService import failStaleGenRuns

app = FastAPI(
    title="企业智达服务助手",
    version="1.0",
    description="企业智达服务助手 API"
)
app.include_router(ragFileController.router)
app.include_router(chatController.router)

# 自动建缺失的表（checkfirst 只建新表，不碰旧表）；DB 不可用时降级为告警，不阻断启动
try:
    Base.metadata.create_all(engine)
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

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)

    # 只能绕过 uvicorn.Server.run()：0.46 强制 asyncio.run(loop_factory=...)，
    # 而 PyCharm 调试器的补丁版 run() 不收 loop_factory 关键字，必报 TypeError；
    # 也不能设 WindowsSelectorEventLoopPolicy——PyCharm 调试器与它不兼容，会报
    # "Task object is not callable"。所以保持默认循环(Proactor)直接驱动 serve()。
    asyncio.run(server.serve())

