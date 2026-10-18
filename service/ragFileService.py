import hashlib
import json
import os
import pickle
import threading
from datetime import datetime
from pathlib import Path

import jieba
from dotenv import load_dotenv
from fastapi import UploadFile
from fastapi.responses import FileResponse
from langchain_community.document_loaders import JSONLoader, PyPDFLoader, TextLoader
from langchain_community.retrievers import BM25Retriever
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, select, update

from agent.initChatModel import getModel
from agent.rag.initRag import getBgeRerankerV2M3, getVector  # [rerank]
from model.initDataBase import db_session
from model.models import zd_file_info
from schema.schemas import FileInfo

load_dotenv()

UPLOAD_FILE_PATH = os.getenv("UPLOAD_FILE_PATH")
FILE_CHUNK_SIZE = int(os.getenv("FILE_CHUNK_SIZE"))
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE"))
ALLOWED_FILE_EXTENSIONS = json.loads(os.getenv("ALLOWED_FILE_EXTENSIONS"))

uploadDir = Path(UPLOAD_FILE_PATH)

# ---------- BM25 关键词检索索引 ----------
BM25_DOC_PATH = Path("data/bm25_docs.pkl")
BM25_K = 5

bm25_retriever_instance = None


def tokenize(text):
    return list(jieba.cut(text))


def loadBm25Docs():
    if BM25_DOC_PATH.exists():
        with open(BM25_DOC_PATH, "rb") as f:
            return pickle.load(f)
    return []


def saveBm25Docs(docs):
    # docs 为空时 rank_bm25 建索引会除零，只落盘不建索引
    global bm25_retriever_instance
    BM25_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_DOC_PATH, "wb") as f:
        pickle.dump(docs, f)
    bm25_retriever_instance = (
        BM25Retriever.from_documents(docs, k=BM25_K, preprocess_func=tokenize) if docs else None
    )


def getBm25Retriever():
    """返回缓存的 BM25 检索器；语料为空或索引未建时返回 None，调用方需降级为纯向量检索"""
    global bm25_retriever_instance
    if bm25_retriever_instance is None:
        docs = loadBm25Docs()
        if docs:
            bm25_retriever_instance = BM25Retriever.from_documents(docs, k=BM25_K, preprocess_func=tokenize)
    return bm25_retriever_instance


# ---------- [rerank] 混合检索 + 重排序（chatService 与 recall 评测共用）----------
# [rerank] 双路各自召回的候选块数 / 粗排融合后保留的条数
COARSE_K = 25
COARSE_KEEP = 30
# 重排相关性下限：bge CrossEncoder 输出经 sigmoid 落在 0~1，低于阈值视为 BM25 拉进来的
# 相邻业务干扰块（实测：经纪业务题混入授权条款导致编造）；全部低于阈值时退回原 top_k 保证上下文非空
# 0.3 会误杀"条文列举型"目标块：第25题的第九十三条禁止行为清单重排只有 0.242，被过滤后
# 上下文只剩经纪业务定义/营业部条款，模型直接输出空答案；45 题扫描后下调到 0.2
RERANK_MIN_SCORE = 0.2

# bge 重排是 CPU/GPU 混合敏感点：多线程同时进 torch forward 会互相踩踏（8 路并发实测整批假死），
# 锁住串行化；默认 batch_size=32 会把 8GB 显存顶满触发 WDDM 系统内存溢出（单次 predict 拖到分钟级），
# 显式 batch_size=8 把激活峰值压到 1/4，结果数值不变
_RERANK_BATCH_SIZE = 8
_rerankLock = threading.Lock()


def rerankChunks(question: str, candidates: list, top_k: int) -> list:
    """[rerank] bge CrossEncoder 给 (query, doc) 打相关性分，降序取前 top_k。"""
    if not candidates:
        return []
    reranker = getBgeRerankerV2M3()
    with _rerankLock:
        scores = reranker.predict([(question, doc.page_content) for doc in candidates], batch_size=_RERANK_BATCH_SIZE)
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)

    # 过滤低于阈值的干扰块；若整批都低于阈值（相关度普遍低），退回原 top_k，保证上下文非空
    kept = [(doc, s) for doc, s in ranked if s >= RERANK_MIN_SCORE][:top_k] or ranked[:top_k]
    return [doc for doc, _ in kept]


