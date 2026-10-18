import asyncio
import json
import queue
import threading
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from langchain_core.messages import HumanMessage

from agent.handle.llm_stream_handle import CancelToken, StreamHandle
from schema.schemas import Response, QaFeedback

from service.chatService import (
    queryConversationId, queryHistoryMessage, deleteHistoryMessage,
    saveQaFeedback, queryFeedbackStats, queryFeedbackList,
)
from tools.agent_tools import getChatAgent

router = APIRouter(prefix="/api/v1/qa", tags=["聊天问答"])

# ---- 全局状态：取消令牌登记表 + 流式处理器 ----
# 每个流式生成都会注册一个「取消令牌」在这里，key 是会话 ID。
# 用户点「停止」时，/chat/stop 拿着会话 ID 找到令牌并触发，让生成停下来。
active_cancel_tokens: dict[str, CancelToken] = {}

# 流式处理器单例：统一处理「取消 / 超时 / 断流 / 重试」四种情况。
# 预算说明：agent 链路包含改写 + 双路检索 + 重排 + 生成，比单纯调 LLM 慢得多，
# 所以总时长（120s）和单块间隔（30s）都比纯模型调用给得宽松。
stream_processor = StreamHandle(total_budget=120.0, idle_budget=30.0)


async def _agent_answer_text_stream(question: str, conversation_id: int, top_k: int) -> AsyncIterator[str]:
    """（内部函数）以「文字片段」异步地产出 agent 的回答，供流式推送使用。

    输入：
        question         用户问的问题
        conversation_id  会话 ID（LangGraph 用它保存和恢复对话记忆）
        top_k            检索知识库时取回的文档数量
    输出：
        一个异步生成器，每次 yield 一小段回答文字（UTF-8 字符串）。
        生成结束（成功或失败）时生成器自然停止。

    为什么需要后台线程？
        LangChain 的 SQLite 记忆功能只支持同步方法，agent.stream(...) 只能在普通
        线程里跑；而 FastAPI 的流式响应必须在协程里逐段产出。所以这个函数是两者
        之间的「桥」：后台线程跑 agent，主协程循环取结果。

    为什么用 queue.Queue 而不是 asyncio.Queue？
        queue.Queue 线程安全，且配合 asyncio.to_thread(...) 取数，即使后台线程
        长时间没产出，协程也不会死锁（asyncio.Queue 跨线程 put 会丢唤醒信号）。
    """
    agent = getChatAgent()
    agent_input = {
        "messages": [HumanMessage(content=question)],
        "conversation_id": conversation_id,
        "top_k": top_k,
    }
    # 会话级隔离：LangGraph 按 thread_id 区分不同会话的记忆，必须传，
    # 否则所有用户共享同一个会话状态，会互相串线。
    agent_config = {"configurable": {"thread_id": str(conversation_id)}}

    # ---- 后台线程与主协程之间的「信箱」 ----
    text_queue = queue.Queue()     # 线程安全队列：后台线程往里放，主协程从里取
    stop_event = threading.Event() # 停止信号：后台线程每轮循环检查它
    QUEUE_FINISHED = object()      # 哨兵值：表示「agent 生成完毕，没有更多内容了」
    QUEUE_ERROR = "__error__"      # 哨兵标记：表示「agent 出错」，细节放在同队列的元组里

    def run_agent_in_background():
        """后台线程执行体：运行 agent，把答案片段逐个放进队列。"""
        try:
            for message_chunk, stream_metadata in agent.stream(
                agent_input, config=agent_config, stream_mode="messages"
            ):
                if stop_event.is_set():
                    break  # 前端取消/超时了，别再继续跑，避免白白消耗 token

                # agent 内部有多个节点：改写问题、检索文档、决定调工具、生成答案……
                # 只有「model」节点、且非工具调用的纯文字，才是最终回答，
                # 检索/改写/工具决策这些中间输出都不该推给用户。
                if stream_metadata.get("langgraph_node") != "model":
                    continue
                if getattr(message_chunk, "tool_call_chunks", None):
                    continue

                answer_piece = message_chunk.content
                if isinstance(answer_piece, str) and answer_piece:
                    text_queue.put(answer_piece)
        except Exception as error:
            # 外部模型调用/网络异常：不在这里吞掉，把错误放回队列，
            # 主协程会把它重新抛出，交给 StreamHandle 决定「重试」还是「报错」。
            text_queue.put((QUEUE_ERROR, str(error)))
        finally:
            # 无论成功还是失败，最后都要通知主协程「没有更多内容了」
            text_queue.put(QUEUE_FINISHED)

    background_thread = threading.Thread(target=run_agent_in_background, daemon=True)
    background_thread.start()

    try:
        while True:
            # 阻塞等待后台线程放入内容。放进 asyncio.to_thread(...) 避免把协程卡死
            item = await asyncio.to_thread(text_queue.get)
            if item is QUEUE_FINISHED:
                return
            if isinstance(item, tuple) and item[0] == QUEUE_ERROR:
                raise RuntimeError(item[1])
            yield item  # 向 StreamHandle 交付一段答案文字
    finally:
        # 无论什么原因离开生成器（推完 / 被取消 / 超时暂停），都要停掉后台线程
        stop_event.set()
        background_thread.join(timeout=2)


