import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

import app.services.plan_management_service as plan_management_service_module
import app.services.solar_client as solar_client_module
from app.core.errors import ApiError
from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanCycleStatus,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.planning_cycle import PlanningCycle
from app.models.solar_message import SolarMessage
from app.models.solar_request import SolarRequest
from app.models.task import Task
from app.services import solar_request_service
from app.services.solar_client import SolarAnalysisItem, SolarAnalysisResult, SolarUnavailableError, UnresolvedLine

USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
FIXED_SCHEDULE_ID = uuid.uuid4()
NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def _make_request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.COLLECTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=None,
        executed_at=None,
        execution_attempt_count=0,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """execute() 1회 호출로 scalar_one_or_none() 결과를 돌려주는 최소 fake."""

    def __init__(self, value):
        self._value = value
        self.last_statement = None

    def execute(self, stmt):
        self.last_statement = stmt
        return _FakeResult(self._value)


# ---------------------------------------------------------------------------
# get_current_solar_request
# ---------------------------------------------------------------------------


def test_get_current_solar_request_query_conditions():
    fake_db = _FakeSession(None)

    solar_request_service.get_current_solar_request(fake_db, USER_ID)

    sql = str(fake_db.last_statement)
    assert "solar_requests.user_id" in sql
    assert "solar_requests.status IN" in sql
    assert "solar_requests.result_acknowledged_at IS NULL" in sql


def test_get_current_solar_request_returns_the_row_the_session_gives_back():
    request = _make_request(status=SolarRequestStatus.COLLECTING)
    fake_db = _FakeSession(request)

    result = solar_request_service.get_current_solar_request(fake_db, USER_ID)

    assert result is request


def test_get_current_solar_request_returns_none_when_no_row():
    fake_db = _FakeSession(None)

    result = solar_request_service.get_current_solar_request(fake_db, USER_ID)

    assert result is None


# ---------------------------------------------------------------------------
# resolve_current_request_screen_mode
# ---------------------------------------------------------------------------


def test_resolve_current_request_screen_mode_maps_each_in_progress_status():
    expected = {
        SolarRequestStatus.COLLECTING: solar_request_service.PlanManagementScreenMode.COLLECTING,
        SolarRequestStatus.CHANGE_CONFIRMATION: (
            solar_request_service.PlanManagementScreenMode.CHANGE_CONFIRMATION
        ),
        SolarRequestStatus.CHANGE_INPUT: (
            solar_request_service.PlanManagementScreenMode.CHANGE_INPUT
        ),
        SolarRequestStatus.FINAL_REVIEW: (
            solar_request_service.PlanManagementScreenMode.FINAL_REVIEW
        ),
        SolarRequestStatus.EXECUTING: solar_request_service.PlanManagementScreenMode.EXECUTING,
        SolarRequestStatus.FAILED: (
            solar_request_service.PlanManagementScreenMode.EXECUTION_FAILED
        ),
    }

    for status, screen_mode in expected.items():
        request = _make_request(status=status)
        assert solar_request_service.resolve_current_request_screen_mode(request) == screen_mode


@pytest.mark.parametrize(("decision", "label"), [("YES", "예"), ("NO", "아니요")])
def test_build_decision_history_entries_preserves_question_before_answer(decision, label):
    entries = solar_request_service._build_decision_history_entries(
        client_event_id="decision-event-id",
        decision=decision,
        decision_label=label,
        prompt_message="다른 선택형 질문인가요?",
    )

    assert [(entry["role"], entry["kind"], entry["content"]) for entry in entries] == [
        (SolarMessageRole.ASSISTANT, SolarMessageKind.QUESTION, "다른 선택형 질문인가요?"),
        (SolarMessageRole.USER, SolarMessageKind.DECISION, label),
    ]
    assert entries[0]["message_metadata"] == {
        "promptType": "CHANGE_CONFIRMATION",
        "decisionClientEventId": "decision-event-id",
    }
    assert entries[1]["message_metadata"] == {"decision": decision}


def test_resolve_current_request_screen_mode_maps_completed_to_execution_success():
    request = _make_request(
        status=SolarRequestStatus.COMPLETED,
        result_acknowledged_at=None,
        execution_started_at=datetime(2026, 7, 29, 14, 20, tzinfo=timezone.utc),
        executed_at=datetime(2026, 7, 29, 14, 20, 5, tzinfo=timezone.utc),
        execution_attempt_count=1,
        execution_result={},
    )

    result = solar_request_service.resolve_current_request_screen_mode(request)

    assert result == solar_request_service.PlanManagementScreenMode.EXECUTION_SUCCESS


# ---------------------------------------------------------------------------
# resolve_no_request_screen_mode
# ---------------------------------------------------------------------------


def test_resolve_no_request_screen_mode_with_active_cycle():
    result = solar_request_service.resolve_no_request_screen_mode(has_active_cycle=True)

    assert result == solar_request_service.PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY


def test_resolve_no_request_screen_mode_without_active_cycle():
    result = solar_request_service.resolve_no_request_screen_mode(has_active_cycle=False)

    assert result == solar_request_service.PlanManagementScreenMode.NEW_CYCLE_ENTRY


# ---------------------------------------------------------------------------
# get_owned_solar_request
# ---------------------------------------------------------------------------


def test_get_owned_solar_request_query_conditions():
    fake_db = _FakeSession(None)
    request_id = uuid.uuid4()

    with pytest.raises(ApiError):
        solar_request_service.get_owned_solar_request(fake_db, request_id, USER_ID)

    sql = str(fake_db.last_statement)
    assert "solar_requests.id" in sql
    assert "solar_requests.user_id" in sql


