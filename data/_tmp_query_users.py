from sqlalchemy import select
from model.initDataBase import db_session
from gateway.models import ZdUser

with db_session() as db:
    rows = db.execute(select(ZdUser)).scalars().all()
    for r in rows:
        print(r.id, r.username, r.display_name, r.role,
              'must=' + str(r.must_change_password), 'active=' + str(r.is_active),
              'failed=' + str(r.failed_attempts), 'locked=' + str(r.locked_until),
              'pwd=' + str(r.pwd_changed_at))