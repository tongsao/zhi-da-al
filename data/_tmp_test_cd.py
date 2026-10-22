# -*- coding: utf-8 -*-
"""模块C用户管理 / D密钥管理 一次性执行（不含锁定时效用例）"""
import json
import requests

BASE = "http://127.0.0.1:8000"
out = []

def call(name, method, path, token=None, body=None, params=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
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
out.append({"用例": "登录admin", "status": r.status_code})

# ===== TC-C 用户管理 =====
# TC-C-01 创建用户：已建 sales01/weak01，跳过
# TC-C-02 创建用户-用户名重复
call("TC-C-02 用户名重复", "POST", "/api/v1/users", token=admin_token,
     body={"username": "sales01", "display_name": "重复", "password": "abcdef", "role": "user"})
# TC-C-02b 用户名过短(<2)
call("TC-C-02 用户名过短", "POST", "/api/v1/users", token=admin_token,
     body={"username": "a", "display_name": "短", "password": "abcdef", "role": "user"})
# TC-C-03 用户列表
call("TC-C-03 用户列表", "GET", "/api/v1/users", token=admin_token, params={"page": 1, "page_size": 10})
# TC-C-04 停用用户
call("TC-C-04 停用weak01", "PATCH", "/api/v1/users/11", token=admin_token, body={"is_active": 0})
# 停用后 weak01 登录应失败
call("TC-C-04 停用后登录失败", "POST", "/api/v1/auth/login", body={"username": "weak01", "password": "abcdef"})
# 恢复 weak01 并重置密码
call("TC-C-04 恢复weak01", "PATCH", "/api/v1/users/11", token=admin_token, body={"is_active": 1, "reset_password": "Wk12345!"})
# TC-C-05 重置密码后登录需强制改密
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "weak01", "password": "Wk12345!"}, timeout=10)
sj = r.json()
out.append({"用例": "TC-C-05 重置密码后登录", "status": r.status_code, "resp": sj})
weak_token = sj["data"]["token"] if sj.get("code") == "0" else None
if weak_token:
    call("TC-C-05 重置密码后业务被拒4031", "GET", "/api/v1/documents", token=weak_token)

# ===== TC-D 密钥管理 =====
# TC-D-01 创建密钥
call("TC-D-01 创建密钥", "POST", "/api/v1/api-keys", token=admin_token,
     body={"key_name": "test-key-1", "ip_whitelist": [], "expires_at": None})
# TC-D-02 密钥列表
call("TC-D-02 密钥列表", "GET", "/api/v1/api-keys", token=admin_token)

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))