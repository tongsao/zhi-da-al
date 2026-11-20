"""工具调用异常兜底：失败后让模型修正参数并重试，最终失败则交回模型告知用户。

放在 middleware 最外层，只处理「工具真正抛异常」的情况；
工具调用次数上限、审批等策略仍由各自的中间件负责。
"""
import json
import logging

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.initChatModel import getEasyMode
from observability import trace_config
from prompts import get_prompt

logger = logging.getLogger("tools.tool_recovery")

MAX_REPAIRS = 2  # 模型最多修 2 次，加上首次执行共 3 次尝试

_REPAIR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("toolRepair")),
    (
        "human",
        "工具名：{tool_name}\n参数结构：{schema}\n原始参数：{args}\n错误信息：{error}",
    ),
])


def _repair_args(request, error):
    """让轻量模型根据错误重写工具参数；无法解析出 JSON 对象时返回 None。"""
    tool = request.tool
    schema = getattr(tool, "args", None) or {}
    try:
        raw = (_REPAIR_PROMPT | getEasyMode().bind(temperature=0) | StrOutputParser()).invoke({
            "tool_name": request.tool_call["name"],
            "schema": json.dumps(schema, ensure_ascii=False),
            "args": json.dumps(request.tool_call.get("args", {}), ensure_ascii=False),
            "error": f"{type(error).__name__}: {error}",
        }, config=trace_config(tags=["tool-repair"], trace_name="tool-repair"))
    except Exception:
        logger.warning("工具参数修复模型调用失败", exc_info=True)
        return None

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        fixed_args = json.loads(text)
    except json.JSONDecodeError:
        return None
    return fixed_args if isinstance(fixed_args, dict) else None


class ToolErrorRecoveryMiddleware(AgentMiddleware):
    """wrap_tool_call：捕获工具异常 → 模型修参重试 → 仍失败则返回失败 ToolMessage。"""

    def wrap_tool_call(self, request, handler):
        tool_name = request.tool_call["name"]
        last_error = None
        attempts = 0

        for attempt in range(MAX_REPAIRS + 1):
            try:
                return handler(request)
            except Exception as error:
                attempts += 1
                last_error = error
                if attempt >= MAX_REPAIRS:
                    break
                fixed_args = _repair_args(request, error)
                # 模型没修出有效参数、或修完与原来一样，就没必要再试
                if fixed_args is None or fixed_args == request.tool_call.get("args"):
                    break
                logger.warning(
                    "工具 %s 第 %s 次调用失败，按模型修复结果重试：%s", tool_name, attempts, error
                )
                request = request.override(
                    tool_call={**request.tool_call, "args": fixed_args}
                )

        message = (
            f"工具调用失败：{tool_name} 已尝试 {attempts} 次仍未成功。"
            f"最后一次错误：{type(last_error).__name__}: {last_error}。\n"
            "请不要再调用该工具，直接如实告知用户：工具调用失败，请稍后重试。"
        )
        logger.error("工具 %s 最终调用失败：%s", tool_name, last_error)
        return ToolMessage(
            content=message,
            tool_call_id=request.tool_call["id"],
            name=tool_name,
            status="error",
        )
