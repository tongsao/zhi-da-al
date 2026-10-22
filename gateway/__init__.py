# 网关包：initGateway() 幂等初始化（建 admin、建表）。
# 模块级不做任何 DB 操作——建表/建 admin 全部收敛在 initGateway() 内，
# 避免 `from gateway import ...` 顶层 import 就触发 DB 建连拖垮启动。
import datetime

from sqlalchemy import select

from gateway import config, security
from gateway.models import ZdUser
from model.initDataBase import Base, db_session, engine


def _ensure_admin():
    """admin 账号不存在才创建；重复启动不重复建（按 username 存在性判断）。"""
    with db_session() as db:
        exists = db.execute(select(ZdUser).where(ZdUser.username == "admin")).scalars().first()
        if exists:
            return
        db.add(
            ZdUser(
                username="admin",
                password_hash=security.hash_password("123456"),
                display_name="系统管理员",
                role="admin",
                must_change_password=1,
                is_active=1,
                pwd_changed_at=datetime.datetime.now(),
            )
        )
        db.commit()


def initGateway():
    """网关幂等初始化：校验配置 → 建表 → 建 admin → 返回汇总 router 供 main.py include。"""
    config.validate()
    Base.metadata.create_all(engine)
    _ensure_admin()
    from gateway.routes import gateway_router  # 延迟导入：路由注册不碰 DB

    return gateway_router
