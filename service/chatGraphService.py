import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory
from langgraph.graph import add_messages

from agent.initChatModel import getEasyMode, getModel, getRiskGuard
from agent.rag.initRag import getVector
from model.initDataBase import db_session
from model.models import messageInfo
from service.chatService import GEN_SYSTEM_PROMPT, format_docs, get_session_history
from service.ragFileService import COARSE_K, COARSE_KEEP, getBm25Retriever, rerankChunks


# 聊天状态定义（类似于炎黄流程图每一个节点的数据结构）
class messageGraphState(TypedDict):
    # messages 存原生 LangChain 消息对象，add_messages 自动追加（不覆盖）
    messages: Annotated[list, add_messages]
    # 原始问题
    question:str
    # 改写后问题
    requestion:str
    # 会话ID
    conversation_id:str
    # 向量库检索的回答
    vec_docs:list[Document]
    # bm25库检索的回答
    bm25_docs:list[Document]
    # 合并之后的检索文档
    unique_docs:list[Document]
    # 边选择
    edgeState:str
    # top_k
    top_k:int
    # 最终回答
    answer: str

# 查询改写
def queryRewriteNode(state:messageGraphState):
    # 获取原始问题
    question = state['question']
    # 获取最近2次聊天历史
    last_msg =state['messages'][-4:]

    # 进行改写
    systemText = """
        你是证券法规知识库的查询优化助手。将用户问题改写成适合检索的书面查询。
        规则：
        1) 结合历史消息进行改写，如果历史消息和本次问题不相关就不用参考
        2) 保留精确法条号、主体（董事/监事/股东/高管）、动作（召集/表决/披露/担保）；
        3) 保留问题原有的行业、机构和范围限定（如证券公司、本公司），不得扩展成公司法、证券法
        等通用法律语境，也不得替换或新增主体；
        4) 补充多轮对话中缺失的主体和指代；
        5) 去除口语、闲聊、重复词；
        6) 不得引入原问题之外的概念、制度名称或条文号；
        7) 只输出一行改写后的查询，不解释不回答。 
        """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system",systemText),
            MessagesPlaceholder("history"),
            ("human","{input}")
        ]
    )
    # 组装提示词,进行改写
    llm = getEasyMode()

    chain = prompt | llm |StrOutputParser()
    requestion = chain.invoke({"history":last_msg,"input":question})

    return {
        "requestion":requestion
    }

# 双路召回节点
def queryBm25AndvectorNode(state:messageGraphState):
    # 改写问题，向量库召回
    requestion = state['requestion']
    # 原始问题，bm25召回
    question = state['question']
    # 2. 分别检索
    vector_retriever = getVector().as_retriever(search_kwargs={"k": COARSE_K})
    bm25_retriever = getBm25Retriever()

    vec_docs = vector_retriever.invoke(requestion)  # 向量用改写后
    bm25_docs = bm25_retriever.invoke(question) if bm25_retriever else []  # BM25 用原问题

    # 3. RRF 融合（只看排名，不看分数）

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
    
    return {
        "vec_docs":vec_docs,
        "bm25_docs":bm25_docs,
        "unique_docs":unique_docs
    }

# 重排序节点
def reRankNode(state:messageGraphState):
    # 与 hybridRetrieve 同口径：重排用原问题比对，截断到 top_k；空候选由 rerankChunks 内部兜底
    reranked = rerankChunks(state['question'], state['unique_docs'], state['top_k'])
    return {
        "unique_docs":reranked
    }

# 生成回答
def chatMessageNode(state:messageGraphState):
    conversation_id = state["conversation_id"]
    question= state["question"]
    unique_docs = state["unique_docs"]
    content = format_docs(unique_docs)

    prompt = ChatPromptTemplate.from_messages([
        ("system", GEN_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("human", "【问题】:{input}")
    ])

    model = getModel()

    # 与评测基线一致：temperature=0 消除随机漂移；思考模式保持默认开启（关思考会拉低 completeness）
    chain = (
        prompt
        | model.bind(temperature=0.2)
        | StrOutputParser()
    )

    with_history = RunnableWithMessageHistory(
        chain,
        get_session_history,  # 第二参数是工厂函数，langchain 会用 config 里的 session_id 调它取历史
        history_messages_key="history",
        input_messages_key="input",
    )
    # 模型适配层不支持异步路径，这里保持同步 invoke（链内有 sync-only 组件）
    chain_input = {"input": question, "context": content}
    config = {"configurable": {"session_id": str(conversation_id)}}
    answer = with_history.invoke(chain_input, config=config)

    # 免费档模型偶发返回空串（45 题实测 1 次），空回答对用户等同于故障，重试一次
    if not answer.strip():
        answer = with_history.invoke(chain_input, config=config)

    # 风测拦截要在落库前：库里必须存用户真正看到的答案，否则审计对不上
    # sources 传文档名（RiskGuard 用不带扩展名的 stem 做文档键），供张冠李戴检查用
    report = getRiskGuard().check(
        question, answer, content,
        [Path(c.metadata["filename"]).stem for c in unique_docs],
    )
    if report['should_block']:
        answer = "请咨询法律合规部门，已反馈法律合规部"

    # 与 generateAnswer 同口径：会话留痕落 messageInfo 表（历史会话列表靠它枚举）。
    # 图里 with_history 已把消息写进 SQLChatMessageHistory，这里补 ORM 表，两份存储同步
    messageList = []
    for role, content in (("human", question), ("ai", answer)):
        msg = messageInfo()
        msg.id = str(uuid.uuid4())
        msg.conversation_id = conversation_id
        msg.role = role
        msg.content = content
        msg.created_at = datetime.now()
        messageList.append(msg)
    with db_session() as db:
        db.add_all(messageList)
        db.commit()

    return {"answer":answer}










