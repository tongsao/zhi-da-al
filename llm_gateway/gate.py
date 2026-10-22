# 计数代理（P0 评审后方案）：包装原 ChatModel/Embedding，业务代码零改动。
# 职责：限额预检 -> 委托 -> 用量记录；重试/降级由 providers 装配在 inner 上。
# 模块级零 DB 操作；usage 全部走函数体。
from typing import Any, AsyncIterator, Iterator, Sequence

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.runnables import Runnable, RunnableSequence

from llm_gateway import usage


class ModelGatewayError(Exception):
    """模型层统一错误（网络/上游失败），业务层提示「模型服务暂不可用」。"""


# ==== 用量提取（openai 兼容）====
def _extract_tokens(msg: Any) -> tuple[int, int]:
    """从 AIMessage/AIMessageChunk 提取 (input, output)；优先 usage_metadata。"""
    meta = getattr(msg, "usage_metadata", None)
    if meta:
        return meta.get("input_tokens") or 0, meta.get("output_tokens") or 0
    resp_meta = getattr(msg, "response_metadata", None) or {}
    token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
    return token_usage.get("prompt_tokens") or 0, token_usage.get("completion_tokens") or 0


def extract_usage(resp: Any) -> tuple[int, int]:
    """提取单条消息或消息列表的用量累计。"""
    if isinstance(resp, list):
        if not resp:
            return 0, 0
        inps, outs = zip(*(_extract_tokens(r) for r in resp))
        return sum(inps), sum(outs)
    return _extract_tokens(resp)


