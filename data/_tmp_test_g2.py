# -*- coding: utf-8 -*-
"""验证 401 被拒请求是否落审计 + 登录失败审计状态 + TC-G 剩余"""
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
            j = r.text[:200]
        out.append({"用例": name, "method": method, "path": path, "status": r.status_code, "resp": j})
    except Exception as e:
        out.append({"用例": name, "method": method, "path": path, "status": "ERR", "resp": str(e)})

r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "234567"}, timeout=10)
admin_token = r.json()["data"]["token"]

# 1. 制造一次无凭证 401 请求（Auth 直接拒绝）
call("制造401 无凭证访问documents", "GET", "/api/v1/documents")
# 制造一次无效密钥 401
call("制造401 无效密钥", "GET", "/api/v1/documents", api_key="zd_invalid_xxx")
# 制造一次越权 403（密钥访问 admin 接口）
call("制造403 密钥访问users", "GET", "/api/v1/users", api_key="zd_invalid_xxx")

# 2. 查询审计：anonymous + documents 是否有记录（验证 401 落审计？）
call("TC-G-06 查询anonymous+documents审计", "GET", "/api/v1/audit", token=admin_token,
     params={"caller_type": "anonymous", "path": "documents", "page_size": 20})
call("TC-G-06 查询login全部记录", "GET", "/api/v1/audit", token=admin_token,
     params={"path": "auth/login", "page_size": 100})

# 3. 查询审计中是否存在 401/403 状态的记录
call("TC-G-04 全部status分布检查(unauthorized)", "GET", "/api/v1/audit", token=admin_token,
     params={"status": "unauthorized", "page_size": 5})
call("TC-G-04 全部status分布检查(forbidden)", "GET", "/api/v1/audit", token=admin_token,
     params={"status": "forbidden", "page_size": 5})

print(json.dumps(out, ensure_ascii=False, indent=2, default=str))