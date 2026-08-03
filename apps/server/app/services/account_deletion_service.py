"""회원탈퇴 실제 삭제. 최종 API 명세서(§12)는 이 기능을 "시연용 로컬 처리, FastAPI 호출 없음"
으로 명시하지만, 사용자가 명세서 범위를 확인한 뒤 명시적으로 추가 구현을 요청해 이 서비스가
존재한다(문서 밖 확장 — docs/ai/AI_USAGE_LOG.md 참고).

삭제 순서는 FK 제약(전부 ondelete=RESTRICT, solar_request_items/solar_messages만 solar_requests에
CASCADE)을 근거로 정했다:
  1. plan_blocks       (아무것도 이 테이블을 RESTRICT로 막지 않음)
  2. solar_requests    (CASCADE로 solar_request_items·solar_messages 자동 삭제)
  3. fixed_schedules
  4. tasks
  5. check_ins
  6. planning_cycles
  7. user_profiles

`user_profiles`를 맨 먼저 SELECT ... FOR UPDATE로 잠근다. 위 7개 테이블 전부 user_id 컬럼에
`ForeignKey("user_profiles.id")` 직접 참조가 있어(grep으로 확인), PostgreSQL은 그 테이블에 새
행을 INSERT할 때 user_profiles 행에 FOR KEY SHARE 잠금을 요구한다 — 그래서 이 잠금이 유지되는
동안 동시 삽입은 대기하고, 삭제가 커밋되면 그 삽입은 FK 위반으로 깨끗하게 실패해 고아 데이터가
남지 않는다. 단, 이건 "Worker 전체와의 완전한 직렬화"는 아니다 — Worker가 기존 자식 행을 먼저
잠근 뒤 그 부모의 FK 잠금을 요구하는 순서로 진행하면 잠금 획득 순서가 반대가 되어 PostgreSQL이
deadlock으로 감지해 둘 중 하나(우리 쪽일 수도 있음)를 강제 종료시킬 수 있다. 그 경우에도
무결성(고아 데이터 없음)은 보장되며, `DELETE /me`가 멱등하므로 강제 종료된 쪽은 그냥 재시도하면
된다. Worker별 advisory lock(new_cycle_execution_service 등)은 이 잠금과 무관한 별도
namespace라 여기서 추가로 획득하지 않는다(서비스 간 결합·잠금 순서 문제만 늘어남).
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_supabase_service_role_key, get_supabase_url
from app.core.errors import ApiError
from app.models.check_in import CheckIn
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.task import Task
from app.models.user_profile import UserProfile
from app.services import supabase_admin_client

CODE_ACCOUNT_AUTH_DELETION_FAILED = "ACCOUNT_AUTH_DELETION_FAILED"


def delete_account(db: Session, user_id: uuid.UUID) -> None:
    """`user_id` 소유 앱 데이터를 전부 삭제하고 Supabase Auth 계정까지 삭제한다.

    이미 앱 데이터가 없는 상태(직전 호출에서 DB는 성공, Auth만 실패한 뒤 재시도)에서
    호출해도 안전하게 Auth 삭제만 재시도하는 멱등 함수다. 설정(SUPABASE_URL/
    SUPABASE_SERVICE_ROLE_KEY)이 없으면 DB 삭제를 전혀 시작하지 않는다.
    """
    # DB 접근 전에 설정을 먼저 검증한다 — 설정이 없으면 DB DELETE가 하나도 실행되지 않아야 한다.
    get_supabase_url()
    get_supabase_service_role_key()

    with db.begin():
        profile = db.execute(
            select(UserProfile).where(UserProfile.id == user_id).with_for_update()
        ).scalars().one_or_none()

        if profile is not None:
            db.execute(delete(PlanBlock).where(PlanBlock.user_id == user_id))
            db.execute(delete(SolarRequest).where(SolarRequest.user_id == user_id))
            db.execute(delete(FixedSchedule).where(FixedSchedule.user_id == user_id))
            db.execute(delete(Task).where(Task.user_id == user_id))
            db.execute(delete(CheckIn).where(CheckIn.user_id == user_id))
            db.execute(delete(PlanningCycle).where(PlanningCycle.user_id == user_id))
            db.execute(delete(UserProfile).where(UserProfile.id == user_id))
        # profile이 None이면(재시도) 이미 삭제된 상태 — DB는 그대로 두고 Auth 삭제만 계속한다.

    try:
        supabase_admin_client.delete_auth_user(user_id)
    except RuntimeError as exc:
        raise ApiError(
            500,
            CODE_ACCOUNT_AUTH_DELETION_FAILED,
            "탈퇴 데이터는 삭제됐지만 계정 삭제가 완료되지 않았어요. 다시 시도해 주세요.",
        ) from exc
