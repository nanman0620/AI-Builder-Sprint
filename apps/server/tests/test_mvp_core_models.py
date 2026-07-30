import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.db.base import Base
from app.models.check_in import CheckIn
from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanBlockStatus,
    PlanCycleStatus,
    PlanPeriod,
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_message import SolarMessage
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task

APP_TABLE_NAMES = {
    "user_profiles",
    "planning_cycles",
    "solar_requests",
    "solar_request_items",
    "solar_messages",
    "tasks",
    "fixed_schedules",
    "plan_blocks",
    "check_ins",
}


def _check_constraints(table):
    return {c for c in table.constraints if isinstance(c, CheckConstraint)}


def _check_names(table):
    return {c.name for c in _check_constraints(table)}


def _unique_constraints(table):
    return {c for c in table.constraints if isinstance(c, UniqueConstraint)}


def _fk_constraints(table):
    return {c for c in table.constraints if isinstance(c, ForeignKeyConstraint)}


def _fk_by_columns(table, columns: tuple[str, ...]) -> ForeignKeyConstraint:
    for fk in _fk_constraints(table):
        if tuple(fk.column_keys) == columns:
            return fk
    raise AssertionError(f"{table.name}에 컬럼 {columns}에 대한 ForeignKeyConstraint가 없다")


# 1. Base.metadata에 앱 테이블 9개 모두 등록 -------------------------------------


def test_base_metadata_has_all_nine_app_tables():
    table_names = set(Base.metadata.tables.keys())
    assert APP_TABLE_NAMES.issubset(table_names)


def test_auth_users_stub_is_excluded_from_app_tables():
    assert "auth.users" in Base.metadata.tables
    assert "auth.users" not in APP_TABLE_NAMES


# 2/3. Enum 이름과 값 --------------------------------------------------------

ENUM_CASES = [
    (PlanningCycle, "status", PlanCycleStatus, "plan_cycle_status", {"ACTIVE", "ENDED"}),
    (SolarRequest, "purpose", SolarRequestPurpose, "solar_request_purpose", {"NEW_CYCLE", "ACTIVE_CYCLE"}),
    (
        SolarRequest,
        "status",
        SolarRequestStatus,
        "solar_request_status",
        {
            "COLLECTING",
            "CHANGE_CONFIRMATION",
            "CHANGE_INPUT",
            "FINAL_REVIEW",
            "EXECUTING",
            "COMPLETED",
            "FAILED",
        },
    ),
    (SolarRequestItem, "action", SolarAction, "solar_action", {"CREATE", "UPDATE", "DELETE"}),
    (
        SolarRequestItem,
        "entity_type",
        SolarEntityType,
        "solar_entity_type",
        {"TASK", "FIXED_SCHEDULE"},
    ),
    (
        SolarRequestItem,
        "status",
        SolarItemStatus,
        "solar_item_status",
        {"INFO_MISSING", "READY", "EXECUTED"},
    ),
    (SolarMessage, "role", SolarMessageRole, "solar_message_role", {"USER", "ASSISTANT"}),
    (
        SolarMessage,
        "kind",
        SolarMessageKind,
        "solar_message_kind",
        {"TEXT", "QUESTION", "ERROR", "DECISION"},
    ),
    (CheckIn, "period", PlanPeriod, "plan_period", {"MORNING", "AFTERNOON", "EVENING"}),
    (PlanBlock, "period", PlanPeriod, "plan_period", {"MORNING", "AFTERNOON", "EVENING"}),
    (Task, "status", TaskStatus, "task_status", {"ACTIVE", "COMPLETED", "CANCELLED"}),
    (
        PlanBlock,
        "status",
        PlanBlockStatus,
        "plan_block_status",
        {"PLANNED", "CHECKED", "COMPLETED", "NOT_DONE"},
    ),
    (Task, "estimated_minutes_source", EstimateSource, "estimate_source", {"USER", "AI_ESTIMATED"}),
    (
        Task,
        "amount_source",
        AmountSource,
        "amount_source",
        {"USER", "AI_ESTIMATED", "UNKNOWN"},
    ),
]


@pytest.mark.parametrize("model, column_name, py_enum, pg_name, values", ENUM_CASES)
def test_enum_name_and_values(model, column_name, py_enum, pg_name, values):
    column = model.__table__.c[column_name]
    assert column.type.name == pg_name
    assert set(column.type.enums) == values
    assert {member.value for member in py_enum} == values


# 4. 필수 FK와 ON DELETE 정책 --------------------------------------------------


