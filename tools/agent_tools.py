import hashlib
import json
from operator import add

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.prebuilt import InjectedState
from sqlalchemy import select
from typing_extensions import Annotated, TypedDict

from agent.initChatModel import checkpointer, getModel
from model.initDataBase import db_session
from model.models import evalGenRun, evalRun
from prompts import get_prompt
from service.chatGraphService import (
    chatMessageNode,
    messageGraphState,
    queryBm25AndvectorNode,
    queryRewriteNode,
    reRankNode,
)
from service.chatService import get_session_history
from tools.toolRecovery import ToolErrorRecoveryMiddleware


# Agent 状态的扩展字段：graphAnswer 需要但不应让模型自己猜的请求级参数
# messages 必须保留——create_agent 的模型节点靠它驱动循环
class ChatAgentState(TypedDict):
    messages: Annotated[list, add]
    conversation_id: int
    top_k: int


# 进程级单例：编译图每次构建+编译开销大（跑 4 个节点函数的图约秒级），进程内复用一份
_compiled_graph = None

def _getCompiledGraph():
    global _compiled_graph
    if _compiled_graph is None:
        graph = StateGraph(messageGraphState)
        graph.add_node(queryRewriteNode)
        graph.add_node(queryBm25AndvectorNode)
        graph.add_node(reRankNode)
        graph.add_node(chatMessageNode)

        graph.add_edge(START,"queryRewriteNode")
        graph.add_edge("queryRewriteNode","queryBm25AndvectorNode")
        graph.add_edge("queryBm25AndvectorNode","reRankNode")
        graph.add_edge("reRankNode","chatMessageNode")
        graph.add_edge("chatMessageNode",END)
        _compiled_graph = graph.compile()
    return _compiled_graph


# graphAnswer 内各阶段完成时上报的进度：节点名 → (百分比, 展示文案)
_GRAPH_PROGRESS_STEPS = {
    "queryRewriteNode": (20, "改写问题"),
    "queryBm25AndvectorNode": (50, "双路检索"),
    "reRankNode": (75, "重排排序"),
    "chatMessageNode": (100, "生成完成"),
}


@tool
def graphAnswer(
    question: str,
    conversation_id: Annotated[int, InjectedState("conversation_id")],
    top_k: Annotated[int, InjectedState("top_k")],
):
    """
    回答用户关于企业知识库内容的问题（证券合规制度类）。这是唯一能产出正式答案的工具。

    适用场景：
    - 用户问法条、流程、职责、时限、比例等知识库内容问题；
    - 包含指代的多轮对话（如"那保存期限呢？"），工具会自动结合会话历史改写问题；
    - 需要先检索资料再作答的问题。

    不适用场景：
    - 闲聊、翻译、计算、通用知识——不要调用本工具，直接告知无法回答；
    - 仅查询评测历史指标——那有专用工具。

    内部流程：改写问题 → 双路检索（向量+BM25）→ RRF 融合去重 → bge 重排 → 依据资料生成回答（temperature=0），回答严格忠于资料，找不到会如实说明。

    :param question: 用户当前这一轮的原问题（不做预改写，直接传原文）
    :param conversation_id: 会话 ID，用于拉取多轮对话历史（指代消解依赖它，务必传当前会话）
    :param top_k: 最终送入生成的检索片段数量，一般 4~8
    :return: 生成答案的纯文本字符串（无 JSON 包装）
    """
    # 复用进程级编译图：首次惰性编译，之后每次问答省去建图+编译（约秒级）
    graphDo = _getCompiledGraph()
    historyMessage = get_session_history(str(conversation_id))
    # 工具内部的阶段进度通过 LangGraph custom 流推给前端；非流式调用时写入为空操作
    streamWriter = get_stream_writer()

    result = {}
    for nodeUpdate in graphDo.stream({
        "question":question,
        "conversation_id":conversation_id,
        "top_k":top_k,
        # 图内节点按消息列表切片取历史，传实例（SQLChatMessageHistory 不可切片）会直接崩
        "messages":historyMessage.messages
    }, stream_mode="updates"):
        for nodeName, delta in nodeUpdate.items():
            result.update(delta or {})
            percent, label = _GRAPH_PROGRESS_STEPS[nodeName]
            streamWriter({"stage": nodeName, "percent": percent, "label": label})

    return result["answer"]


