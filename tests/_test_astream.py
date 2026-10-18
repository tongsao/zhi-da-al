"""验证 agent 异步流式：astream_events 能否逐 token 穿透到 graphAnswer 内部生成节点。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage

from tools.agent_tools import getChatAgent
from service.chatService import deleteHistoryMessage


async def main():
    CONV = 980003
    deleteHistoryMessage(str(CONV))

    agent = getChatAgent()
    config = {"configurable": {"thread_id": str(CONV)}}
    inputs = {
        "messages": [HumanMessage(content="证券公司董事的每届任期是多少年？")],
        "conversation_id": CONV,
        "top_k": 6,
    }

    events = []
    total_chars = 0
    async for event in agent.astream_events(inputs, config=config, version="v2"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            if isinstance(chunk, str) and chunk:
                total_chars += len(chunk)
        elif kind in ("on_tool_start", "on_tool_end"):
            events.append(f"{kind}:{event['name']}")

    print("统计:")
    print("  流式字符总数:", total_chars)
    print("  工具事件:", events)
    print("  结论:", "最终答案 token 是否有流出:", total_chars > 0)

    deleteHistoryMessage(str(CONV))


asyncio.run(main())