def test_get_owned_solar_request_returns_the_row():
    request = _make_request(status=SolarRequestStatus.COMPLETED, result_acknowledged_at=None)
    fake_db = _FakeSession(request)

    result = solar_request_service.get_owned_solar_request(fake_db, request.id, USER_ID)

    assert result is request


def test_get_owned_solar_request_raises_404_when_missing():
    fake_db = _FakeSession(None)

    with pytest.raises(ApiError) as exc_info:
        solar_request_service.get_owned_solar_request(fake_db, uuid.uuid4(), USER_ID)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "REQUEST_NOT_FOUND"


# ---------------------------------------------------------------------------
# create_solar_request — Issue #50. 오케스트레이션(호출 순서·트랜잭션 분기) 단위
# 테스트이며, 실제 PostgreSQL CHECK 제약·partial unique index를 검증하는 통합
# 테스트가 아니다(이 저장소 테스트 스위트는 네트워크·실DB를 쓰지 않는다).
# ---------------------------------------------------------------------------


def _make_cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        status=PlanCycleStatus.ACTIVE,
        activated_at=NOW,
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


def _make_task(**overrides):
    defaults = dict(
        id=TASK_ID,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        source_request_item_id=None,
        title="기존 과제",
        deadline_at=None,
        amount_text=None,
        amount_source=AmountSource.UNKNOWN,
        initial_minutes=120,
        estimated_minutes=120,
        estimated_minutes_source=EstimateSource.USER,
        remaining_minutes=120,
        status=TaskStatus.ACTIVE,
        deadline_warning_acknowledged_at=None,
        completed_at=None,
        cancelled_at=None,
    )
    defaults.update(overrides)
    return Task(**defaults)


