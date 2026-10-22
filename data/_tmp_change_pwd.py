import requests

BASE = "http://127.0.0.1:8000"

# 1. 登录 admin（123456）
r = requests.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "123456"})
print("login:", r.status_code, r.text[:200])
token = r.json()["data"]["token"]
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# 2. 改密：不合规密码（无特殊字符）
r2 = requests.post(BASE + "/api/v1/auth/change-password", headers=H,
                   json={"old_password": "123456", "new_password": "Ab12345678"})
print("weak pwd:", r2.status_code, r2.text[:200])

# 3. 改密：合规密码
r3 = requests.post(BASE + "/api/v1/auth/change-password", headers=H,
                   json={"old_password": "123456", "new_password": "Fe123456a!"})
print("strong pwd:", r3.status_code, r3.text[:300])