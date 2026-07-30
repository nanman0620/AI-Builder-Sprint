import importlib.util
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str):
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(filename.rsplit(".", 1)[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path.read_text(encoding="utf-8")


def test_revision_and_down_revision():
    module, _ = _load_migration("0002_create_mvp_core_tables.py")
    assert module.revision == "0002_create_mvp_core_tables"
    assert module.down_revision == "0001_create_user_profiles"


def test_0001_revision_unchanged():
    module, _ = _load_migration("0001_create_user_profiles.py")
    assert module.revision == "0001_create_user_profiles"
    assert module.down_revision is None


def test_0002_does_not_recreate_user_profiles():
    _, source = _load_migration("0002_create_mvp_core_tables.py")
    assert 'op.create_table(\n        "user_profiles"' not in source
    assert 'op.drop_table("user_profiles"' not in source


def test_0002_does_not_touch_auth_users():
    _, source = _load_migration("0002_create_mvp_core_tables.py")
    assert "CREATE TABLE" not in source.upper().replace("OP.CREATE_TABLE", "")
    assert 'op.create_table(\n        "users"' not in source
    assert "auth.users" not in source
    assert 'schema="auth"' not in source


def test_0001_migration_file_not_modified_by_this_change():
    # 0002는 새 revision만 추가하며 0001 파일 자체의 upgrade/downgrade 로직은
    # 이번 Issue에서 변경 대상이 아니다. user_profiles 테이블 생성 로직이
    # 여전히 0001에만 존재하는지로 간접 확인한다.
    _, source_0001 = _load_migration("0001_create_user_profiles.py")
    assert 'op.create_table(\n        "user_profiles"' in source_0001


def test_new_tables_created_in_0002_only():
    _, source = _load_migration("0002_create_mvp_core_tables.py")
    for table_name in [
        "planning_cycles",
        "solar_requests",
        "solar_request_items",
        "solar_messages",
        "tasks",
        "fixed_schedules",
        "plan_blocks",
        "check_ins",
    ]:
        assert f'op.create_table(\n        "{table_name}"' in source
