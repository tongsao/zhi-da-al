# -*- coding: utf-8 -*-
"""模块A(剩余)/B/E 一次性执行：不涉及锁定的用例"""
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

# admin 登录
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "234567"}, timeout=10)
admin_token = r.json()["data"]["token"]
out.append({"用例": "登录admin", "status": r.status_code, "resp": r.json()})

# 业务员登录（sales01 / 123456，must_change_password=true）
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "sales01", "password": "123456"}, timeout=10)
sj = r.json()
sales_token = sj["data"]["token"] if sj.get("code") == "0" else None
out.append({"用例": "登录sales01", "status": r.status_code, "resp": sj})

# ===== TC-B-02 强制改密状态访问业务接口被拒（4031）=====
call("TC-B-02 must_change访问业务接口", "GET", "/api/v1/documents", token=sales_token)

# ===== TC-B-03 强制改密状态可访问改密与 me =====
call("TC-B-03 改密接口(合法入参)", "POST", "/api/v1/auth/change-password", token=sales_token,
     body={"old_password": "123456", "new_password": "Sales12345"})
# me 在改密前的 must_change 状态下（上面改密已成功，用新登录态验证）
call("TC-B-03 me接口", "GET", "/api/v1/auth/me", token=sales_token)

# ===== TC-B-05 改密后旧 token 失效 =====
# 用 sales_token（改密前签发）调用 me → 应 401
call("TC-B-05 改密后旧token失效", "GET", "/api/v1/auth/me", token=sales_token)

# 用新密码重新登录
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "sales01", "password": "Sales12345"}, timeout=10)
sj = r.json()
sales2 = sj["data"]["token"] if sj.get("code") == "0" else None
out.append({"用例": "TC-B-05 新密码登录", "status": r.status_code, "resp": sj})

# 旧密码登录应失败
call("TC-B-05 旧密码登录应失败", "POST", "/api/v1/auth/login", body={"username": "sales01", "password": "123456"})

# ===== TC-B-07 改密完成后业务功能恢复正常 =====
call("TC-B-07 改密后业务接口", "GET", "/api/v1/documents", token=sales2)
call("TC-B-07 me返回must_change=false", "GET", "/api/v1/auth/me", token=sales2)

# ===== TC-B-06 弱密码被拒（用一个临时新建账号测）=====
call("TC-C-01b 创建弱密测试账号", "POST", "/api/v1/users", token=admin_token,
     body={"username": "weak01", "display_name": "弱密测试", "password": "123456", "role": "user"})
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "weak01", "password": "123456"}, timeout=10)
wk = r.json()
weak_token = wk["data"]["token"] if wk.get("code") == "0" else None
out.append({"用例": "弱密账号登录", "status": r.status_code, "resp": wk})

# 三种弱密码
call("TC-B-06 弱密码-不足8位", "POST", "/api/v1/auth/change-password", token=weak_token,
     body={"old_password": "123456", "new_password": "Ab1"})
call("TC-B-06 弱密码-纯字母", "POST", "/api/v1/auth/change-password", token=weak_token,
     body={"old_password": "123456", "new_password": "abcdefgh"})
call("TC-B-06 弱密码-纯数字", "POST", "/api/v1/auth/change-password", token=weak_token,
     body={"old_password": "123456", "new_password": "12345678"})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