async def _build_sse_stream(question: str, conversation_id: int, top_k: int, request: Request):
    """（内部函数）构建 SSE 事件流，供 StreamingResponse 推送给前端。

    输入：
        question / conversation_id / top_k  这三个会原样传给 _agent_answer_text_stream
        request   当前 HTTP 请求（用来探测「客户端是不是已经断开连接」）
    输出：
        一个异步生成器，每次 yield 一行 SSE 文本（形如 data: {...}\n\n）。

    分工：
        取消 / 超时 / 断流 / 重试 这些复杂判断全部交给 StreamHandle，
        这个函数只做两件简单的事：
          1) 为本次生成创建「取消令牌」并登记到全局表，供 /chat/stop 触发；
          2) 把 StreamHandle 返回的事件翻译成前端能识别的 SSE 格式。
    """
    session_id = str(conversation_id)
    cancel_token = CancelToken()
    active_cancel_tokens[session_id] = cancel_token

    def create_answer_stream(_ignored_previous_text):
        """StreamHandle 的「生成器工厂」。

        StreamHandle 在重试时会传入一段已生成的文字（前缀），它的原意是
        「接着这段继续生成」。但我们的 agent 是整张图重跑（检索+改写+生成），
        用不上前缀，所以这里忽略它，每次都完整地重新生成一轮。
        """
        return _agent_answer_text_stream(question, conversation_id, top_k)

    try:
        async for event in stream_processor.run(
            create_answer_stream,
            session_id=session_id,
            token=cancel_token,
            probe=request.is_disconnected,
        ):
            if event["type"] == "delta":
                # 正常答案片段：直接转发
                yield f"data: {json.dumps({'content': event['text']}, ensure_ascii=False)}\n\n"
            elif event["type"] == "error":
                # 不可重试的错误：把错误信息推给前端展示，然后结束
                yield f"data: {json.dumps({'error': event['message']}, ensure_ascii=False)}\n\n"
                break
            # 其余事件类型（done / cancelled / partial / retry）不需要通知前端：
            #   断流与取消时，客户端早就离开了，消息推不出去；
            #   重试会自动再来一轮，前端不需要感知。
    finally:
        # 本次生成结束，注销取消令牌，避免全局表越积越多
        active_cancel_tokens.pop(session_id, None)

    yield "data: [DONE]\n\n"  # SSE 结束标记，前端读到后停止读取


@router.post("/chat")
async def chat(request: Request, question: str, conversation_id: int, top_k: int = 6, stream: bool = False):
    """对话接口：支持流式和一次性两种方式。

    输入：
        question         用户问的问题
        conversation_id  会话 ID
        top_k            检索知识库时取回的文档数量（默认 6）
        stream           是否使用流式输出（默认否）
    输出：
        stream=True  → 返回 SSE 流：逐段推送 AI 回答，前端边收边渲染
        stream=False → 返回完整 JSON：{ conversation_id, role, content }
    """
    # 流式问答：交给 StreamHandle 统一兜底取消/超时/断流/重试
    if stream:
        return StreamingResponse(
            _build_sse_stream(question, conversation_id, top_k, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        # Agent 版链路：模型决策选工具（graphAnswer 检索问答 / 两个评估工具），stream=false 的单次兜底
        agent = getChatAgent()
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=question)],
                "conversation_id": conversation_id,
                "top_k": top_k,
            },
            # 会话级隔离：SqliteSaver 按 thread_id 分线程，不传则全站共用一个线程会串线
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        answer = result["messages"][-1].content
        # 前端按原链路返回结构消费：{ conversation_id, role, content }
        data = {"conversation_id": conversation_id, "role": "ai", "content": answer}
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response

    response = Response()
    response.data = data
    return response


@router.post("/chat/stop")
async def stop_generation(conversation_id: int):
    """用户点「停止生成」时调用。

    功能：通过会话 ID 找到该会话的「取消令牌」并触发。
         StreamHandle 检测到令牌后，会在下一轮循环里掐断上游模型，
         同时后台线程也会收到 stop_event 退出，不再消耗 token。

    输入：conversation_id  正在生成的会话 ID
    输出：{"ok": True}（无论有没有找到令牌都返回成功，保证前端不报错）
    """
    cancel_token = active_cancel_tokens.get(str(conversation_id))
    if cancel_token:
        cancel_token.cancel(reason="user_stop")
    return {"ok": True}

@router.get("/chat/conversation_id")
def getConversationId():
    return queryConversationId();

@router.get("/chat/gethistory")
def getHistoryMessage(conversation_id):
    return queryHistoryMessage(conversation_id)

@router.delete("/chat/conversation_id")
def deleteMessage(conversation_id: str):
    try:
        deleteHistoryMessage(conversation_id)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response

    response = Response()
    return response


@router.post("/feedback")
def feedback(payload: QaFeedback):
    try:
        saveQaFeedback(payload)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response

    response = Response()
    return response


# 人工测评分析：action 各操作数量统计（扇形图数据源）
@router.get("/feedback/stats")
def feedbackStats():
    try:
        return queryFeedbackStats()
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response


# 人工测评分析：留痕明细，问题模糊查询 + 操作筛选 + 分页
@router.get("/feedback/list")
def feedbackList(page: int = 1, page_size: int = 30, question: str = "", action: str = ""):
    try:
        return queryFeedbackList(page, page_size, question, action)
    except Exception as e:
        response = Response()
        response.code = "5001"
        response.message = str(e)
        return response