import os
import threading

import torch
from langchain_chroma import Chroma
from dotenv import load_dotenv

from agent.rag.initEmBedding import NormalizeDashScopeEmbeddings
from sentence_transformers import CrossEncoder
load_dotenv()


embeddings = NormalizeDashScopeEmbeddings(
    model="text-embedding-v1",  # Qwen 文本向量模型
    dashscope_api_key=os.getenv("QWEN_API_KEY", "")
)

chroma = Chroma(
    collection_name="zhida_embeddings",
    embedding_function=embeddings,
    persist_directory="data/vector_store",
)

def getVector():
    return chroma

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
                _reranker = CrossEncoder(r"D:\models\bge-reranker-v2-m3", device=device, max_length=512)
    return _reranker