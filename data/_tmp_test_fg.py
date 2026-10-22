# -*- coding: utf-8 -*-
"""TC-F 限流测试（qa组 IP桶 10/min）、TC-G 审计查询"""
import json
import requests
import time

BASE = "http://127.0.0.1:8000"
out = []

def call(name, method, path, token=None, body=None, params=None, api_key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["X-Api-Key"] = api_key
    try:
        r = requests.request(method, BASE + path, headers=headers, json=body, params=params, timeout=15)
        try:
            j = r.json()
        except Exception:
            j = r.text[:120]
        out.append({"用例": name, "method": method, "path": path, "status": r.status_code, "resp": j})
    except Exception as e:
        out.append({"用例": name, "method": method, "path": path, "status": "ERR", "resp": str(e)})

r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "234567"}, timeout=10)
admin_token = r.json()["data"]["token"]

# ===== TC-F-01：qa组 IP桶 10/min，携带凭证连续调用 11 次 =====
# 用 GET /api/v1/qa/chat/conversation_id（qa 组，无模型副作用）
H = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
statuses = []
for i in range(12):
    rr = requests.get(BASE + "/api/v1/qa/chat/conversation_id", headers=H, timeout=15)
    try:
        body = rr.json()
        c = body.get("code")
    except Exception:
        c = "?"
    statuses.append((rr.status_code, c))
out.append({"用例": "TC-F-01 qa组连续12次调用", "状态序列": statuses})
# 预期：前 10 次 200 或近 200，第 11 次起 429/4290（IP 桶 10.min 先于 user 桶 30/min 命中）
# 注意 admin 属于 user 维度 30/min，但 IP 桶仅 10，故第 11 次触发 IP 4290

# 验证 IP 桶拦截后携带凭证也返回 4290
call("TC-F-01b 超限后仍429", "GET", "/api/v1/qa/chat/conversation_id", token=admin_token)

# ===== TC-G 审计查询（避免触发更多限流，间隔等待）=====
time.sleep(62)  # 等待桶窗口重置(60s)，避免后续接口被 IP 桶误伤
call("TC-G-01 审计列表", "GET", "/api/v1/audit", token=admin_token, params={"page": 1, "page_size": 5})
call("TC-G-02 按caller_type=user筛选", "GET", "/api/v1/audit", token=admin_token, params={"caller_type": "user", "page_size": 5})
call("TC-G-03 按path筛选/auth/login", "GET", "/api/v1/audit", token=admin_token, params={"path": "/auth/login", "page_size": 5})
call("TC-G-04 按status=unauthorized筛选", "GET", "/api/v1/audit", token=admin_token, params={"status": "unauthorized", "page_size": 5})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))