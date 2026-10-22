# 模型工厂：收敛现有模型初始化，统一持有 Langfuse 埋点、重试与降级装配。
# 模块级零 DB 操作；构建模型对象不发网络请求，仅装配 Runnable。
import logging

from langchain.chat_models import init_chat_model
from langfuse.langchain import CallbackHandler

from gateway import config
from llm_gateway.gate import CountingChatModel, CountingEmbeddingModel

logger = logging.getLogger("llm_gateway.providers")

langfuse_handler = CallbackHandler()


def _build_chat(model_name: str, temperature: float):
    inner = init_chat_model(
        model=f"openai:{model_name}",
        api_key=config.GOAI_API_KEY,
        base_url=config.GOAI_BASE_URL,
        temperature=temperature,
        timeout=180,
    )
    inner = inner.with_config({"callbacks": [langfuse_handler]})
    # 仅重试瞬时错误，业务 4xx 不重试；指数退避由 LangChain 内部处理
    inner = inner.with_retry(
        stop_after_attempt=3,
        retry_if_exception_type=(TimeoutError, OSError),
    )
    return inner


# ---- 单例（懒加载，首次 get 时才构建） ----
_chat = None
_rewrite = None
_embedding = None


def get_chat() -> CountingChatModel:
    """主生成模型 glm-5.3（temp=0.5），返回计数代理包装实例。"""
    global _chat
    if _chat is None:
        inner = _build_chat("glm-5.3", 0.5)
        if config.GATEWAY_MODEL_FALLBACK:
            inner = inner.with_fallbacks([_rewrite_inner()])
        _chat = CountingChatModel(inner, "chat")
    return _chat


def get_rewrite() -> CountingChatModel:
    """轻量/改写模型 glm-5.3-flash（temp=0.3），返回计数代理包装实例。"""
    global _rewrite
    if _rewrite is None:
        _rewrite = CountingChatModel(_rewrite_inner(), "rewrite")
    return _rewrite


def _rewrite_inner():
    return _build_chat("glm-5.3-flash", 0.3)


def get_embedding() -> CountingEmbeddingModel:
    """向量模型 DashScope text-embedding-v1（归一化），计数包装实例。"""
    global _embedding
    if _embedding is None:
        _embedding = CountingEmbeddingModel(
            model="text-embedding-v1",
            dashscope_api_key=config.QWEN_API_KEY,
        )
    return _embedding