def hybridRetrieve(question: str, top_k: int) -> list:
    #查询改写，向量库检索改写问题，bm25检索原问题，重排序使用原问题比对
    rewritten = llm_rewrite(question)

    # 2. 分别检索
    vector_retriever = getVector().as_retriever(search_kwargs={"k": COARSE_K})
    bm25_retriever = getBm25Retriever()

    vec_docs = vector_retriever.invoke(rewritten)  # 向量用改写后
    bm25_docs = bm25_retriever.invoke(question) if bm25_retriever else []  # BM25 用原问题

    # 3. RRF 融合（只看排名，不看分数）
    from collections import defaultdict
    K = 60  # RRF 常数，常用 60
    scores = defaultdict(float)

    for rank, doc in enumerate(vec_docs):
        doc_id = doc.metadata.get("id", doc.page_content)  # 需要唯一标识
        scores[doc_id] += 1.0 / (K + rank + 1)

    for rank, doc in enumerate(bm25_docs):
        doc_id = doc.metadata.get("id", doc.page_content)
        scores[doc_id] += 1.0 / (K + rank + 1)

    # 按 RRF 分数降序，取前 COARSE_KEEP 个
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:COARSE_KEEP]

    # 建立 doc_id → Document 映射
    doc_map = {}
    for doc in vec_docs + bm25_docs:
        doc_id = doc.metadata.get("id", doc.page_content)
        doc_map[doc_id] = doc
    fused = [doc_map[did] for did in sorted_ids]

    # [rerank] 两路召回的是同一批分块的副本，按正文去重，避免重排浪费名额
    seen, unique_docs = set(), []
    for doc in fused:
        if doc.page_content not in seen:
            seen.add(doc.page_content)
            unique_docs.append(doc)

    return rerankChunks(question, unique_docs, top_k)


# 改写只依赖问题文本与历史，结果落盘复用：一次改写是 9s 的模型调用，
# 而评测每轮都要对同一批 45 道题重跑，缓存让重复轮次直接省掉这部分
REWRITE_CACHE_PATH = Path("resource/rewrite_cache.json")
# 改动下面的改写 prompt 必须 +1：否则旧缓存里的改写结果与新 prompt 口径不符
REWRITE_CACHE_VERSION = 1
_rewriteCache = None
_rewriteLock = threading.RLock()


def loadRewriteCache() -> dict:
    global _rewriteCache
    with _rewriteLock:
        if _rewriteCache is None:
            _rewriteCache = (
                json.loads(REWRITE_CACHE_PATH.read_text(encoding="utf-8"))
                if REWRITE_CACHE_PATH.exists() else {}
            )
        return _rewriteCache


def cacheRewrite(key: str, rewritten: str):
    with _rewriteLock:
        cache = loadRewriteCache()
        cache[key] = rewritten
        REWRITE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def llm_rewrite(query: str, history: str = "") -> str:
    """把口语化问题改写成书面检索查询。改写为空（模型异常输出）时回退原问题。"""
    # 模型名必须进键：换模型后改写口径就变了，命中旧模型留下的改写会悄悄改掉检索输入
    key = f"v{REWRITE_CACHE_VERSION}|{getModel().model_name}|{history}|{query}"
    cached = loadRewriteCache().get(key)
    if cached:
        return cached

    system_prompt = (
        "你是证券法规知识库的查询优化助手。将用户问题改写成适合检索的书面查询。\n"
        "规则：\n"
        "1) 保留精确法条号、主体（董事/监事/股东/高管）、动作（召集/表决/披露/担保）；\n"
        "2) 保留问题原有的行业、机构和范围限定（如证券公司、本公司），不得扩展成公司法、证券法"
        "等通用法律语境，也不得替换或新增主体；\n"
        "3) 补充多轮对话中缺失的主体和指代；\n"
        "4) 去除口语、闲聊、重复词；\n"
        "5) 不得引入原问题之外的概念、制度名称或条文号；\n"
        "6) 只输出一行改写后的查询，不解释不回答。"
    )
    if history:
        user_msg = f"历史对话：{history}\n原始问题：{query}\n改写后："
    else:
        user_msg = f"原始问题：{query}\n改写后："

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{user_msg}"),
    ])
    # temperature=0 让改写结果稳定；模型实例默认 0.5，用 bind 覆盖本次调用
    chain = prompt | getModel().bind(temperature=0) | StrOutputParser()

    rewritten = chain.invoke({"user_msg": user_msg}).strip() or query
    cacheRewrite(key, rewritten)
    return rewritten


async def uploadFileAndSaveDir(title:str,file :UploadFile):
    # 创建上传目录，如果不存在创建文件夹
    uploadDir.mkdir(parents=True, exist_ok=True)
    fileName = file.filename
    filePath = uploadDir / fileName
    ext = Path(fileName).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise Exception(f"不支持的文件类型：{ext}")
    # 检查文件大小是否超过最大限制
    if file.size > MAX_FILE_SIZE:
        raise Exception("文件大小超过最大限制")

    # 保存文件到指定路径
    with open(filePath, "wb") as f:
        while chunk := await file.read(FILE_CHUNK_SIZE):
            f.write(chunk)

    fileId = file_md5(filePath)
    with db_session() as db:
        exists = db.execute(select(zd_file_info).where(zd_file_info.ID == fileId)).first()
        if exists:
            raise Exception("文件已存在")

        # 保存文件信息到数据库
        zdfileinfo = zd_file_info()
        zdfileinfo.ID = fileId
        zdfileinfo.FILE_NAME = fileName
        zdfileinfo.FILE_PATH = str(filePath)
        zdfileinfo.FILE_TITLE = title
        zdfileinfo.FILE_TYPE = ext
        zdfileinfo.CREATE_DATE = datetime.now()
        db.add(zdfileinfo)
        db.commit()
        db.refresh(zdfileinfo)

    return zdfileinfo

