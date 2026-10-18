"""临时验证脚本：真实走一遍流式链路，检查 delta 推送与中途停止。

用法：cd 项目根 && python tests/_test_stream_stop.py <mode>
  mode=stream  只验证 SSE 正常流式（前几块后自行断开）
  mode=stop    流式中途调用 /chat/stop，验证掐断
"""
import json
import sys
import threading
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
SID = str(int(time.time() * 1000))


def call_stop():
    time.sleep(3)
    req = urllib.request.Request(
        f"{BASE}/api/v1/qa/chat/stop?conversation_id={SID}", method="POST")
    with urllib.request.urlopen(req) as r:
        print(f"\n[stop] HTTP {r.status}: {r.read().decode()}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "stream"
    if mode == "stop":
        threading.Thread(target=call_stop, daemon=True).start()

    url = (f"{BASE}/api/v1/qa/chat?question={urllib.parse.quote('你好，请介绍一下自己')}&"
           f"conversation_id={SID}&top_k=6&stream=true")
    req = urllib.request.Request(url, method="POST")
    n_delta = 0
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=40) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                print(f"\n[done] 总耗时 {time.time() - t0:.1f}s, delta 块数 {n_delta}")
                return
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if "content" in ev:
                n_delta += 1
                if n_delta <= 3:
                    print(f"[delta] {ev['content']!r}")
            elif "error" in ev:
                print(f"\n[error] {ev['error']}")
                return
    print(f"\n[流结束] delta 块数 {n_delta}（未收到 [DONE]，可能是流被断开）")


if __name__ == "__main__":
    main()