def _make_fixed_schedule(**overrides):
    defaults = dict(
        id=FIXED_SCHEDULE_ID,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        source_request_item_id=None,
        title="기존 알바",
        start_at=datetime(2026, 7, 28, 17, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return FixedSchedule(**defaults)


def _create_item(**overrides):
    defaults = dict(
        entity_type="TASK",
        action="CREATE",
        target_entity_id=None,
        raw_line_text="원문",
        update_fields=[],
        normalized_payload={
            "title": "새 과제",
            "deadlineAt": None,
            "estimatedMinutes": 120,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": "UNKNOWN",
        },
        missing_fields=[],
        pending_question=None,
    )
    defaults.update(overrides)
    return SolarAnalysisItem(**defaults)


class _FakeDiag:
    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


class _FakePgError(Exception):
    def __init__(self, constraint_name):
        super().__init__(constraint_name)
        self.diag = _FakeDiag(constraint_name)


def _make_integrity_error(constraint_name):
    return IntegrityError("INSERT ...", {}, _FakePgError(constraint_name))


class _TransactionRecorder:
    def __init__(self):
        self.committed = False
        self.rolled_back = False


class _FakeTransaction:
    def __init__(self, recorder):
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._recorder.committed = True
        else:
            self._recorder.rolled_back = True
        return False


class _ExecResult:
    def __init__(self, single=None, many=None):
        self._single = single
        self._many = list(many) if many is not None else []

    def scalar_one_or_none(self):
        return self._single

    def scalars(self):
        return self

    def all(self):
        return self._many


class _CreateFakeSession:
    """SQL 문자열 fingerprint로 쿼리 종류를 구분하는 fake. current_request_sequence/
    active_cycle_sequence는 읽기 트랜잭션·쓰기 트랜잭션(·IntegrityError 복구)에서 순서대로
    하나씩 소비된다."""

    def __init__(
        self,
        *,
        current_request_sequence=(),
        matching_message=None,
        active_cycle_sequence=(),
        candidate_tasks=(),
        candidate_fixed_schedules=(),
        target_task=None,
        target_fixed_schedule=None,
        integrity_error=None,
        integrity_error_on_flush_no=None,
    ):
        self._current_request_iter = iter(current_request_sequence)
        self.matching_message = matching_message
        self._active_cycle_iter = iter(active_cycle_sequence)
        self.candidate_tasks = list(candidate_tasks)
        self.candidate_fixed_schedules = list(candidate_fixed_schedules)
        self.target_task = target_task
        self.target_fixed_schedule = target_fixed_schedule
        self.integrity_error = integrity_error
        self.integrity_error_on_flush_no = integrity_error_on_flush_no
        self.added = []
        self._flush_count = 0

    def begin(self):
        return _FakeTransaction(_TransactionRecorder())

    def execute(self, stmt):
        sql = str(stmt)
        if "solar_requests.status IN" in sql:
            return _ExecResult(single=next(self._current_request_iter, None))
        if "solar_messages" in sql:
            return _ExecResult(single=self.matching_message)
        if "planning_cycles" in sql:
            return _ExecResult(single=next(self._active_cycle_iter, None))
        if "tasks.id =" in sql:
            return _ExecResult(single=self.target_task)
        if "fixed_schedules.id =" in sql:
            return _ExecResult(single=self.target_fixed_schedule)
        if "tasks" in sql:
            return _ExecResult(many=self.candidate_tasks)
        if "fixed_schedules" in sql:
            return _ExecResult(many=self.candidate_fixed_schedules)
        raise AssertionError(f"예상치 못한 쿼리: {sql}")

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self._flush_count += 1
        if self._flush_count == self.integrity_error_on_flush_no:
            raise self.integrity_error


@pytest.fixture
def patch_plan_management_state(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(plan_management_service_module, "get_plan_management_state", lambda db, user_id: sentinel)
    return sentinel


def _patch_analyze_message(monkeypatch, *, result=None, error=None):
    def _fake(*args, **kwargs):
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(solar_client_module, "analyze_message", _fake)


def _patch_analyze_message_not_called(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("analyze_message가 호출되면 안 된다.")

    monkeypatch.setattr(solar_client_module, "analyze_message", _fail)


def _call_create(fake_db, **overrides):
    kwargs = dict(
        user_id=USER_ID,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        client_event_id="evt",
        message="메시지",
        now=NOW,
    )
    kwargs.update(overrides)
    return solar_request_service.create_solar_request(fake_db, **kwargs)


def test_create_solar_request_new_cycle_create_success_is_change_confirmation(
    monkeypatch, patch_plan_management_state
):
    item = _create_item()
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    result = _call_create(
        fake_db, client_event_id="evt-1", message=" 새 과제 만들어줘 ", purpose=SolarRequestPurpose.NEW_CYCLE
    )

    assert result.created is True
    assert result.state is patch_plan_management_state
    assert len(fake_db.added) == 1 + 1 + 2

    request_obj, item_obj, user_message, assistant_message = fake_db.added
    assert request_obj.status == SolarRequestStatus.CHANGE_CONFIRMATION
    assert request_obj.current_item_order is None
    assert request_obj.raw_input == "새 과제 만들어줘"
    assert request_obj.plan_cycle_id is None

    assert item_obj.status == SolarItemStatus.READY
    assert item_obj.normalized_payload["remainingMinutes"] == 120
    assert "_updateFields" not in item_obj.normalized_payload

    assert user_message.role == SolarMessageRole.USER
    assert user_message.kind == SolarMessageKind.TEXT
    assert user_message.client_event_id == "evt-1"
    assert user_message.sequence_no == 1
    assert user_message.content == "새 과제 만들어줘"

    assert assistant_message.role == SolarMessageRole.ASSISTANT
    assert assistant_message.kind == SolarMessageKind.TEXT
    assert assistant_message.client_event_id is None
    assert assistant_message.sequence_no == 2
    assert assistant_message.message_metadata["snapshotVersion"] == 1
    snapshot = assistant_message.message_metadata["requestItemSnapshots"][0]
    assert snapshot["requestItemId"] == str(item_obj.id)
    assert snapshot["itemOrder"] == 1
    assert snapshot["status"] == "READY"
    assert uuid.UUID(snapshot["snapshotId"])


def test_create_four_complete_tasks_persists_deterministic_items_and_snapshots(
    monkeypatch, patch_plan_management_state
):
    titles = ["C++ 복습", "선형대수 복습", "자료구조 복습", "운영체제 복습"]
    items = [
        _create_item(
            raw_line_text=f"오늘 오후 5시 59분까지 {title} 1단원을 하고 총 30분 걸려.",
            normalized_payload={
                "title": title,
                "deadlineAt": "2026-07-30T17:59:00+09:00",
                "estimatedMinutes": 30,
                "estimatedMinutesSource": "USER",
                "remainingMinutes": None,
                "amountText": "1단원",
                "amountSource": "USER",
            },
        )
        for title in titles
    ]
    analysis = SolarAnalysisResult(analysis_message="네 개 작업을 확인했어요.", items=items, unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    result = _call_create(fake_db, client_event_id="evt-four-tasks", message="\n".join(item.raw_line_text for item in items))

    assert result.created is True
    request_obj = fake_db.added[0]
    stored_items = fake_db.added[1:5]
    assert request_obj.status == SolarRequestStatus.CHANGE_CONFIRMATION
    assert [item.item_order for item in stored_items] == [1, 2, 3, 4]
    assert [item.normalized_payload["title"] for item in stored_items] == titles
    assert all(item.normalized_payload["amountText"] == "1단원" for item in stored_items)
    assert all(item.normalized_payload["estimatedMinutes"] == 30 for item in stored_items)
    snapshots = fake_db.added[-1].message_metadata["requestItemSnapshots"]
    assert len(snapshots) == 4
    assert len({snapshot["snapshotId"] for snapshot in snapshots}) == 4


def test_create_solar_request_collecting_adds_question_message(monkeypatch, patch_plan_management_state):
    item = _create_item(
        normalized_payload={
            "title": "새 과제",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=["deadlineAt", "estimatedMinutes", "amount"],
        pending_question={"field": "deadlineAt", "message": "마감이 언제인가요?"},
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    result = _call_create(fake_db, client_event_id="evt-2", message="과제 만들어줘")

    assert result.created is True
    request_obj = fake_db.added[0]
    assert request_obj.status == SolarRequestStatus.COLLECTING
    assert request_obj.current_item_order == 1
    assert len(fake_db.added) == 1 + 1 + 3

    analysis_message = fake_db.added[-2]
    question_message = fake_db.added[-1]
    snapshot = analysis_message.message_metadata["requestItemSnapshots"][0]
    assert analysis_message.sequence_no == 2
    assert snapshot["status"] == "INFO_MISSING"
    assert snapshot["missingFields"] == ["deadlineAt", "estimatedMinutes", "amount"]
    assert question_message.kind == SolarMessageKind.QUESTION
    assert question_message.sequence_no == 3
    assert question_message.content == "마감이 언제인가요?"
    assert question_message.message_metadata["field"] == "deadlineAt"
    assert question_message.message_metadata["itemId"] == str(fake_db.added[1].id)


def test_create_recurring_task_stays_collecting_and_clears_occurrence_values(
    monkeypatch, patch_plan_management_state
):
    item = _create_item(
        raw_line_text="매일 영어 단어 20개씩 외울래",
        normalized_payload={
            "title": "영어 단어 암기",
            "deadlineAt": "2026-08-31T23:59:59+09:00",
            "estimatedMinutes": 20,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": "20개",
            "amountSource": "USER",
        },
        unsupported_intent="RECURRING_TASK",
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    result = _call_create(fake_db, client_event_id="evt-recurring", message="매일 영어 단어 20개씩 외울래")

    assert result.created is True
    request_obj, item_obj = fake_db.added[:2]
    assert request_obj.status == SolarRequestStatus.COLLECTING
    assert item_obj.status == SolarItemStatus.INFO_MISSING
    assert item_obj.normalized_payload["_unsupportedIntent"] == "RECURRING_TASK"
    assert item_obj.normalized_payload["deadlineAt"] is None
    assert item_obj.normalized_payload["estimatedMinutes"] is None
    assert item_obj.normalized_payload["amountText"] is None
    question = fake_db.added[-1]
    assert question.message_metadata == {
        "itemId": str(item_obj.id),
        "field": "unsupportedRecurrence",
        "followUpType": "UNSUPPORTED_TASK_RECURRENCE",
    }
    assert "반복 계획은 아직 지원하지 않아요" in question.content
    assert "전체 분량" in question.content
    assert "총 예상 시간" in question.content


def test_create_rejects_false_structured_recurring_marker_per_item(
    monkeypatch, patch_plan_management_state, caplog
):
    item = _create_item(
        raw_line_text="8월 7일까지 운영체제 과제 2문제 해야 해",
        normalized_payload={
            "title": "운영체제 과제",
            "deadlineAt": "2026-08-07T23:59:59+09:00",
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": "2문제",
            "amountSource": "USER",
        },
        missing_fields=["estimatedMinutes"],
        pending_question={"field": "estimatedMinutes", "message": "예상 시간이 얼마나 걸릴까요?"},
        unsupported_intent="RECURRING_TASK",
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    with caplog.at_level("WARNING", logger="app.services.solar_request_service"):
        _call_create(fake_db, client_event_id="evt-false-recurring", message=item.raw_line_text)

    item_obj = fake_db.added[1]
    assert "_unsupportedIntent" not in item_obj.normalized_payload
    assert item_obj.missing_fields == ["estimatedMinutes"]
    assert item_obj.pending_question["field"] == "estimatedMinutes"
    assert any("SOLAR_RECURRING_TASK_MARKER_REJECTED" in record.message for record in caplog.records)


def test_create_multiple_tasks_keeps_recurrence_marker_on_matching_item_only(
    monkeypatch, patch_plan_management_state
):
    one_off = _create_item(
        raw_line_text="운영체제 과제 해야 해",
        normalized_payload={
            "title": "운영체제 과제",
            "deadlineAt": None,
            "estimatedMinutes": 120,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": "UNKNOWN",
        },
        unsupported_intent="RECURRING_TASK",
    )
    recurring = _create_item(
        raw_line_text="매일 영어 단어를 외울래",
        normalized_payload={
            "title": "영어 단어 암기",
            "deadlineAt": None,
            "estimatedMinutes": 20,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": "UNKNOWN",
        },
    )
    analysis = SolarAnalysisResult(
        analysis_message="분석 완료", items=[one_off, recurring], unresolved_line=None
    )
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(fake_db, client_event_id="evt-isolated-recurring", message="두 작업")

    one_off_obj, recurring_obj = fake_db.added[1:3]
    assert one_off_obj.id != recurring_obj.id
    assert "_unsupportedIntent" not in one_off_obj.normalized_payload
    assert one_off_obj.status == SolarItemStatus.READY
    assert recurring_obj.normalized_payload["_unsupportedIntent"] == "RECURRING_TASK"
    assert recurring_obj.status == SolarItemStatus.INFO_MISSING
    question = fake_db.added[-1]
    assert question.message_metadata["itemId"] == str(recurring_obj.id)
    assert question.message_metadata["followUpType"] == "UNSUPPORTED_TASK_RECURRENCE"


@pytest.mark.parametrize(
    ("solar_start", "solar_end"),
    [
        ("2026-08-01T10:00:00+09:00", "2026-08-01T16:00:00+09:00"),
        ("2026-08-02T10:00:00+09:00", "2026-08-02T16:00:00+09:00"),
    ],
)
def test_create_fixed_schedule_relative_weekday_normalizes_wrong_or_past_solar_date(
    monkeypatch, patch_plan_management_state, solar_start, solar_end
):
    now = datetime(2026, 8, 2, 14, 17, tzinfo=timezone(timedelta(hours=9)))
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text="토요일 오전 10시부터 오후 4시까지 알바",
        normalized_payload={"title": "알바", "startAt": solar_start, "endAt": solar_end},
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db, client_event_id=f"evt-relative-{solar_start}", message=item.raw_line_text, now=now
    )

    request_obj, item_obj = fake_db.added[:2]
    assert request_obj.status == SolarRequestStatus.CHANGE_CONFIRMATION
    assert item_obj.status == SolarItemStatus.READY
    assert item_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"
    assert item_obj.normalized_payload["endAt"] == "2026-08-08T16:00:00+09:00"
    assert item_obj.pending_question is None


def test_create_compound_input_scopes_task_date_out_of_fixed_schedule_normalization(
    monkeypatch, patch_plan_management_state
):
    compound = (
        "8월 7일까지 운영체제 과제 2문제 해야 하고, "
        "토요일 오전 10시부터 오후 4시까지 알바 있어"
    )
    task = _create_item(
        raw_line_text="8월 7일까지 운영체제 과제 2문제 해야 해",
        normalized_payload={
            "title": "운영체제 과제",
            "deadlineAt": "2026-08-07T23:59:59+09:00",
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": "2문제",
            "amountSource": "USER",
        },
        missing_fields=["estimatedMinutes"],
        pending_question={"field": "estimatedMinutes", "message": "예상 시간이 얼마나 걸릴까요?"},
    )
    fixed = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text=compound,
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-01T10:00:00+09:00",
            "endAt": "2026-08-01T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(
        analysis_message="분석 완료", items=[task, fixed], unresolved_line=None
    )
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id="evt-compound-fixed-scope",
        message=compound,
        now=datetime(2026, 8, 2, 14, 28, tzinfo=timezone(timedelta(hours=9))),
    )

    task_obj, fixed_obj = fake_db.added[1:3]
    assert task_obj.normalized_payload["deadlineAt"] == "2026-08-07T23:59:59+09:00"
    assert task_obj.missing_fields == ["estimatedMinutes"]
    assert fixed_obj.status == SolarItemStatus.READY
    assert fixed_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"
    assert fixed_obj.normalized_payload["endAt"] == "2026-08-08T16:00:00+09:00"
    assert fixed_obj.missing_fields == []
    assert fixed_obj.pending_question is None
    question = fake_db.added[-1]
    assert question.message_metadata["itemId"] == str(task_obj.id)
    assert question.message_metadata["field"] == "estimatedMinutes"


@pytest.mark.parametrize(
    ("raw_line_text", "start_at", "end_at", "expected_status"),
    [
        (
            "토요일 오전 10시 - 오후 4시 알바",
            "2026-08-01T10:00:00+09:00",
            "2026-08-01T16:00:00+09:00",
            SolarItemStatus.READY,
        ),
        (
            "토요일 오전 10시부터 오후 4시까지 알바",
            "2026-08-01T11:00:00+09:00",
            "2026-08-01T17:00:00+09:00",
            SolarItemStatus.INFO_MISSING,
        ),
    ],
)
def test_create_fixed_schedule_prefers_valid_structured_time_but_rejects_clear_raw_conflict(
    monkeypatch, patch_plan_management_state, raw_line_text, start_at, end_at, expected_status
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text=raw_line_text,
        normalized_payload={"title": "알바", "startAt": start_at, "endAt": end_at},
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id=f"evt-structured-time-{expected_status.value}",
        message=raw_line_text,
        now=datetime(2026, 8, 2, 14, 28, tzinfo=timezone(timedelta(hours=9))),
    )

    item_obj = fake_db.added[1]
    assert item_obj.status == expected_status
    if expected_status == SolarItemStatus.READY:
        assert item_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"
        assert item_obj.normalized_payload["endAt"] == "2026-08-08T16:00:00+09:00"
    else:
        assert item_obj.normalized_payload["startAt"] is None
        assert item_obj.normalized_payload["endAt"] is None


@pytest.mark.parametrize(
    ("now", "expected_date"),
    [
        (datetime(2026, 8, 8, 9, 0, tzinfo=timezone(timedelta(hours=9))), "2026-08-08"),
        (datetime(2026, 8, 8, 14, 0, tzinfo=timezone(timedelta(hours=9))), "2026-08-15"),
    ],
)
def test_create_fixed_schedule_same_weekday_uses_today_before_start_else_next_week(
    monkeypatch, patch_plan_management_state, now, expected_date
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text="토요일 오전 10시부터 오후 4시까지 알바",
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-01T10:00:00+09:00",
            "endAt": "2026-08-01T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(fake_db, client_event_id=f"evt-same-{expected_date}", message=item.raw_line_text, now=now)

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["startAt"] == f"{expected_date}T10:00:00+09:00"
    assert item_obj.normalized_payload["endAt"] == f"{expected_date}T16:00:00+09:00"


def test_create_fixed_schedule_absolute_date_weekday_mismatch_asks_exact_date(
    monkeypatch, patch_plan_management_state
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text="8월 2일 토요일 오전 10시부터 오후 4시까지 알바",
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-02T10:00:00+09:00",
            "endAt": "2026-08-02T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id="evt-weekday-mismatch",
        message=item.raw_line_text,
        now=datetime(2026, 8, 1, 9, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    request_obj, item_obj = fake_db.added[:2]
    assert request_obj.status == SolarRequestStatus.COLLECTING
    assert item_obj.status == SolarItemStatus.INFO_MISSING
    assert item_obj.normalized_payload["startAt"] is None
    assert item_obj.normalized_payload["endAt"] is None
    assert item_obj.missing_fields == ["startAt", "endAt"]
    assert item_obj.pending_question["field"] == "startAt"
    assert "정확히 몇 월 며칠" in item_obj.pending_question["message"]


@pytest.mark.parametrize(
    "raw_line_text",
    [
        "토요일이나 일요일에 알바",
        "토요일 또는 일요일에 알바",
        "주말에 알바",
        "매주 토요일 오전 10시부터 오후 4시까지 알바",
        "토요일마다 오전 10시부터 오후 4시까지 알바",
        "토요일에 알바",
    ],
)
def test_create_fixed_schedule_ambiguous_recurring_or_missing_time_asks_date(
    monkeypatch, patch_plan_management_state, raw_line_text
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text=raw_line_text,
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-08T10:00:00+09:00",
            "endAt": "2026-08-08T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id=f"evt-ambiguous-{len(raw_line_text)}",
        message=raw_line_text,
        now=datetime(2026, 8, 2, 14, 17, tzinfo=timezone(timedelta(hours=9))),
    )

    item_obj = fake_db.added[1]
    assert item_obj.status == SolarItemStatus.INFO_MISSING
    assert item_obj.normalized_payload["startAt"] is None
    assert item_obj.normalized_payload["endAt"] is None


def test_create_fixed_schedule_explicit_next_week_uses_next_week_date(
    monkeypatch, patch_plan_management_state
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text="다음 주 토요일 오전 10시부터 오후 4시까지 알바",
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-08T10:00:00+09:00",
            "endAt": "2026-08-08T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id="evt-next-week",
        message=item.raw_line_text,
        now=datetime(2026, 8, 2, 14, 17, tzinfo=timezone(timedelta(hours=9))),
    )

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"
    assert item_obj.normalized_payload["endAt"] == "2026-08-08T16:00:00+09:00"


def test_create_fixed_schedule_relative_weekday_uses_seoul_date_across_utc_midnight_boundary(
    monkeypatch, patch_plan_management_state
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text="토요일 오전 10시부터 오후 4시까지 알바",
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-01T01:00:00Z",
            "endAt": "2026-08-01T07:00:00Z",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(
        fake_db,
        client_event_id="evt-seoul-midnight",
        message=item.raw_line_text,
        now=datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc),
    )

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"
    assert item_obj.normalized_payload["endAt"] == "2026-08-08T16:00:00+09:00"


@pytest.mark.parametrize(
    "raw_line_text",
    [
        "8월 8일 토요일 오전 10시부터 오후 4시까지 알바",
        "8월 8일 오전 10시부터 오후 4시까지 알바",
    ],
)
def test_create_fixed_schedule_matching_or_absent_weekday_remains_ready(
    monkeypatch, patch_plan_management_state, raw_line_text
):
    item = _create_item(
        entity_type="FIXED_SCHEDULE",
        raw_line_text=raw_line_text,
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-08T10:00:00+09:00",
            "endAt": "2026-08-08T16:00:00+09:00",
        },
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[None, None])

    _call_create(fake_db, client_event_id=f"evt-weekday-{len(raw_line_text)}", message=raw_line_text)

    request_obj, item_obj = fake_db.added[:2]
    assert request_obj.status == SolarRequestStatus.CHANGE_CONFIRMATION
    assert item_obj.status == SolarItemStatus.READY
    assert item_obj.normalized_payload["startAt"] == "2026-08-08T10:00:00+09:00"


def test_create_solar_request_active_cycle_update_remaining_minutes_only(monkeypatch, patch_plan_management_state):
    task = _make_task(estimated_minutes=180, remaining_minutes=180)
    item = SolarAnalysisItem(
        entity_type="TASK",
        action="UPDATE",
        target_entity_id=str(TASK_ID),
        raw_line_text="남은 시간을 2시간으로 바꿔줘",
        update_fields=["remainingMinutes"],
        normalized_payload={
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": 120,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_tasks=[task],
        target_task=task,
    )

    result = _call_create(
        fake_db,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        client_event_id="evt-3",
        message="남은 시간을 2시간으로 바꿔줘",
    )

    assert result.created is True
    item_obj = fake_db.added[1]
    assert item_obj.status == SolarItemStatus.READY
    assert item_obj.normalized_payload["remainingMinutes"] == 120
    assert item_obj.normalized_payload["estimatedMinutes"] == 180
    assert item_obj.normalized_payload["title"] == "기존 과제"
    assert item_obj.normalized_payload["_updateFields"] == ["remainingMinutes"]
    assert item_obj.target_task_id == TASK_ID
    assert item_obj.target_fixed_schedule_id is None


def test_create_solar_request_update_backfills_from_fresh_db_value_not_candidate_snapshot(
    monkeypatch, patch_plan_management_state
):
    # 후보 스냅숏 시점엔 remaining_minutes=180이었지만 쓰기 시점엔 CheckIn 등으로 60이 된 상태.
    task = _make_task(estimated_minutes=180, remaining_minutes=60)
    item = SolarAnalysisItem(
        entity_type="TASK",
        action="UPDATE",
        target_entity_id=str(TASK_ID),
        raw_line_text="마감을 내일로 바꿔줘",
        update_fields=["deadlineAt"],
        normalized_payload={
            "title": None,
            "deadlineAt": "2026-08-01T23:59:59+09:00",
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_tasks=[task],
        target_task=task,
    )

    _call_create(
        fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-19", message="마감을 내일로 바꿔줘"
    )

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["remainingMinutes"] == 60


def test_create_solar_request_update_explicit_deadline_removal_not_backfilled(
    monkeypatch, patch_plan_management_state
):
    task = _make_task(deadline_at=datetime(2026, 8, 1, 23, 59, 59, tzinfo=timezone.utc))
    item = SolarAnalysisItem(
        entity_type="TASK",
        action="UPDATE",
        target_entity_id=str(TASK_ID),
        raw_line_text="마감 없애줘",
        update_fields=["deadlineAt"],
        normalized_payload={
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_tasks=[task],
        target_task=task,
    )

    _call_create(fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-16", message="마감 없애줘")

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["deadlineAt"] is None
    assert item_obj.status == SolarItemStatus.READY


def test_create_solar_request_active_cycle_delete_success(monkeypatch, patch_plan_management_state):
    task = _make_task()
    item = SolarAnalysisItem(
        entity_type="TASK",
        action="DELETE",
        target_entity_id=str(TASK_ID),
        raw_line_text="그 과제 취소해줘",
        update_fields=[],
        normalized_payload={
            "title": "아무값",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_tasks=[task],
        target_task=task,
    )

    result = _call_create(
        fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-4", message="그 과제 취소해줘"
    )

    item_obj = fake_db.added[1]
    assert item_obj.status == SolarItemStatus.READY
    assert item_obj.missing_fields == []
    assert "_updateFields" not in item_obj.normalized_payload
    assert item_obj.normalized_payload["title"] == "기존 과제"
    assert item_obj.target_task_id == TASK_ID
    assert result.created is True


def test_create_solar_request_fixed_schedule_update_merge_inverted_range_rejected(monkeypatch):
    fs = _make_fixed_schedule()
    item = SolarAnalysisItem(
        entity_type="FIXED_SCHEDULE",
        action="UPDATE",
        target_entity_id=str(FIXED_SCHEDULE_ID),
        raw_line_text="알바 시작을 19시로 바꿔줘",
        update_fields=["startAt"],
        normalized_payload={"title": None, "startAt": "2026-07-28T19:00:00+00:00", "endAt": None},
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_fixed_schedules=[fs],
        target_fixed_schedule=fs,
    )

    with pytest.raises(ApiError) as exc_info:
        _call_create(
            fake_db,
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            client_event_id="evt-17",
            message="알바 시작을 19시로 바꿔줘",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "SOLAR_UNAVAILABLE"


def test_create_solar_request_fixed_schedule_update_merge_valid_range_accepted(
    monkeypatch, patch_plan_management_state
):
    fs = _make_fixed_schedule()
    item = SolarAnalysisItem(
        entity_type="FIXED_SCHEDULE",
        action="UPDATE",
        target_entity_id=str(FIXED_SCHEDULE_ID),
        raw_line_text="알바 끝나는 시간을 20시로 바꿔줘",
        update_fields=["endAt"],
        normalized_payload={"title": None, "startAt": None, "endAt": "2026-07-28T20:00:00+00:00"},
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_fixed_schedules=[fs],
        target_fixed_schedule=fs,
    )

    result = _call_create(
        fake_db,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        client_event_id="evt-18",
        message="알바 끝나는 시간을 20시로 바꿔줘",
    )

    item_obj = fake_db.added[1]
    assert item_obj.normalized_payload["startAt"] == fs.start_at.isoformat()
    assert item_obj.normalized_payload["endAt"] == "2026-07-28T20:00:00+00:00"
    assert item_obj.status == SolarItemStatus.READY
    assert result.created is True


def test_create_solar_request_unresolved_line_creates_no_card(monkeypatch, patch_plan_management_state):
    unresolved = UnresolvedLine(
        raw_line_text="그 과제 마감 바꿔줘",
        action="UPDATE",
        entity_type="TASK",
        message="어떤 항목을 말씀하시는지 다시 알려주시겠어요?",
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[], unresolved_line=unresolved)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    task = _make_task()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None], active_cycle_sequence=[cycle, cycle], candidate_tasks=[task]
    )

    result = _call_create(
        fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-5", message="그 과제 마감 바꿔줘"
    )

    request_obj = fake_db.added[0]
    assert request_obj.status == SolarRequestStatus.COLLECTING
    assert request_obj.current_item_order is None
    assert len(fake_db.added) == 1 + 0 + 3

    unresolved_message = fake_db.added[-1]
    assert unresolved_message.kind == SolarMessageKind.QUESTION
    assert unresolved_message.message_metadata["unresolved"] is True
    assert unresolved_message.message_metadata["field"] == "targetEntityId"
    assert unresolved_message.message_metadata["candidateEntityIds"] == [str(TASK_ID)]
    assert result.created is True


def test_create_solar_request_idempotent_replay_returns_existing_state(monkeypatch, patch_plan_management_state):
    existing_request = _make_request(purpose=SolarRequestPurpose.NEW_CYCLE, raw_input="기존 메시지")
    existing_message = SolarMessage(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=existing_request.id,
        client_event_id="evt-6",
        sequence_no=1,
        role=SolarMessageRole.USER,
        kind=SolarMessageKind.TEXT,
        content="기존 메시지",
        message_metadata={},
    )
    _patch_analyze_message_not_called(monkeypatch)
    fake_db = _CreateFakeSession(current_request_sequence=[existing_request], matching_message=existing_message)

    result = _call_create(fake_db, client_event_id="evt-6", message="기존 메시지")

    assert result.created is False
    assert result.state is patch_plan_management_state
    assert fake_db.added == []


def test_create_solar_request_active_request_exists_conflict_on_different_payload(monkeypatch):
    existing_request = _make_request(purpose=SolarRequestPurpose.NEW_CYCLE, raw_input="기존 메시지")
    _patch_analyze_message_not_called(monkeypatch)
    fake_db = _CreateFakeSession(current_request_sequence=[existing_request], matching_message=None)

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, client_event_id="evt-7", message="다른 메시지")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == solar_request_service.CODE_ACTIVE_REQUEST_EXISTS
    assert fake_db.added == []


def test_create_solar_request_new_cycle_active_cycle_exists(monkeypatch):
    cycle = _make_cycle()
    _patch_analyze_message_not_called(monkeypatch)
    fake_db = _CreateFakeSession(current_request_sequence=[None], active_cycle_sequence=[cycle])

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, client_event_id="evt-8", message="새 계획 시작")

    assert exc_info.value.code == solar_request_service.CODE_ACTIVE_CYCLE_EXISTS


def test_create_solar_request_active_cycle_no_active_cycle(monkeypatch):
    _patch_analyze_message_not_called(monkeypatch)
    fake_db = _CreateFakeSession(current_request_sequence=[None], active_cycle_sequence=[None])

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-9", message="과제 바꿔줘")

    assert exc_info.value.code == solar_request_service.CODE_NO_ACTIVE_CYCLE


def test_create_solar_request_cycle_changed_during_solar_call(monkeypatch, patch_plan_management_state):
    item = _create_item()
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    other_cycle = _make_cycle(id=uuid.uuid4())
    fake_db = _CreateFakeSession(current_request_sequence=[None, None], active_cycle_sequence=[cycle, other_cycle])

    with pytest.raises(ApiError) as exc_info:
        _call_create(
            fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-10", message="과제 추가해줘"
        )

    assert exc_info.value.code == solar_request_service.CODE_CYCLE_NOT_ACTIVE
    assert fake_db.added == []


def test_create_solar_request_target_ambiguous_when_target_missing_at_write_time(
    monkeypatch, patch_plan_management_state
):
    item = SolarAnalysisItem(
        entity_type="TASK",
        action="UPDATE",
        target_entity_id=str(TASK_ID),
        raw_line_text="마감 바꿔줘",
        update_fields=["deadlineAt"],
        normalized_payload={
            "title": None,
            "deadlineAt": "2026-08-01T23:59:59+09:00",
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=[],
        pending_question=None,
    )
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    cycle = _make_cycle()
    task = _make_task()
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[cycle, cycle],
        candidate_tasks=[task],
        target_task=None,
    )

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, purpose=SolarRequestPurpose.ACTIVE_CYCLE, client_event_id="evt-11", message="마감 바꿔줘")

    assert exc_info.value.code == solar_request_service.CODE_TARGET_AMBIGUOUS
    assert fake_db.added == []


def test_create_solar_request_solar_failure_maps_to_503_and_no_writes(monkeypatch):
    _patch_analyze_message(monkeypatch, error=SolarUnavailableError("boom"))
    fake_db = _CreateFakeSession(current_request_sequence=[None], active_cycle_sequence=[None])

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, client_event_id="evt-12", message="새 과제")

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "SOLAR_UNAVAILABLE"
    assert fake_db.added == []


def test_create_solar_request_final_repair_failure_maps_to_503_and_no_writes(monkeypatch):
    """analyze_message 내부에서 canonicalization + repair 1회까지 시도한 뒤에도 최종
    실패하면(SolarUnavailableError에 code가 실려 있어도) create_solar_request는 여전히
    503 SOLAR_UNAVAILABLE로 매핑하고 어떤 DB 행도 저장하지 않는다."""
    _patch_analyze_message(
        monkeypatch, error=SolarUnavailableError("repair도 실패했다.", code="PENDING_FIELD_MISMATCH")
    )
    fake_db = _CreateFakeSession(current_request_sequence=[None], active_cycle_sequence=[None])

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, client_event_id="evt-repair-fail", message="새 과제")

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "SOLAR_UNAVAILABLE"
    assert fake_db.added == []


def test_create_solar_request_integrity_error_replay_branch(monkeypatch, patch_plan_management_state):
    item = _create_item()
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    existing_request = _make_request(purpose=SolarRequestPurpose.NEW_CYCLE, raw_input="새 과제 만들어줘")
    existing_message = SolarMessage(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=existing_request.id,
        client_event_id="evt-13",
        sequence_no=1,
        role=SolarMessageRole.USER,
        kind=SolarMessageKind.TEXT,
        content="새 과제 만들어줘",
        message_metadata={},
    )
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None, existing_request],
        active_cycle_sequence=[None, None],
        matching_message=existing_message,
        integrity_error=_make_integrity_error("uq_solar_requests_one_current_per_user"),
        integrity_error_on_flush_no=1,
    )

    result = _call_create(fake_db, client_event_id="evt-13", message="새 과제 만들어줘")

    assert result.created is False


def test_create_solar_request_integrity_error_conflict_branch(monkeypatch):
    item = _create_item()
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    other_request = _make_request(purpose=SolarRequestPurpose.NEW_CYCLE, raw_input="다른 사람이 만든 요청")
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None, other_request],
        active_cycle_sequence=[None, None],
        matching_message=None,
        integrity_error=_make_integrity_error("uq_solar_requests_one_current_per_user"),
        integrity_error_on_flush_no=1,
    )

    with pytest.raises(ApiError) as exc_info:
        _call_create(fake_db, client_event_id="evt-14", message="새 과제 만들어줘")

    assert exc_info.value.code == solar_request_service.CODE_ACTIVE_REQUEST_EXISTS


def test_create_solar_request_integrity_error_unknown_constraint_reraises(monkeypatch):
    item = _create_item()
    analysis = SolarAnalysisResult(analysis_message="분석 완료", items=[item], unresolved_line=None)
    _patch_analyze_message(monkeypatch, result=analysis)
    fake_db = _CreateFakeSession(
        current_request_sequence=[None, None],
        active_cycle_sequence=[None, None],
        integrity_error=_make_integrity_error("some_other_constraint"),
        integrity_error_on_flush_no=1,
    )

    with pytest.raises(IntegrityError):
        _call_create(fake_db, client_event_id="evt-15", message="새 과제 만들어줘")
