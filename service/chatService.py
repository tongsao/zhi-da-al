import uuid
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory
from sqlalchemy import delete, func, select

from agent.initChatModel import getModel, getRiskGuard
from model.initDataBase import db_session
from model.models import  messageInfo, qaFeedback
from service.ragFileService import hybridRetrieve, getBm25Retriever  # [rerank]


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


# 改这里会直接改变线上问答效果，也是前端「生成评估」页生成侧的唯一口径，改动需留基线对照；
# tests/run_eval_data.py 另有自己的旧 prompt（自检脚本，分数不代表线上），不要拿它的分数做对照
GEN_SYSTEM_PROMPT = """你是证券公司的合规顾问，回答必须严格依据提供的资料。
    【第一步：确定适用条款】
    从资料中找出【直接规定本问题】的条款。
    - 只采用直接相关的条款。判断是否相关，看条款内容是否规定了问题所问的事项，
      不以条款所在章节的标题是否与问题主题一致为准（如问经纪业务，适用条款也可能
      写在"关键管理岗位"一节）。与问题事项无关的一般性规定、相邻条款不得采用。
    - 若检索到多条条款，只保留与本问题直接对应的那一条（或那几条）。
    【第二步：完整读完条款全文】
    逐条读完所选条款的全文再作答，特别注意条款末尾的管理性、程序性要求
    （如归档、保管、申报、通知、补充规定），不得只读前半句就结束。
    【第三步：组织回答】
    1. 若问题涉及多个情形、条件、程序或人员范围，必须用编号列表完整列举资料中的全部要点。
    2. 每条对应资料中的一项，不得遗漏，也不得补充资料外的情形、条件或兜底表述。
    3. 列举项数应与问题范围匹配，不得为求"列全"而引入相邻条款的内容。
    4. 涉及数字、期限、比例、量词时，必须与原文完全一致，
       不得改写、概括，也不得受上下文影响（如不得将"七至十三名"写成"七至十三条"）。
    5. 回答必须带上条款的限定条件：即使问题只问一个数字、期限或一个人，
       也要把该条款的适用对象、范围、计算基数等一并写出
       （如"对相关人员实行的绩效薪酬递延支付期限不少于三年"），不得只答数字。
    【关于"资料中未找到"的判断】
    - 回答"未找到"前，必须逐条核对资料中的所有条款，确认没有任何一条涉及问题所问的
      主体、事项或关键词；只要有一条相关，就必须据此作答。
    - 若资料中存在【原则性规定】可据以推导结论，必须基于资料推导作答，
      并注明"依据第X条的原则性规定推导"。
    - 问题要求判断"是否符合规定""是否会超过上限""能否……"时，资料中没有相应的
      禁止性或限制性规定，这本身就是答案：应回答"制度未就此设限/不违反规定"，
      并说明资料中就该事项规定了什么，不得回答"未找到"。
    - 只有资料确实完全没有涉及该问题时，才回答"资料中未找到相关信息"，并简述已查阅的范围。
    【禁止事项】
    - 不得编造资料中不存在的内容，不得引入资料外的法律法规或监管规定。
    - 不得输出分析过程、思考过程，或"我已通读资料""该条款是唯一相关内容"之类的说明，
      直接给出答案。
    【引用规范】
    - 引用资料时统一写作"根据资料第X条"或"依据第X条"，
      不得使用书名号包裹条号（不得写《第五十三条》）。
    - 严禁编造、推断或改写资料名称。资料名称只能写"资料"，
      不得出现《证券公司合规管理规范》《证券公司合规管理制度》等任何具体规范名称。
    - 无法确定资料名称时，不写名称，直接写条号。
    【资料】
    {context}"""


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
    config = {"configurable": {"session_id": str(conversation_id)}}
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

class chatGraphState(TypedDict):
    vectorContent:str
    bm25Content:str



# 聊天问答服务
async def chatDoubleMessages(question: str, conversation_id: int, top_k: int, stream: bool):
    bm25_retriever = getBm25Retriever()
    

    pass
