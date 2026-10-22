import datetime

from sqlalchemy import select

from model.initDataBase import db_session
from gateway.models import ZdUser
from gateway.security import hash_password

# 并发会话在 18:15:19 改过 admin 密码，导致密码未知。
# 重置为初始状态（123456 / must_change_password=1），复现 TC-I-03 首次强制改密。
with db_session() as db:
    u = db.execute(select(ZdUser).where(ZdUser.username == "admin")).scalars().first()
    u.password_hash = hash_password("123456")
    u.must_change_password = 1
    u.pwd_changed_at = datetime.datetime.now()
    u.failed_attempts = 0
    u.locked_until = None
    db.commit()
    print("admin reset ok, pwd_changed_at =", u.pwd_changed_at, "must =", u.must_change_password)