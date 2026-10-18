"""
LLM 流式调用统一处理器 —— 取消 / 超时 / 断流 / 重试 四合一
================================================================
技术栈：LangChain 1.4.x / LangGraph 1.2.x / FastAPI / Qwen(DashScope 兼容)

设计要点（全部经过实测验证）：
  1. 四种异常【共用同一个 finally】，而不是写四套逻辑
  2. 对外只【补发增量】，已发出的 chunk 绝不重发
  3. 断流/超时后默认 drain（后台跑完并缓存），让续写秒回
  4. retry 带 prefix 续写，不重复生成
"""
from __future__ import annotations

import asyncio
import enum
import inspect
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Optional

# ---- 类型别名：让函数签名一眼看懂 ----
# 生成器工厂：传入「已生成的前缀文字」，返回一个新的异步生成器（产出后续文字片段）。
# 重试时工具会用它带着前缀重新开始，保证已发出的内容不重复生成。
StreamFactory = Callable[[str], AsyncIterator[str]]

# 断流探测函数：返回客户端当前是否已断开连接。
# FastAPI 里直接传 request.is_disconnected 即可（它本身是异步方法，也能用）。
DisconnectProbe = Callable[[], bool]

# 落库回调：会话结束时把结果保存起来。
# 参数依次是：(会话 ID, 最终文字, 结束状态, 附加信息)
PersistHook = Callable[[str, str, "Status", dict], None]


class Status(str, enum.Enum):
    """一次流式生成的结束状态。

    别用布尔值！「后台跑完缓存（drained）」和「正常送完（done）」在计费/对账
    上是两回事：前者用户没拿到完整结果，后者拿到了。
    """
    STREAMING = "streaming"          # 正在生成中
    DONE = "done"                    # 正常送完
    CANCELLED = "cancelled"          # 用户主动停止 → 掐断上游
    TOTAL_TIMEOUT = "total_timeout"  # 总预算耗尽 → drain（不重试：预算已用完）
    IDLE_TIMEOUT = "idle_timeout"    # 卡死（chunk 间隔超阈值）→ 可重试
    BROKEN = "broken"                # 断流（网络掉线）→ drain（不重试：用户已不在）
    UPSTREAM_ERROR = "upstream_error"  # 上游可重试异常（503/429）→ 重试
    DRAINED = "drained"              # 断流后后台跑完了（用户没拿到，但已缓存）
    FATAL = "fatal"                  # 不可重试错误（401/400/拦截）


# 可重试 vs 不可重试：按错误文本里的关键词粗判。
# 判断顺序很关键——先排除「致命关键词」，再看「可重试关键词」。
_FATAL_KEYS = ("401", "400", "403", "404", "content_filter", "invalid_api_key",
               "invalid_request", "authentication")
_RETRY_KEYS = ("429", "500", "502", "503", "504", "timeout", "timed out",
               "connection", "reset", "temporarily", "overloaded")


def is_retryable(error: BaseException) -> bool:
    """判断一个异常是否值得重试。

    输入：error  从上游（LLM API）抛出的异常
    输出：True  = 可以重试（如 429 限流、5xx 服务端错误、网络抖动）
         False = 重试也没用（如 401 鉴权失败、400 参数错误、内容被拦截）
    """
    error_text = str(error).lower()
    if any(key in error_text for key in _FATAL_KEYS):
        return False
    return any(key in error_text for key in _RETRY_KEYS)


class CancelToken:
    """取消令牌：把「三种取消来源」统一成同一个信号。

    取消来源可能有：用户主动点停止 / 前端连接断开 / 人工审批叫停，
    它们最终都会调用 cancel() 置位内部同一个事件。生成循环里只要检查
    cancelled 属性就知道该停了，不用关心是谁触发的。
    """

    def __init__(self) -> None:
        self._cancel_event = asyncio.Event()  # 内部事件：置位 = 已取消
        self.reason = ""                      # 取消原因，方便排查日志

    def cancel(self, reason: str = "user_abort") -> None:
        """请求取消本次生成（幂等：重复调用只有第一次生效）。"""
        if not self._cancel_event.is_set():
            self.reason = reason
            self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        """是否已被请求取消。"""
        return self._cancel_event.is_set()


