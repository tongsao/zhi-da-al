import os
import threading
from pathlib import Path

import torch
from dotenv import load_dotenv
from langchain_postgres import PGVector
from sentence_transformers import CrossEncoder
from sqlalchemy import text

from agent.rag.initEmBedding import NormalizeDashScopeEmbeddings
from model.initDataBase import engine
from model_versions import EMBEDDING_MODEL, RERANKER_MODEL

load_dotenv()

COLLECTION_NAME = "zhida_embeddings"
EMBEDDING_DIM = 1536  # text-embedding-v1 输出维度

embeddings = NormalizeDashScopeEmbeddings(
    model=EMBEDDING_MODEL,
    dashscope_api_key=os.getenv("QWEN_API_KEY", "")
)

# 向量库：PostgreSQL + pgvector，与业务表同库同连接池
vectorstore = PGVector(
    embeddings=embeddings,
    connection=engine,
    embedding_length=EMBEDDING_DIM,
    collection_name=COLLECTION_NAME,
    use_jsonb=True,
)

# PGVector 只建表不建向量索引（Chroma 会自动建 HNSW），这里补一个余弦索引保持检索性能
with engine.begin() as conn:
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_hnsw "
        "ON langchain_pg_embedding USING hnsw (embedding vector_cosine_ops)"
    ))

def getVector():
    return vectorstore


def deleteVectorsByFileId(fileid: str) -> int:
    """按文件 ID 删除向量。

    PGVector 原生 delete() 只支持按 id，不支持元数据过滤，
    这里先用 cmetadata 查出该文件的向量 id，再交给 delete()。
    """
    with engine.connect() as conn:
        ids = conn.execute(
            text(
                "SELECT e.id FROM langchain_pg_embedding e "
                "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                "WHERE c.name = :name AND e.cmetadata->>'fileid' = :fileid"
            ),
            {"name": COLLECTION_NAME, "fileid": fileid},
        ).scalars().all()

    if ids:
        vectorstore.delete(ids=list(ids))
    return len(ids)

_reranker = None  # [rerank] 进程级单例，CrossEncoder 加载开销大只建一次
_rerankerLock = threading.Lock()


def getBgeRerankerV2M3():
    # [rerank] CrossEncoder 加载开销大，进程内只建一次；无 CUDA 时自动退回 CPU。
    # 初始化必须加锁：评测批次启动瞬间多线程同时进这里会各自加载一份模型（2.2GB/份），
    # 把 8GB 显存塞满，之后每次 predict 都落在 WDDM 系统内存溢出模式，慢上百倍
    global _reranker
    if _reranker is None:
        with _rerankerLock:
            if _reranker is None:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                _reranker = CrossEncoder(
                    str(Path(r"D:\models") / RERANKER_MODEL), device=device, max_length=512
                )
    return _reranker