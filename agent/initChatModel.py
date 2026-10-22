import sqlite3

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.rag.RagHandler import RiskGuard
from llm_gateway import providers

load_dotenv()

# FastAPI 多线程共用一个连接，check_same_thread=False 必须
conn = sqlite3.connect("resource/checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()


# 通用模型:执行一般任务（经 llm_gateway 计数代理包装，含限额/用量）
def getModel():
    return providers.get_chat()

# 简单模型执行简单任务（经 llm_gateway 计数代理包装）
def getEasyMode():
    return providers.get_rewrite()


def getCheckpointer():
    return checkpointer

_riskguard = None  # 进程级单例：建索引要读全部文档，每次问答重建开销太大

def getRiskGuard():
    global _riskguard
    if _riskguard is None:
        _riskguard = RiskGuard('data/FILE/')
    return _riskguard