def file_md5(filePath :str):
    hash_md5 = hashlib.md5()
    with open(filePath, "rb") as f:
        for chunk in iter(lambda : f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

async def FileToVector(chunk_size:int,chunk_overlap:int,file_id:str,filePath :str,ext :str):

    fileinfo = None
    with db_session() as db:
        fileinfo = db.execute(select(zd_file_info).where(zd_file_info.ID == file_id)).scalars().one()

    vector = getVector()
    documentSplitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        # separators 含正则（条文边界），必须显式开启，否则整条按字面量匹配必然失配
        is_separator_regex=True,
        separators=[
            r"\n\*\*第[一二三四五六七八九十百千]+条\*\*",  # 条文边界（文档格式：**第十五条**　）
            "\n## ",           # 章标题
            "\n\n",            # 段落
            "\n（",            # 中文序号列表项 ← 非常重要
            "\n",              # 行
            "。", "！", "？",  # 句号
            "；",              # 分号
            "，",              # 逗号
            " ",               # 空格
            "",                # 字符
        ]
    )
    chunk_count = 0
    documents = []

    if ext == "pdf":
        document = PyPDFLoader(filePath).load()
        documents = documentSplitter.split_documents(document)
        chunk_count = len(documents)
    elif ext == "txt" or ext == "md":
        document = TextLoader(
            filePath,
            encoding="utf-8"
        ).load()
        documents = documentSplitter.split_documents(document)
        chunk_count = len(documents)

    elif ext == "json":
        document = JSONLoader(filePath).load()
        documents = documentSplitter.split_documents(document)
        chunk_count = len(documents)
    else:
        raise Exception(f"不支持的文件类型：{ext}")

    # 给文档打标签，Chroma 只存 Document 对象，元数据必须是 str/int/float/bool
    # md 块也要带 fileid，否则 deleteDocument 按 fileid 删不掉向量
    for i, chunk in enumerate(documents):
        chunk.metadata.update({
            "fileid": file_id,
            "filename": fileinfo.FILE_NAME,
            "chunk_index": i,
            "total_chunks": chunk_count,
            "username": "root"
        })

    vector.add_documents(documents)

    # ---------- BM25 索引同步 ----------
    # 按本次 fileid 清掉旧块再合并：删除后重传同一文件且分块参数变化时，
    # chunk_index 对不上的旧尾巴也要清掉
    existing_docs = [d for d in loadBm25Docs() if d.metadata.get("fileid") != file_id]
    saveBm25Docs(existing_docs + documents)

    # 保存分块数量到数据库
    with db_session() as db:
        db.execute(update(zd_file_info).where(zd_file_info.ID == file_id).values(CHUNK_COUNT=chunk_count))
        db.commit()

    return chunk_count

def getDocuments(page:int,page_size:int,keyword:str):
    filters = [zd_file_info.FILE_TITLE.contains(keyword)] if keyword else []
    with db_session() as db:
        total = db.execute(
            select(func.count()).select_from(zd_file_info).where(*filters)
        ).scalar()
        query = (
            select(zd_file_info)
            .where(*filters)
            .order_by(zd_file_info.ID.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        documents = db.execute(query).scalars().all()

    return {"total": total, "items": [FileInfo.model_validate(d) for d in documents]}


def deleteDocument(document_id: str):
    with db_session() as db:
        document = db.execute(select(zd_file_info).where(zd_file_info.ID == document_id)).scalars().first()
        if not document:
            raise Exception("文件不存在")
        # 删除文件
        filePath = Path(document.FILE_PATH)
        if filePath.is_file():
            os.remove(filePath)
        # 删除数据库记录
        db.execute(delete(zd_file_info).where(zd_file_info.ID == document_id))
        db.commit()
        # 需要删除向量库文档
        vector = getVector()
        vector.delete(
            where={"fileid": document_id}
        )
        # BM25 索引同步：清掉该文件的所有块并重建
        saveBm25Docs([d for d in loadBm25Docs() if d.metadata.get("fileid") != document_id])

    return { "deleted": True, "chunk_count": document.CHUNK_COUNT }

def downloadDocument(document_id: str):
    with db_session() as db:
        document = db.execute(select(zd_file_info).where(zd_file_info.ID == document_id)).scalars().first()
    if not document:
        raise Exception("文件不存在")
    filePath = Path(document.FILE_PATH)
    if not filePath.is_file():
        raise Exception("文件不存在")

    return FileResponse(
        path=filePath,
        filename=document.FILE_NAME,
        media_type="application/octet-stream"
    )

def countDocuments():
    with db_session() as db:
        documents = db.execute(select(zd_file_info)).scalars().all()
        chunk_count = 0
        for document in documents:
            chunk_count += document.CHUNK_COUNT
        vector = getVector()
        return {"document_count":len(documents),"chunk_count":chunk_count,"vector_dim":len(vector.embeddings.embed_query("dim"))}