@dataclass
class Session:
    """一次流式生成的运行记录（会话结束时传给 on_persist 回调落库）。"""
    session_id: str
    status: Status = Status.STREAMING          # 当前/最终状态
    text: str = ""                             # 已生成的文字（含重试前的部分）
    attempts: int = 0                          # 已经尝试的轮数（含初次）
    duration_ms: int = 0                       # 总耗时（毫秒）
    errors: list = field(default_factory=list)                # 每次失败的简记
    metadata: dict = field(default_factory=dict)              # 额外信息（如取消原因）


class StreamHandle:
    """
    用法：
        handle = StreamHandle()
        async for event in handle.run(factory, token=tok, probe=request.is_disconnected):
            if event["type"] == "delta": yield sse(event["text"])
    """

    def __init__(
        self,
        total_budget: float = 45.0,   # 总时长上限（秒）：防止「慢慢吐个没完」
        idle_budget: float = 15.0,    # 单块最大间隔（秒）：防止「卡死不动」
        max_retries: int = 3,         # 最多重试几轮
        base_delay: float = 0.3,      # 重试间隔基数（秒），按指数退避增长
        drain_on_break: bool = True,  # 断流/超时后后台跑完（续写秒回）
        abandon_ratio: float = 0.6,   # 已发出这么多比例 → 放弃重试
        expected_total: Optional[int] = None,  # 预生成长度，用于算比例
        on_persist: Optional[PersistHook] = None,  # 会话结束时的落库回调
    ) -> None:
        self.total_budget = total_budget
        self.idle_budget = idle_budget
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.drain_on_break = drain_on_break
        self.abandon_ratio = abandon_ratio
        self.expected_total = expected_total
        self.on_persist = on_persist
        # 所有历史的会话记录：会话 ID -> Session
        self.sessions: dict[str, Session] = {}
        # 后台任务集合（drain / 掐断上游），保存引用防止被垃圾回收
        self._background_tasks: set[asyncio.Task] = set()

    # ---------------- 主入口 ----------------
    async def run(
        self,
        factory: StreamFactory,
        session_id: Optional[str] = None,
        token: Optional[CancelToken] = None,
        probe: Optional[DisconnectProbe] = None,
    ) -> AsyncIterator[dict]:
        """启动一次流式生成，产出事件序列。

        输入：
            factory     生成器工厂：传入已生成前缀文字，返回新的异步生成器
            session_id  会话 ID（不传则自动生成一个）
            token       取消令牌：用户点停止 / 断流时由外部置位
            probe       断流探测函数：返回客户端是否已断开
        输出：
            事件 dict 的异步迭代器，常见事件类型：
              delta   新文字片段        {"type":"delta", "text":片段}
              done    正常结束          {"type":"done", "text":完整结果}
              error   不可重试错误      {"type":"error", "message":原因}
              partial 部分结果收尾      {"type":"partial", "text":..., "reason":...}
              retry   准备重试          {"type":"retry", "attempt":轮数, "delay":秒}
        """
        resolved_session_id = session_id or uuid.uuid4().hex[:12]
        session = Session(session_id=resolved_session_id)
        self.sessions[resolved_session_id] = session

        sent_parts: list[str] = []          # 已经交付给调用方的文字片段
        stream_holder: dict = {"stream": None}  # 容器：存放当前上游生成器（收尾时要取出）
        start_time = time.time()

        try:
            async for event in self._stream_with_retry(
                factory, session, sent_parts, stream_holder, token, probe, start_time
            ):
                yield event
        except asyncio.CancelledError:
            # 生成器被取消：token 置位才是「用户主动停止」，否则算断流
            if not (token is not None and token.cancelled):
                session.status = Status.BROKEN
            else:
                session.status = Status.CANCELLED
            raise  # ⚠️ 绝不吞掉，吞了会连接泄漏
        finally:
            # 无论以什么方式结束，都在这里记录最终结果并收尾上游
            session.text = "".join(sent_parts)
            session.duration_ms = int((time.time() - start_time) * 1000)
            self._finalize_session(resolved_session_id, session, stream_holder)

    # ---------------- 主循环（含重试）----------------
    async def _stream_with_retry(
        self, factory, session, sent_parts, stream_holder, token, probe, start_time
    ) -> AsyncIterator[dict]:
        """核心循环：拉取文字 → 逐项检查异常 → 决定「结束 / 重试 / 收尾」。

        输入：
            factory / token / probe  见 run() 的说明
            session       本次会话记录（attempts / status 会在这里更新）
            sent_parts    已经交付的文字片段列表
            stream_holder 装着当前上游生成器的容器
            start_time    本次生成开始的时刻，用来算总预算
        输出：与 run() 相同的事件流
        """
        attempt_number = 0
        while True:
            attempt_number += 1
            session.attempts = attempt_number
            prefix_text = "".join(sent_parts)     # 已生成部分，重试时传给工厂
            answer_stream = factory(prefix_text)  # 创建本轮上游生成器
            stream_holder["stream"] = answer_stream
            is_fatal_error = False

            try:
                while True:
                    # ① 取消（用户主动停止）
                    if token is not None and token.cancelled:
                        session.status = Status.CANCELLED
                        break
                    # ② 总超时
                    if time.time() - start_time > self.total_budget:
                        session.status = Status.TOTAL_TIMEOUT
                        break
                    # ③ 断流（辅助探测；真正的兜底是下面的 CancelledError）
                    #    probe 可能是同步函数，也可能是 request.is_disconnected（异步）
                    if probe is not None:
                        is_disconnected = probe()
                        if inspect.isawaitable(is_disconnected):
                            is_disconnected = await is_disconnected
                        if is_disconnected:
                            session.status = Status.BROKEN
                            break

                    try:
                        # ④ 空闲超时：只给「下一个文字块」定一个等待上限
                        text_piece = await asyncio.wait_for(
                            answer_stream.__anext__(), timeout=self.idle_budget
                        )
                    except StopAsyncIteration:
                        session.status = Status.DONE
                        break
                    except asyncio.TimeoutError:
                        session.status = Status.IDLE_TIMEOUT
                        break
                    except asyncio.CancelledError:
                        # token 置位 = 用户主动停止；否则多半是网络断流（连接断开）
                        session.status = (
                            Status.CANCELLED
                            if (token is not None and token.cancelled)
                            else Status.BROKEN
                        )
                        raise
                    except Exception as error:     # ⑤ 上游出错
                        session.errors.append(f"#{attempt_number}:{type(error).__name__}")
                        if not is_retryable(error):
                            session.status = Status.FATAL
                            is_fatal_error = True
                        else:
                            session.status = Status.UPSTREAM_ERROR
                        break

                    sent_parts.append(text_piece)
                    yield {"type": "delta", "text": text_piece,
                           "session_id": session.session_id}

            except asyncio.CancelledError:
                session.status = Status.CANCELLED
                raise
            finally:
                await self._close_stream_if_needed(answer_stream, session)

            # ---- 结束：正常 / 致命 / 取消 ----
            if session.status is Status.DONE:
                yield {"type": "done", "text": "".join(sent_parts),
                       "status": session.status.value, "session_id": session.session_id}
                return

            if is_fatal_error:
                yield {"type": "error", "message": "不可重试错误，已放弃",
                       "text": "".join(sent_parts), "status": session.status.value,
                       "session_id": session.session_id}
                return

            if session.status is Status.CANCELLED:
                yield {"type": "cancelled", "text": "".join(sent_parts),
                       "status": session.status.value, "session_id": session.session_id}
                return

            # ---- 不重试：断流 / 总超时 → 收尾，交由 _finalize_session 去 drain ----
            #   断流：用户已不在，重试无意义 → 后台跑完缓存，等他回来
            #   总超时：预算已耗尽，重试还是超时 → 后台跑完缓存
            if session.status in (Status.BROKEN, Status.TOTAL_TIMEOUT):
                yield {"type": "partial", "text": "".join(sent_parts),
                       "reason": "断流" if session.status is Status.BROKEN else "总时长超时",
                       "status": session.status.value, "session_id": session.session_id}
                return

            # ---- 可重试：上游异常 / 卡死 ----
            if session.status in (Status.UPSTREAM_ERROR, Status.IDLE_TIMEOUT):
                # 剩余预算不够了就别折腾
                if time.time() - start_time > self.total_budget:
                    yield {"type": "partial", "text": "".join(sent_parts),
                           "reason": "预算已耗尽，放弃重试", "status": session.status.value,
                           "session_id": session.session_id}
                    return
                if attempt_number > self.max_retries:
                    yield {"type": "partial", "text": "".join(sent_parts),
                           "reason": "重试已耗尽", "status": session.status.value,
                           "session_id": session.session_id}
                    return
                if self._should_give_up_retry(sent_parts):
                    yield {"type": "partial", "text": "".join(sent_parts),
                           "reason": "已发出大半，不再折腾用户", "status": session.status.value,
                           "session_id": session.session_id}
                    return
                # 指数退避 + 随机抖动：0.3s → 0.6s → 1.2s ...
                retry_delay = self.base_delay * (2 ** (attempt_number - 1)) * (0.5 + random.random() / 2)
                yield {"type": "retry", "attempt": attempt_number, "delay": round(retry_delay, 2),
                       "sent": len(sent_parts), "session_id": session.session_id}
                await asyncio.sleep(retry_delay)
                continue

            # 兜底：理论上走不到这里，仍给出 partial 收尾
            yield {"type": "partial", "text": "".join(sent_parts),
                   "reason": session.status.value, "status": session.status.value,
                   "session_id": session.session_id}
            return

    def _should_give_up_retry(self, sent_parts: list[str]) -> bool:
        """已生成的内容达到放弃比例时，不再重试（避免折腾用户）。

        输入：sent_parts 已经交付的文字片段列表
        输出：True = 放弃重试
        """
        if not self.expected_total:
            return False  # 不知道总长度，算不出比例，一律继续重试
        return len(sent_parts) / max(self.expected_total, 1) >= self.abandon_ratio

    async def _close_stream_if_needed(self, answer_stream, session: Session) -> None:
        """需要的时候立刻关掉上游生成器，别再烧钱。

        关掉的场景：用户取消 / 上游出错 / 卡死——这三种要么结束、要么重试，
        旧生成器不关的话（尤其是线程桥接的实现）会继续在后台跑，白白消耗 token。
        断流和总超时故意不关：_finalize_session 会对它们做后台 drain
        （跑完并缓存，用户回来「续写」可秒回）。
        """
        if session.status in (Status.CANCELLED, Status.UPSTREAM_ERROR, Status.IDLE_TIMEOUT):
            try:
                await answer_stream.aclose()
            except Exception:
                pass  # 关闭失败无所谓，反正不再使用它

    # ---------------- 统一收尾 ----------------
    def _finalize_session(self, session_id: str, session: Session, stream_holder: dict) -> None:
        """会话结束（任何原因）的统一收尾：保存记录 → 决策上游生成器去留。

        输入：
            session_id     会话 ID
            session        会话记录（text / status 等已就绪）
            stream_holder  装着当前上游生成器的容器
        输出：无（副作用：落库、掐断上游，或让 drain 在后台跑完）
        """
        # ① 保存运行记录（幂等：可能被多次触发）
        if self.on_persist:
            try:
                self.on_persist(session_id, session.text, session.status, {
                    "attempts": session.attempts,
                    "duration_ms": session.duration_ms,
                    "errors": session.errors})
            except Exception:
                pass  # 落库失败不影响主流程

        # ② 决策上游：用户不想要 → 掐断；还想要 → 后台 drain
        answer_stream = stream_holder.get("stream")
        if answer_stream is None:
            return
        if session.status is Status.CANCELLED:
            self._spawn_background_task(self._close_stream_safely(answer_stream))
        elif self.drain_on_break and session.status in (
                Status.BROKEN, Status.IDLE_TIMEOUT, Status.TOTAL_TIMEOUT):
            self._spawn_background_task(
                self._drain_remaining_stream(session_id, answer_stream, session))

    async def _drain_remaining_stream(self, session_id: str, answer_stream, session: Session) -> None:
        """断流/超时后，在后台把上游生成器跑完并缓存结果。

        用户当时已不在（断流），或生成被暂停（超时），但模型可能还在出字，
        直接掐断会浪费已付的费用。这里在后台跑完、存进 session.text，
        用户回来点「继续生成」时 resume() 就能秒回。
        """
        remaining_parts: list[str] = []
        try:
            async for text_piece in answer_stream:
                remaining_parts.append(text_piece)
        except Exception:
            pass  # 后台 drain 失败不致命，保留已收到的部分
        finally:
            if remaining_parts:
                session.text = session.text + "".join(remaining_parts)
                session.status = Status.DRAINED
                if self.on_persist:
                    try:
                        self.on_persist(session_id, session.text, session.status,
                                        {"drained": len(remaining_parts)})
                    except Exception:
                        pass

    async def _close_stream_safely(self, answer_stream) -> None:
        """安全关闭一个异步生成器（忽略一切关闭错误）。"""
        try:
            await answer_stream.aclose()
        except Exception:
            pass  # 关闭失败无所谓，反正不再使用它

    def _spawn_background_task(self, coroutine) -> None:
        """把一个协程丢到后台运行，并保留引用防止被回收。

        为什么必须丢后台：_finalize_session 可能是在「取消态」下被调用（finally 块），
        此时不能 await 慢操作，只能创建 asyncio 任务异步执行。
        """
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ---------------- 取消 / 续写 ----------------
    def cancel(self, session_id: str, reason: str = "user_abort") -> None:
        """按会话 ID 标记取消。

        注意：真正让生成停下来的，是外部持有的 CancelToken 被置位；
        这里只是同步更新会话记录，方便日志排查，不主动掐上游。
        """
        session = self.sessions.get(session_id)
        if session:
            session.status = Status.CANCELLED
            session.metadata["cancel_reason"] = reason

    async def resume(self, session_id: str, factory: StreamFactory) -> dict:
        """用户点「继续生成」：已缓存则秒回，没跑完则接着往下跑。

        输入：
            session_id  要续写的会话 ID
            factory     生成器工厂（用于还没跑完的情况，带着已有文字继续）
        输出：
            字典 { text: 完整文字, status: 状态, session_id, from_cache: 是否来自缓存 }
        """
        session = self.sessions.get(session_id)
        if session is None:
            return {"error": "session not found", "session_id": session_id}

        # 之前后台 drain 已跑完（或正常完成）→ 直接返回缓存结果
        if session.status in (Status.DRAINED, Status.DONE):
            return {"text": session.text, "status": session.status.value,
                    "session_id": session_id, "from_cache": True}

        # 还没跑完 → 带着已有文字继续生成
        remaining_parts: list[str] = []
        async for text_piece in factory(session.text):
            remaining_parts.append(text_piece)
        session.text += "".join(remaining_parts)
        session.status = Status.DONE
        return {"text": session.text, "status": session.status.value,
                "session_id": session_id, "from_cache": False}

    # ---------------- SSE 编码 ----------------
    @staticmethod
    def to_sse(event: dict) -> str:
        """把一个事件 dict 编码成 SSE 文本行（形如 data: {...}\n\n）。"""
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"