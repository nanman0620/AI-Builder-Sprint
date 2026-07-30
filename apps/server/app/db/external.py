from sqlalchemy import Column, Table, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

# Supabase가 관리하는 외부 테이블. FK 참조 및 SELECT 해석용 최소 stub이며
# Alembic 생성·수정 대상에서 제외한다 (alembic/env.py의 include_object 참고).
# email 컬럼 추가는 SQLAlchemy 참조 선언일 뿐 실제 DB schema나 migration을 변경하지 않는다.
auth_users = Table(
    "users",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", Text),
    schema="auth",
)
