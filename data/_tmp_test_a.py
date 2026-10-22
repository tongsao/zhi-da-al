# -*- coding: utf-8 -*-
"""模块A登录用例 + 模块C创建用户前置 一次性执行"""
import json
import requests

BASE = "http://127.0.0.1:8000"
out = []

def call(name, method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.request(method, BASE + path, headers=headers, json=body, timeout=10)
        txt = r.text
        try:
            j = r.json()
        except Exception:
            j = txt
        out.append({"用例": name, "method": method, "path": path, "status": r.status_code, "resp": j})
    except Exception as e:
        out.append({"用例": name, "method": method, "path": path, "status": "ERR", "resp": str(e)})

# 0. 登录 admin 拿 token
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "234567"}, timeout=10)
admin_token = r.json()["data"]["token"]
out.append({"用例": "TC-A-01(环境状态)", "method": "POST", "path": "/api/v1/auth/login", "status": r.status_code,
            "resp": {"must_change_password": r.json().get("data", {}).get("user", {}).get("must_change_password")}})

# TC-A-02 前置：创建业务员 sales01（TC-C-01）
call("TC-C-01 创建业务员", "POST", "/api/v1/users", token=admin_token,
     body={"username": "sales01", "display_name": "销售一", "password": "123456", "role": "user"})

# TC-A-02 业务员正确密码登录
call("TC-A-02 业务员登录成功", "POST", "/api/v1/auth/login", body={"username": "sales01", "password": "123456"})

# TC-A-03 密码错误
call("TC-A-03 密码错误统一提示", "POST", "/api/v1/auth/login", body={"username": "sales01", "password": "wrong123"})

# TC-A-04 账号不存在
call("TC-A-04 账号不存在", "POST", "/api/v1/auth/login", body={"username": "no_such_user", "password": "anypass"})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