def _estimate_input(input_: Any) -> int:
    """按调用入参估算本次输入 tokens（仅用于 precheck，精确值以响应 usage 为准）。"""
    if isinstance(input_, str):
        return max(1, len(input_) // 2)
    text = ""
    if isinstance(input_, (list, tuple)):
        for item in input_:
            content = getattr(item, "content", None)
            if isinstance(content, str):
                text += content
            elif isinstance(content, Sequence):
                text += "".join(str(c) for c in content)
            elif isinstance(content, dict):
                text += str(content.get("text", ""))
            elif isinstance(item, dict):
                text += str(item.get("content") or "")
    return max(1, len(text) // 2) if text else usage.context_input_estimate()


def _estimate_texts(texts: Sequence[str]) -> int:
    return sum(usage.estimate_tokens(t) for t in texts)


# ==== Chat 模型计数代理 ====
class CountingChatModel(Runnable):
    """与原 ChatModel Runnable 同接口；invoke/ainvoke/stream/astream/batch/abatch 统一计数。

    继承 Runnable 以便 langchain 的 coerce_to_runnable/`|` 链识别本包装为可运行对象。
    """

    def __init__(self, inner: Any, role: str):
        self.inner = inner
        self.role = role

    # ---- 接口变形：重新包装，保住计数外壳 ----
    def bind(self, **kwargs):
        return CountingChatModel(self.inner.bind(**kwargs), self.role)

    def bind_tools(self, tools, **kwargs):
        return CountingChatModel(self.inner.bind_tools(tools, **kwargs), self.role)

    def with_config(self, **kwargs):
        return CountingChatModel(self.inner.with_config(**kwargs), self.role)

    def with_retry(self, **kwargs):
        return CountingChatModel(self.inner.with_retry(**kwargs), self.role)

    def with_fallbacks(self, fallbacks, **kwargs):
        inners = [f.inner if isinstance(f, CountingChatModel) else f for f in fallbacks]
        return CountingChatModel(self.inner.with_fallbacks(inners, **kwargs), self.role)

    def __or__(self, other):
        # 保留 self 作为序列首元素，链式调用仍走计数外壳
        return RunnableSequence(self, other)

    # ---- 属性代理：model_name 等透传给 inner（穿透 RunnableBinding 的 bound 链）----
    def __getattr__(self, name):
        # 避免对双下划线/特殊属性递归
        if name.startswith("__"):
            raise AttributeError(name)
        node = self.inner
        seen = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            try:
                return getattr(node, name)
            except AttributeError:
                node = getattr(node, "bound", None)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # ---- 核心：预检 -> 委托 -> 记录 ----
    def _call(self, method: str, args, kwargs):
        if not usage.in_batch_exempt():
            input_ = args[0] if args else kwargs.get("input")
            usage.precheck(self.role, _estimate_input(input_))
        try:
            resp = getattr(self.inner, method)(*args, **kwargs)
        except Exception as e:
            raise ModelGatewayError(f"[{self.role}] 模型调用失败: {type(e).__name__}: {e}") from e
        usage.record(self.role, *extract_usage(resp))
        return resp

    # ---- 同步 ----
    def invoke(self, *args, **kwargs):
        return self._call("invoke", args, kwargs)

    def batch(self, inputs, *args, **kwargs):
        return self._call("batch", (inputs, *args), kwargs)

    def stream(self, *args, **kwargs):
        if not usage.in_batch_exempt():
            input_ = args[0] if args else kwargs.get("input")
            usage.precheck(self.role, _estimate_input(input_))
        return _CountingIterator(self.inner.stream(*args, **kwargs), self.role)

    # ---- 异步 ----
    async def ainvoke(self, *args, **kwargs):
        if not usage.in_batch_exempt():
            input_ = args[0] if args else kwargs.get("input")
            usage.precheck(self.role, _estimate_input(input_))
        try:
            resp = await self.inner.ainvoke(*args, **kwargs)
        except Exception as e:
            raise ModelGatewayError(f"[{self.role}] 模型调用失败: {type(e).__name__}: {e}") from e
        usage.record(self.role, *extract_usage(resp))
        return resp

    async def abatch(self, inputs, *args, **kwargs):
        if not usage.in_batch_exempt():
            usage.precheck(self.role, _estimate_input(inputs))
        resp = await self.inner.abatch(inputs, *args, **kwargs)
        usage.record(self.role, *extract_usage(resp))
        return resp

    async def astream(self, *args, **kwargs):
        if not usage.in_batch_exempt():
            input_ = args[0] if args else kwargs.get("input")
            usage.precheck(self.role, _estimate_input(input_))
        return _CountingAsyncIterator(self.inner.astream(*args, **kwargs), self.role)


class _CountingIterator:
    """流式：逐个透传 chunk，最后一个带 usage 的 chunk 落账。"""

    def __init__(self, inner_iter: Iterator, role: str):
        self._inner = inner_iter
        self._role = role
        self._pending: tuple[int, int] | None = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._inner)
        except StopIteration:
            usage.record(self._role, *(self._pending or (0, 0)))
            raise
        tokens = _extract_tokens(chunk)
        if tokens != (0, 0):
            self._pending = tokens
        return chunk


class _CountingAsyncIterator:
    def __init__(self, inner_iter: AsyncIterator, role: str):
        self._inner = inner_iter
        self._role = role
        self._pending: tuple[int, int] | None = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._inner.__anext__()
        except StopAsyncIteration:
            usage.record(self._role, *(self._pending or (0, 0)))
            raise
        tokens = _extract_tokens(chunk)
        if tokens != (0, 0):
            self._pending = tokens
        return chunk


# ==== Embedding 计数（继承式：业务子类继承即自动计数）====
class CountingEmbeddingModel(DashScopeEmbeddings):
    """在 DashScopeEmbeddings 之上加计数：embed_query/embed_documents 走 precheck+record。

    业务侧子类（NormalizeDashScopeEmbeddings）继承本类、保留归一化 override，
    调用 super().embed_* 时自然经过计数层，initRag.py 实例化处零改动。
    """

    role: str = "embedding"  # 声明为 Pydantic 字段，否则 self.role 赋值被拦截

    def __init__(self, *args, role: str = "embedding", **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role

    def embed_query(self, text: str):
        estimate = max(1, len(text) // 4)
        if not usage.in_batch_exempt():
            usage.precheck(self.role, estimate)
        result = super().embed_query(text)
        usage.record(self.role, estimate, 0)
        return result

    def embed_documents(self, texts: Sequence[str]):
        estimate = _estimate_texts(texts)
        if not usage.in_batch_exempt():
            usage.precheck(self.role, estimate)
        result = super().embed_documents(texts)
        usage.record(self.role, estimate, 0)
        return result