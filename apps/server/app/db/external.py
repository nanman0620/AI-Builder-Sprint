from sqlalchemy import Column, Table
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

# Supabase가 관리하는 외부 테이블. FK 참조 해석용 최소 stub이며
# Alembic 생성·수정 대상에서 제외한다 (alembic/env.py의 include_object 참고).
auth_users = Table(
    "users",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    schema="auth",
)
