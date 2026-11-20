import uuid
from datetime import datetime
from pathlib import Path

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory
from sqlalchemy import delete, func, select

from agent.initChatModel import getModel, getRiskGuard
from model.initDataBase import db_session
from model.models import messageInfo, qaFeedback
from observability import trace_config
from prompts import get_prompt
from service.ragFileService import hybridRetrieve  # [rerank]


def messagePrint(message):
    print("检索到的内容：" + message)
    return message


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def get_session_history(session_id: str):
    return SQLChatMessageHistory(
        session_id=session_id,
        connection_string="sqlite:///resource/checkpoints.db",
    )


# 生成口径统一收敛在 prompts.py，改版本只动那里的 CURRENT；
# tests/run_eval_data.py 另有自己的旧 prompt（自检脚本，分数不代表线上），不要拿它的分数做对照
GEN_SYSTEM_PROMPT = get_prompt("gen")


# 生产问答链路（同步实现）：检索 → prompt → 生成，消息落库。
# 返回 (答案, 检索到的块)：生成评估要让裁判看到同一份资料才能判 faithfulness，
# 同时评测方直接复用这份块算 recall/MRR，不必再检索一遍
# 若靠拼接字符串回传，答案里一旦出现 "=" 就会静默串数据
def generateAnswer(question: str, conversation_id: int, top_k: int) -> tuple:
    # 消息列表
    messageList = []
    humanMessage = messageInfo()
    humanMessage.id = str(uuid.uuid4())
    humanMessage.conversation_id = conversation_id
    humanMessage.role = "human"
    humanMessage.content =question
    humanMessage.created_at = datetime.now()
    messageList.append(humanMessage)

    # stream 本期预留，SSE 流式输出属后续迭代
    # [rerank] 检索与质量评测同链路：hybridRetrieve 双路召回 + RRF 粗排 + bge 重排，取 top_k 块
    # 检索结果链外算好，以 context 键注入 prompt（与模板变量同名）
    chunks = hybridRetrieve(question, top_k)
    content = format_docs(chunks)
    messagePrint(content)

    prompt = ChatPromptTemplate.from_messages([
        ("system", GEN_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("human", "【问题】:{input}")
    ])

    model = getModel()

    # 与评测基线一致：temperature=0 消除随机漂移；思考模式保持默认开启（关思考会拉低 completeness）
    chain = (
        prompt
        | model.bind(temperature=0)
        | StrOutputParser()
    )

    with_history = RunnableWithMessageHistory(
        chain,
        get_session_history,
        history_messages_key="history",
        input_messages_key="input",
    )

    # 模型适配层不支持异步路径，这里保持同步 invoke（链内有 sync-only 组件）
    chain_input = {"input": question, "context": content}
    config = trace_config(
        {"configurable": {"session_id": str(conversation_id)}},
        tags=["generate"],
        trace_name="generate",
        session_id=str(conversation_id),
    )
    answer = with_history.invoke(chain_input, config=config)

    # 免费档模型偶发返回空串（45 题实测 1 次），空回答对用户等同于故障，重试一次
    if not answer.strip():
        answer = with_history.invoke(chain_input, config=config)

    # 风测拦截要在落库前：库里必须存用户真正看到的答案，否则审计对不上
    # sources 传文档名（RiskGuard 用不带扩展名的 stem 做文档键），供张冠李戴检查用
    report = getRiskGuard().check(
        question, answer, content,
        [Path(c.metadata["filename"]).stem for c in chunks],
    )
    if report['should_block']:
        answer = "请咨询法律合规部门，已反馈法律合规部"

    aiMessage = messageInfo()
    aiMessage.id = str(uuid.uuid4())
    aiMessage.conversation_id = conversation_id
    aiMessage.role = "ai"
    aiMessage.content =answer
    aiMessage.created_at = datetime.now()
    messageList.append(aiMessage)

    with db_session() as db:
        db.add_all(messageList)
        db.commit()

    return answer, chunks


# 聊天问答服务
async def chatMessages(question: str, conversation_id: int, top_k: int, stream: bool):
    answer, _ = generateAnswer(question, conversation_id, top_k)
    return {"conversation_id": conversation_id, "role":"ai", "content": answer}


def queryConversationId():
    with db_session() as db:
        conversationIdList = db.execute(select(messageInfo.conversation_id).distinct()).scalars().all()
        return {"conversation_id":conversationIdList}

def queryHistoryMessage(conversation_id:str):
    history = get_session_history(conversation_id)
    return {"messages": [{"role": m.type, "content": m.content} for m in history.messages]}


def deleteHistoryMessage(conversation_id: str):
    # 消息记录与对话上下文是两份存储，需同步清理
    with db_session() as db:
        db.execute(delete(messageInfo).where(messageInfo.conversation_id == conversation_id))
        db.commit()

    get_session_history(conversation_id).clear()


# 用户对某条回答的操作留痕（复制/评价），问题和回答一起存，供后续统计分析
def saveQaFeedback(payload):
    record = qaFeedback(
        conversation_id=payload.conversation_id,
        question=payload.question,
        answer=payload.answer,
        action=payload.action,
    )
    with db_session() as db:
        db.add(record)
        db.commit()


def queryFeedbackStats():
    with db_session() as db:
        rows = db.execute(
            select(qaFeedback.action, func.count()).group_by(qaFeedback.action)
        ).all()
        return [{"action": action, "count": count} for action, count in rows]


# 筛选：问题模糊匹配（like）、操作精确匹配；按时间倒序分页
def queryFeedbackList(page: int, page_size: int, question: str = "", action: str = ""):
    stmt = select(qaFeedback)
    if question:
        stmt = stmt.where(qaFeedback.question.like(f"%{question}%"))
    if action:
        stmt = stmt.where(qaFeedback.action == action)

    with db_session() as db:
        total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
        rows = (
            db.execute(
                stmt.order_by(qaFeedback.created_at.desc(), qaFeedback.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return {
            "total": total,
            "items": [
                {
                    "id": r.id,
                    "conversation_id": r.conversation_id,
                    "question": r.question,
                    "answer": r.answer,
                    "action": r.action,
                    "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
                }
                for r in rows
            ],
        }
