# -*- coding: utf-8 -*-
"""重测TC-D-03轮换正确顺序 + TC-A-05/06登录锁定 + TC-A-03/04统一提示"""
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

# ===== TC-D-03 轮换（正确顺序）=====
r = requests.post(BASE + "/api/v1/api-keys", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"key_name": "rotate2", "ip_whitelist": ["127.0.0.1"], "expires_at": None}, timeout=15)
rj = r.json()
rid = rj["data"]["id"]
old2 = rj["data"]["api_key"]
call("TC-D-03 轮换前旧密钥有效", "GET", "/api/v1/documents", api_key=old2)
r = requests.post(BASE + f"/api/v1/api-keys/{rid}/rotate", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
rj2 = r.json()
new2 = rj2["data"]["api_key"]
out.append({"用例": "TC-D-03 轮换返回", "status": r.status_code, "resp": rj2})
call("TC-D-03 轮换后旧密钥失效", "GET", "/api/v1/documents", api_key=old2)
call("TC-D-03 轮换后新密钥生效", "GET", "/api/v1/documents", api_key=new2)
# 验证轮换后原密钥无法再次轮换（已是新hash，旧key调用业务接口被拒）

# ===== TC-A-03 密码错误统一提示（业务员改密后状态 sales01=Sales12345）=====
call("TC-A-03 密码错误", "POST", "/api/v1/auth/login", body={"username": "sales01", "password": "WrongPass00"})
# TC-A-04 账号不存在
call("TC-A-04 账号不存在", "POST", "/api/v1/auth/login", body={"username": "ghost_user_x", "password": "abc123"})
# 缓存的失败次数检查：sales01 已错2次（设阈值5，还差3次）

# ===== TC-A-05/06 登录锁定 =====
# 用专用账号 locktest01，避免污染业务员
r = requests.post(BASE + "/api/v1/users", headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                  json={"username": "locktest01", "display_name": "锁定测试", "password": "Lock12345", "role": "user"}, timeout=15)
out.append({"用例": "TC-A-05 创建locktest01", "status": r.status_code, "resp": r.json()})

# 连续 4 次错误密码（第5次应触发锁定）
for i in range(4):
    call(f"TC-A-05 第{i+1}次错误密码", "POST", "/api/v1/auth/login", body={"username": "locktest01", "password": "wrong"})
# 第5次错误 → 应返回锁定/统一提示
call("TC-A-05 第5次错误密码", "POST", "/api/v1/auth/login", body={"username": "locktest01", "password": "wrong"})
# 锁定后正确密码也失败
call("TC-A-06 锁定后正确密码仍失败", "POST", "/api/v1/auth/login", body={"username": "locktest01", "password": "Lock12345"})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))