def test_planning_cycles_user_id_fk_restrict():
    table = PlanningCycle.__table__
    fk = _fk_by_columns(table, ("user_id",))
    assert fk.elements[0].column.table.name == "user_profiles"
    assert fk.ondelete == "RESTRICT"


def test_solar_request_items_solar_request_id_composite_fk_cascade():
    table = SolarRequestItem.__table__
    fk = _fk_by_columns(table, ("solar_request_id", "user_id"))
    assert fk.ondelete == "CASCADE"
    referred_tables = {elem.column.table.name for elem in fk.elements}
    assert referred_tables == {"solar_requests"}


def test_solar_messages_solar_request_id_composite_fk_cascade():
    table = SolarMessage.__table__
    fk = _fk_by_columns(table, ("solar_request_id", "user_id"))
    assert fk.ondelete == "CASCADE"


def test_tasks_source_request_item_column_specific_set_null():
    table = Task.__table__
    fk = _fk_by_columns(table, ("source_request_item_id", "user_id"))
    assert fk.ondelete == "SET NULL (source_request_item_id)"


def test_fixed_schedules_source_request_item_column_specific_set_null():
    table = FixedSchedule.__table__
    fk = _fk_by_columns(table, ("source_request_item_id", "user_id"))
    assert fk.ondelete == "SET NULL (source_request_item_id)"


def test_solar_request_items_target_task_id_restrict():
    table = SolarRequestItem.__table__
    fk = _fk_by_columns(table, ("target_task_id", "user_id"))
    assert fk.ondelete == "RESTRICT"
    referred_tables = {elem.column.table.name for elem in fk.elements}
    assert referred_tables == {"tasks"}


def test_solar_request_items_target_fixed_schedule_column_specific_set_null():
    table = SolarRequestItem.__table__
    fk = _fk_by_columns(table, ("target_fixed_schedule_id", "user_id"))
    assert fk.ondelete == "SET NULL (target_fixed_schedule_id)"


def test_plan_blocks_task_id_composite_fk_restrict():
    table = PlanBlock.__table__
    fk = _fk_by_columns(table, ("task_id", "user_id", "plan_cycle_id"))
    assert fk.ondelete == "RESTRICT"
    referred_tables = {elem.column.table.name for elem in fk.elements}
    assert referred_tables == {"tasks"}


def test_plan_blocks_check_in_id_composite_fk_restrict():
    table = PlanBlock.__table__
    fk = _fk_by_columns(table, ("check_in_id", "user_id", "plan_cycle_id", "plan_date", "period"))
    assert fk.ondelete == "RESTRICT"
    referred_tables = {elem.column.table.name for elem in fk.elements}
    assert referred_tables == {"check_ins"}


def test_plan_blocks_rescheduled_from_block_id_self_fk_column_specific_set_null():
    table = PlanBlock.__table__
    fk = _fk_by_columns(table, ("rescheduled_from_block_id", "user_id", "plan_cycle_id", "task_id"))
    assert fk.ondelete == "SET NULL (rescheduled_from_block_id)"
    referred_tables = {elem.column.table.name for elem in fk.elements}
    assert referred_tables == {"plan_blocks"}


# 5. 복합 UNIQUE 및 복합 FK ----------------------------------------------------


@pytest.mark.parametrize(
    "model, columns, name",
    [
        (PlanningCycle, ("id", "user_id"), "uq_planning_cycles_id_user"),
        (SolarRequest, ("id", "user_id"), "uq_solar_requests_id_user"),
        (SolarRequestItem, ("id", "user_id"), "uq_solar_request_items_id_user"),
        (Task, ("id", "user_id"), "uq_tasks_id_user"),
        (Task, ("id", "user_id", "plan_cycle_id"), "uq_tasks_id_user_cycle"),
        (FixedSchedule, ("id", "user_id"), "uq_fixed_schedules_id_user"),
        (
            PlanBlock,
            ("id", "user_id", "plan_cycle_id", "task_id"),
            "uq_plan_blocks_id_user_cycle_task",
        ),
        (
            CheckIn,
            ("id", "user_id", "plan_cycle_id", "check_date", "period"),
            "uq_check_ins_full_identity",
        ),
    ],
)
def test_composite_unique_constraint_for_fk_target(model, columns, name):
    table = model.__table__
    matches = [
        c
        for c in _unique_constraints(table)
        if tuple(col.name for col in c.columns) == columns
    ]
    assert matches, f"{table.name}에 {columns} UNIQUE가 없다"
    assert matches[0].name == name


