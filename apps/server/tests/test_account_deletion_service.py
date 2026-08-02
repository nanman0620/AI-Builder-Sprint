"""account_deletion_service.delete_account 순수 로직 테스트. 이 저장소의 다른 서비스 테스트와
동일하게 실제 Postgres에 연결하지 않는 fake DB 세션을 쓴다 — RESTRICT 제약·CASCADE 자체는
자동 테스트로 검증할 수 없고(SQLite로 user_profiles 테이블을 만들어보면 `CHECK (btrim(...))`
등 Postgres 전용 함수 때문에 즉시 실패한다), 실제 Supabase 수동 검증으로 대신한다.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Select
from sqlalchemy.sql.dml import Delete

from app.services import account_deletion_service, supabase_admin_client
from app.models.check_in import CheckIn
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.task import Task
from app.models.user_profile import UserProfile

TEST_USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()

# 기대하는 삭제 순서(§ 스키마 조사 결과). solar_request_items/solar_messages는
# solar_requests에 ON DELETE CASCADE라 별도 DELETE 문 없이 자동 삭제된다.
EXPECTED_DELETE_ORDER = [
    PlanBlock,
    SolarRequest,
    FixedSchedule,
    Task,
    CheckIn,
    PlanningCycle,
    UserProfile,
]


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeTransaction:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        if self._session.in_transaction:
            raise RuntimeError("중첩 트랜잭션이 시도됐다 — get_db()는 트랜잭션을 미리 열지 않는다.")
        self._session.in_transaction = True
        return self._session

    def __exit__(self, exc_type, exc, tb):
        self._session.in_transaction = False
        if exc_type is None:
            self._session.commit_count += 1
        return False  # 예외를 그대로 전파(진짜 rollback처럼 이후 단계를 중단시킨다)


class FakeAccountDeletionDB:
    def __init__(self, *, profile=None, fail_at_model: type | None = None):
        self.in_transaction = False
        self.commit_count = 0
        self._profile = profile
        self._fail_at_model = fail_at_model
        # (tablename, user_id) 순서 기록 — 순서·스코프 검증에 쓴다.
        self.delete_calls: list[tuple[str, uuid.UUID]] = []

    def begin(self):
        return _FakeTransaction(self)

    def execute(self, stmt):
        if isinstance(stmt, Select):
            return _FakeResult([self._profile] if self._profile is not None else [])
        if isinstance(stmt, Delete):
            model = _model_for_table(stmt.table.name)
            if model is self._fail_at_model:
                raise RuntimeError(f"{model.__name__} 삭제 중 임의 실패(테스트)")
            params = stmt.compile().params
            (user_id_value,) = params.values()
            self.delete_calls.append((stmt.table.name, user_id_value))
            return None
        raise AssertionError(f"예상하지 못한 statement: {stmt!r}")


_TABLENAME_TO_MODEL = {model.__tablename__: model for model in EXPECTED_DELETE_ORDER}


def _model_for_table(tablename: str) -> type:
    return _TABLENAME_TO_MODEL[tablename]


@pytest.fixture(autouse=True)
def _supabase_config_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")


@pytest.fixture
def mock_delete_auth_user(monkeypatch):
    mock = MagicMock(return_value=None)
    monkeypatch.setattr(supabase_admin_client, "delete_auth_user", mock)
    return mock


def test_deletes_all_tables_in_fk_safe_order_and_scopes_to_user_id(mock_delete_auth_user):
    profile = UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)
    db = FakeAccountDeletionDB(profile=profile)

    account_deletion_service.delete_account(db, TEST_USER_ID)

    actual_order = [_model_for_table(tablename) for tablename, _ in db.delete_calls]
    assert actual_order == EXPECTED_DELETE_ORDER
    assert all(user_id == TEST_USER_ID for _, user_id in db.delete_calls)
    assert db.commit_count == 1
    mock_delete_auth_user.assert_called_once_with(TEST_USER_ID)


def test_retry_without_profile_skips_db_deletes_and_still_deletes_auth_user(mock_delete_auth_user):
    """1차 호출에서 DB는 성공, Auth만 실패한 뒤 재시도하는 상황: user_profiles가 이미 없으므로
    DB 삭제는 전부 건너뛰고 Auth 삭제만 다시 시도해도 정상 종료돼야 한다."""
    db = FakeAccountDeletionDB(profile=None)

    account_deletion_service.delete_account(db, TEST_USER_ID)

    assert db.delete_calls == []
    assert db.commit_count == 1
    mock_delete_auth_user.assert_called_once_with(TEST_USER_ID)


def test_exception_mid_transaction_stops_later_deletes_and_auth_call(mock_delete_auth_user):
    profile = UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)
    # SolarRequest(순서상 2번째)에서 실패 — PlanBlock까지만 기록되고 이후 단계는 실행되지 않아야 한다.
    db = FakeAccountDeletionDB(profile=profile, fail_at_model=SolarRequest)

    with pytest.raises(RuntimeError, match="SolarRequest 삭제 중"):
        account_deletion_service.delete_account(db, TEST_USER_ID)

    assert [t for t, _ in db.delete_calls] == [PlanBlock.__tablename__]
    assert db.commit_count == 0
    mock_delete_auth_user.assert_not_called()


def test_missing_supabase_url_prevents_any_db_delete(monkeypatch, mock_delete_auth_user):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    profile = UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)
    db = FakeAccountDeletionDB(profile=profile)

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        account_deletion_service.delete_account(db, TEST_USER_ID)

    assert db.delete_calls == []
    assert db.commit_count == 0
    mock_delete_auth_user.assert_not_called()


def test_missing_service_role_key_prevents_any_db_delete(monkeypatch, mock_delete_auth_user):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    profile = UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)
    db = FakeAccountDeletionDB(profile=profile)

    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"):
        account_deletion_service.delete_account(db, TEST_USER_ID)

    assert db.delete_calls == []
    assert db.commit_count == 0
    mock_delete_auth_user.assert_not_called()


def test_auth_deletion_failure_raises_api_error_after_db_already_committed(mock_delete_auth_user):
    profile = UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)
    db = FakeAccountDeletionDB(profile=profile)
    mock_delete_auth_user.side_effect = RuntimeError("Supabase Auth 삭제가 실패했다: 500")

    from app.core.errors import ApiError

    with pytest.raises(ApiError) as exc_info:
        account_deletion_service.delete_account(db, TEST_USER_ID)

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "ACCOUNT_AUTH_DELETION_FAILED"
    # DB 쪽은 이미 커밋 완료된 상태라야 한다(Auth 실패와 무관하게 데이터는 지워짐).
    assert db.commit_count == 1
    assert len(db.delete_calls) == len(EXPECTED_DELETE_ORDER)
