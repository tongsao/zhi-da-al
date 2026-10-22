# -*- coding: utf-8 -*-
"""模块D密钥(带白名单)/E准入 一次性执行"""
import json
import requests

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
            j = r.text
        out.append({"用例": name, "method": method, "path": path, "status": r.status_code, "resp": j})
    except Exception as e:
        out.append({"用例": name, "method": method, "path": path, "status": "ERR", "resp": str(e)})

r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "234567"}, timeout=10)
admin_token = r.json()["data"]["token"]

# ===== 模块D：带 IP 白名单创建密钥 =====
r = requests.post(BASE + "/api/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"key_name": "test-key-1", "ip_whitelist": ["127.0.0.1", "::1"], "expires_at": None}, timeout=15)
rj = r.json()
out.append({"用例": "TC-D-01 创建密钥(白名单)", "status": r.status_code, "resp": rj})
api_key_plain = rj.get("data", {}).get("api_key") if rj.get("code") == "0" else None

# TC-D-02 密钥列表（应含1条）
call("TC-D-02 密钥列表", "GET", "/api/v1/api-keys", token=admin_token)

if api_key_plain:
    # ===== 模块E：准入（key 维度）=====
    # TC-E-02 有效密钥调用 user_or_key 接口（qa/chat GET history 或 documents）
    call("TC-E-02 密钥调用user_or_key", "GET", "/api/v1/documents", api_key=api_key_plain)
    # TC-E-03 无效密钥
    call("TC-E-03 无效密钥", "GET", "/api/v1/documents", api_key="zd_invalid_key_123")
    # TC-E-01 无凭证访问需鉴权接口
    call("TC-E-01 无凭证", "GET", "/api/v1/documents")
    # TC-E-06 密钥访问 admin_only 接口被拒
    call("TC-E-06 密钥访问admin接口", "GET", "/api/v1/users", api_key=api_key_plain)
    # TC-E-04 admin 访问 admin_only 通过
    call("TC-E-04 admin访问users", "GET", "/api/v1/users", token=admin_token)
    # TC-E-05 key_only 接口：无凭证/带JWT 都不可达（用 eval_trigger 路径模拟——需确认，改用一个已知 key_only 接口）
    # 该接口 /api/v1/eval/gen/run 是 POST key_only，用无凭证测试
    call("TC-E-05 无凭证访问key_only", "POST", "/api/v1/eval/gen/run", params={"indexes": "0"})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))