def test_solar_request_items_order_unique():
    table = SolarRequestItem.__table__
    names = {c.name for c in _unique_constraints(table)}
    assert "uq_solar_request_items_order" in names


def test_check_ins_cycle_date_period_unique():
    table = CheckIn.__table__
    names = {c.name for c in _unique_constraints(table)}
    assert "uq_check_ins_cycle_date_period" in names


def test_plan_blocks_task_date_period_and_display_order_unique():
    table = PlanBlock.__table__
    names = {c.name for c in _unique_constraints(table)}
    assert "uq_plan_blocks_task_date_period" in names
    assert "uq_plan_blocks_display_order" in names


# 6. partial UNIQUE index와 주요 조회 index -------------------------------------


def _index_names(table):
    return {ix.name for ix in table.indexes}


def test_planning_cycles_partial_unique_active_index():
    table = PlanningCycle.__table__
    index = next(ix for ix in table.indexes if ix.name == "uq_planning_cycles_one_active_per_user")
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def test_solar_requests_partial_unique_current_index():
    table = SolarRequest.__table__
    index = next(ix for ix in table.indexes if ix.name == "uq_solar_requests_one_current_per_user")
    assert index.unique is True


def test_tasks_partial_unique_source_request_item_index():
    table = Task.__table__
    index = next(ix for ix in table.indexes if ix.name == "uq_tasks_source_request_item")
    assert index.unique is True


def test_fixed_schedules_partial_unique_source_request_item_index():
    table = FixedSchedule.__table__
    index = next(ix for ix in table.indexes if ix.name == "uq_fixed_schedules_source_request_item")
    assert index.unique is True


def test_key_lookup_indexes_exist():
    assert "ix_tasks_plan_cycle" in _index_names(Task.__table__)
    assert "ix_tasks_active_deadline" in _index_names(Task.__table__)
    assert "ix_fixed_schedules_range" in _index_names(FixedSchedule.__table__)
    assert "ix_fixed_schedules_plan_cycle" in _index_names(FixedSchedule.__table__)
    assert "ix_plan_blocks_user_date_period" in _index_names(PlanBlock.__table__)
    assert "ix_plan_blocks_cycle_date_period" in _index_names(PlanBlock.__table__)
    assert "ix_plan_blocks_check_in" in _index_names(PlanBlock.__table__)
    assert "ix_check_ins_latest_unacknowledged" in _index_names(CheckIn.__table__)
    assert "ix_check_ins_finalizing" in _index_names(CheckIn.__table__)


# 7. 주요 CHECK constraint ----------------------------------------------------


def _assert_has_check_ending_with(table, suffix: str):
    names = _check_names(table)
    assert any(name and name.endswith(suffix) for name in names), (
        f"{table.name}에 '...{suffix}'로 끝나는 CHECK 제약이 없다 (실제: {names})"
    )


def test_planning_cycles_check_constraints():
    table = PlanningCycle.__table__
    _assert_has_check_ending_with(table, "cycle_is_exactly_seven_days")
    _assert_has_check_ending_with(table, "status_matches_ended_at")


def test_tasks_check_constraints():
    table = Task.__table__
    for suffix in (
        "initial_minutes_positive",
        "estimated_minutes_positive",
        "remaining_minutes_non_negative",
        "title_not_blank",
        "status_consistency",
        "amount_source_consistency",
    ):
        _assert_has_check_ending_with(table, suffix)


def test_plan_blocks_check_constraints():
    table = PlanBlock.__table__
    for suffix in (
        "allocated_minutes_positive",
        "allocated_minutes_max_240",
        "display_order_non_negative",
        "display_title_not_blank",
        "allocated_amount_text_not_blank",
        "status_consistency",
    ):
        _assert_has_check_ending_with(table, suffix)


def test_check_ins_check_constraints_guard_null_bypass():
    constraints = {c.name: c for c in _check_constraints(CheckIn.__table__)}
    match = next(
        (c for name, c in constraints.items() if name and name.endswith("finalized_counts_consistency")),
        None,
    )
    assert match is not None
    sql_text = str(match.sqltext)
    assert "total_plan_count IS NOT NULL" in sql_text
    assert "IS NOT NULL" in sql_text


def test_solar_request_items_check_constraints():
    table = SolarRequestItem.__table__
    _assert_has_check_ending_with(table, "target_reference_integrity")
    _assert_has_check_ending_with(table, "card_status_consistency")
