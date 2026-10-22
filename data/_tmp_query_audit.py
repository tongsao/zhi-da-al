from sqlalchemy import select, desc
from model.initDataBase import db_session
from gateway.models import ZdCallAudit

with db_session() as db:
    rows = db.execute(
        select(ZdCallAudit).order_by(desc(ZdCallAudit.id)).limit(25)
    ).scalars().all()
    for r in rows:
        print(r.id, r.created_at, r.caller_type, r.caller_id,
              r.method, r.path, r.status, r.status_code)