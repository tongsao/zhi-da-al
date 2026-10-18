"""验证同步 agent.stream(stream_mode='messages') 的结构：能否逐 token 穿透工具内部生成节点。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage

from tools.agent_tools import getChatAgent
from service.chatService import deleteHistoryMessage

CONV = 980004
deleteHistoryMessage(str(CONV))

agent = getChatAgent()
config = {"configurable": {"thread_id": str(CONV)}}
inputs = {
    "messages": [HumanMessage(content="证券公司董事的每届任期是多少年？")],
    "conversation_id": CONV,
    "top_k": 6,
}

text_streams = []  # (node, 累积文本前80字)
cur_chunks = []

for item in agent.stream(inputs, config=config, stream_mode="messages"):
    # item = (message_chunk, metadata) 二元组
    msg_chunk, metadata = item
    node = metadata.get("langgraph_node", "")
    text = msg_chunk.content if isinstance(msg_chunk.content, str) else ""
    tcs = getattr(msg_chunk, "tool_call_chunks", None) or []
    if text:
        cur_chunks.append((node, text, bool(tcs)))

print("\n消息节点分布（node, 是否toolcall, 累积前缀）:")
from collections import Counter
cnt = Counter()
merged = {}
for node, text, is_tc in cur_chunks:
    key = (node, is_tc)
    cnt[key] += 1
    merged.setdefault(key, "")
    merged[key] += text
for (node, is_tc), n in cnt.items():
    print(f"  node={node!r} toolcall={is_tc} chunks={n} 累积前80: {merged[(node,is_tc)][:80]!r}")

deleteHistoryMessage(str(CONV))