@tool
def queryReCalAndMrr():
    """
    查询最近一次「检索评估」的结果（不含 LLM 生成，只评估检索召回质量）。

    适用场景：用户问"知识库检索得准不准 / Recall 多少 / MRR 如何 / 检索评估结果"，或想了解最近一次检索质量趋势。

    指标含义：
    - recall_any / recall_all：召回率@k。any=候选块命中任一关键词即算召回，all=块需包含全部关键词才算召回（更严格）
    - mrr_any / mrr_all：平均倒数排名，衡量相关块排得多靠前
    - top_k：该次评测的检索片段数量；created_at：评测时间

    返回的是最近一次（按评测 id 倒序）的汇总指标，不含逐题明细。

    :return: 检索评估指标字典；若从未跑过检索评估则返回 {"error": "..."}
    """
    with db_session() as db:
        row = db.execute(
            select(evalRun)
            .where(evalRun.run_type == "retrieval")
            .order_by(evalRun.id.desc())
        ).scalars().first()

    if row is None:
        return {"error": "暂无检索评估记录，请先发起检索评测"}

    return {
        "run_id": row.id,
        "top_k": row.top_k,
        "total": row.total,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "recall_any": row.recall_any,
        "recall_all": row.recall_all,
        "mrr_any": row.mrr_any,
        "mrr_all": row.mrr_all,
    }


@tool
def queryLlmAsJudgeResult():
    """
    查询最近一次「生成评估」的结果（LLM 问答全链路 + 裁判打分，评估生成质量）。

    适用场景：用户问"回答质量怎么样 / 完整度如何 / 忠于资料吗 / 生成评估结果"，或想对比最近一次生成质量趋势。

    指标含义（满分均为 2，avg=均分，full_rate=得满分的题占比）：
    - correctness_avg / correctness_full_rate：事实正确性，数字、期限、比例是否与资料一致
    - completeness_avg / completeness_full_rate：要点完整性，问题范围内的要点是否齐全
    - faithfulness_avg / faithfulness_full_rate：忠于资料，是否编造资料外内容
    - top_k：该次评测的检索片段数量；total：评测题数；elapsed_seconds：总耗时秒

    仅返回 status=success 的最近一次（按评测 id 倒序）汇总指标，不含逐题明细。

    :return: 生成评估指标字典；若从未跑过成功的生成评估则返回 {"error": "..."}
    """
    with db_session() as db:
        row = db.execute(
            select(evalGenRun)
            .where(evalGenRun.status == "success")
            .order_by(evalGenRun.id.desc())
        ).scalars().first()

    if row is None:
        return {"error": "暂无成功的生成评估记录，请先发起生成评测"}

    return {
        "run_id": row.id,
        "top_k": row.top_k,
        "total": row.total,
        "elapsed_seconds": row.elapsed_seconds,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "correctness_avg": row.correctness_avg,
        "completeness_avg": row.completeness_avg,
        "faithfulness_avg": row.faithfulness_avg,
        "correctness_full_rate": row.correctness_full_rate,
        "completeness_full_rate": row.completeness_full_rate,
        "faithfulness_full_rate": row.faithfulness_full_rate,
    }


AGENT_TOOLS = [graphAnswer, queryReCalAndMrr, queryLlmAsJudgeResult]

# 工具集版本：语义版本手动维护，内容哈希自动反映工具名/描述/参数的真实变化，
# 两者一起写入 Langfuse Trace，审计时能判断“工具变没变、有没有忘记升版本”
TOOL_VERSION = "v1"


def _toolset_hash(tools) -> str:
    payload = [
        {"name": tool.name, "description": tool.description, "args": tool.args}
        for tool in tools
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]


TOOLSET_HASH = _toolset_hash(AGENT_TOOLS)

# 工具名 → 前端提示文案：与工具定义同文件维护，新增工具时不会漏改。
# 接口层只 import 使用，不再硬编码工具名单。
TOOL_HINTS = {
    "graphAnswer": "正在检索知识库…",
    "queryReCalAndMrr": "正在读取检索评估结果…",
    "queryLlmAsJudgeResult": "正在读取生成评估结果…",
}

_agent = None  # 进程级单例：Agent 编译开销大，且多请求共用一个图即可


def getChatAgent():
    global _agent
    if _agent is None:
        _agent = create_agent(
            getModel(),
            AGENT_TOOLS,
            state_schema=ChatAgentState,
            system_prompt=get_prompt("agent"),
            checkpointer=checkpointer,
            # 防死循环（按实际链路校准）：
            # ■ 模型调用：正常一轮是「决策→作答」2 次，多意图顶多 3 次，4 次只给参数纠错留一次余量；
            #   超限直接 end，不再让模型空转。
            # ■ 工具调用：一轮最多 3 次，够覆盖「问答 + 两个评估工具」的组合，再多必是重复调用。
            # ■ graphAnswer 单轮 1 次：它内部是完整 RAG 链路（改写+双路检索+重排+生成），
            #   重复调用每次至少十几秒，很容易吃满 chatController 的 120s 流式总预算。
            # 不设 thread_limit：会话状态跨轮持久化（SqliteSaver），按线程累计会误伤长会话。
            middleware=[
                # 最外层兜住工具异常：模型修参重试 2 次，仍失败则返回失败 ToolMessage 让模型告知用户
                ToolErrorRecoveryMiddleware(),
                ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
                ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
                ToolCallLimitMiddleware(tool_name="graphAnswer", run_limit=1, exit_behavior="continue"),
            ],
        )
    return _agent
