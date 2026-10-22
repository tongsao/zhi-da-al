# -*- coding: utf-8 -*-
"""模块D剩余(轮换/停用/到期) + 模块E key_only正确接口(ai-check) """
import json, datetime
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

# 复用已创建的密钥 id=4（test-key-1）。创建新密钥用于轮换测试
r = requests.post(BASE + "/api/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"key_name": "rotate-key", "ip_whitelist": ["127.0.0.1"], "expires_at": None}, timeout=15)
rj = r.json()
old_key = rj.get("data", {}).get("api_key")
new_id = rj.get("data", {}).get("id")
out.append({"用例": "TC-D-01 创建rotate-key", "status": r.status_code, "resp": rj})

# TC-D-03 轮换：旧密钥立即失效，新密钥生效
call("TC-D-03 轮换后旧密钥失效", "GET", "/api/v1/documents", api_key=old_key)
r = requests.post(BASE + f"/api/v1/api-keys/{new_id}/rotate", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
rr = r.json()
new_key = rr.get("data", {}).get("api_key")
out.append({"用例": "TC-D-03 轮换返回新明文", "status": r.status_code, "resp": rr})
call("TC-D-03 轮换后新密钥生效", "GET", "/api/v1/documents", api_key=new_key)

# TC-D-04 停用密钥：is_active=0 → 调用被拒
call("TC-D-05 停用rotate-key", "PATCH", f"/api/v1/api-keys/{new_id}", token=admin_token, body={"is_active": 0})
call("TC-D-05 停用后新密钥失效", "GET", "/api/v1/documents", api_key=new_key)

# TC-D-07 密钥到期：创建一个 10秒内过期 的密钥
r = requests.post(BASE + "/api/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"key_name": "exp-key", "ip_whitelist": ["127.0.0.1"], "expires_at": (datetime.datetime.now() + datetime.timedelta(seconds=10)).isoformat()}, timeout=15)
rj = r.json()
if rj.get("code") == "0":
    exp_key = rj.get("data", {}).get("api_key")
    exp_id = rj.get("data", {}).get("id")
    call("TC-D-07 未到期前调用", "GET", "/api/v1/documents", api_key=exp_key)
    import time as _t; _t.sleep(11)
    call("TC-D-07 到期后调用", "GET", "/api/v1/documents", api_key=exp_key)
else:
    out.append({"用例": "TC-D-07 创建到期密钥失败", "status": r.status_code, "resp": rj})

# ===== 模块E：key_only 正确接口（ai-check）=====
call("TC-E-05 key_only带JWT被拒", "POST", "/api/v1/ai-check/projects", token=admin_token,
     body={"project_name": "test"})
call("TC-E-05 key_only无凭证被拒", "POST", "/api/v1/ai-check/projects")

# 用有效密钥调用 ai-check（应通过准入进入业务）
r = requests.post(BASE + "/api/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"key_name": "ai-check-key", "ip_whitelist": ["127.0.0.1"], "expires_at": None}, timeout=15)
rj = r.json()
if rj.get("code") == "0":
    aic_key = rj.get("data", {}).get("api_key")
    call("TC-E-05 key_only有效密钥调用", "POST", "/api/v1/ai-check/projects", api_key=aic_key,
         body={"project_name": "test"})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))