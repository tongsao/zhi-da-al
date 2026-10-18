import os
import sqlite3

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.rag.RagHandler import RiskGuard

load_dotenv()

API_KEY = os.getenv("GOAI_API_KEY")
BASE_URL = os.getenv("GOAI_BASE_URL")

# 全程挂 Langfuse 埋点：所有走 getModel() 的链路（问答/检索改写/评测）自动带 trace。
# 配置由 .env 的 LANGFUSE_* 提供，避免平时误埋只是数据全到本地，无副作用。
langfuse_handler = CallbackHandler()
model = init_chat_model(
    model="openai:glm-5.3",
    api_key=API_KEY,
    base_url=BASE_URL,
    temperature=0.5,
    timeout=180
).with_config({"callbacks": [langfuse_handler]})

# FastAPI 多线程共用一个连接，check_same_thread=False 必须
conn = sqlite3.connect("resource/checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()


# 通用模型:执行一般任务
def getModel():
    return model

# 简单模型执行简单任务
# EASY_API_KEY = os.getenv("ZHIPU_API_KEY")
# EASY_BASE_URL = os.getenv("ZHIPU_BASE_URL")
easyModel = init_chat_model(
    model="openai:glm-5.3-flash",
    api_key=API_KEY,
    base_url=BASE_URL,
    temperature=0.3,
    timeout=180
).with_config({"callbacks": [langfuse_handler]})
def getEasyMode():
    return easyModel


def getCheckpointer():
    return checkpointer

_riskguard = None  # 进程级单例：建索引要读全部文档，每次问答重建开销太大

def getRiskGuard():
    global _riskguard
    if _riskguard is None:
        _riskguard = RiskGuard('data/FILE/')
    return _riskguard