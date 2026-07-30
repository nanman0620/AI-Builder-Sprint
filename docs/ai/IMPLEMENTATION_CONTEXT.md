# 이음(E-um) MVP 구현 컨텍스트

이 문서는 최종 화면 흐름, UI 캡처, API 명세, DB 구조, ERD를 구현 작업용으로 압축한 탐색 문서다. Claude와 Codex가 매 작업마다 원본 전체를 다시 읽지 않도록 만든 요약이며, 원본 계약을 대체하지 않는다.

## 문서 권한과 동기화

- 정확한 요청·응답 JSON은 최종 API 명세서가 우선한다.
- 정확한 컬럼·SQL 제약·트랜잭션은 최종 DB 구조 문서가 우선한다.
- 화면 존재·상태·문구·내비게이션·API 동작은 최종 화면 흐름 PDF가 우선한다.
- 색상·간격·배치·컴포넌트 외형은 `docs/design/UI_REFERENCE.md`와 연결된 캡처를 참고한다.
- 캡처와 최종 계약의 확인된 차이는 `UI_REFERENCE.md`의 보정 표를 따른다.
- 이 문서와 원본 PDF가 충돌하면 원본 PDF를 따른다.
- 원본 PDF가 변경되면 이 파일도 같은 PR에서 갱신한다.
- 이 문서에 없는 기능은 임의로 구현하지 않는다.
- 이 문서는 구현 탐색을 위한 요약이며 원본 계약을 대체하지 않는다.

목표 문서 경로:

- `docs/api/이음_MVP_최종_API_명세서.pdf`
- `docs/database/이음_MVP_최종_DB_구조.pdf`
- `docs/database/ERD.png`
- `docs/design/이음_MVP_최종_화면_흐름.pdf`
- `docs/design/UI_REFERENCE.md`
- `docs/design/ui/screens/`

위 경로는 목표 구조를 기준으로 한 것이다. 실제 저장소의 파일명이나 경로가 다를 수 있으므로 최종 적용 전에 `rg --files docs`로 실제 경로를 확인하고 이 문서의 링크와 반드시 맞춘다. 파일을 찾지 못하면 비슷한 이름을 임의로 추측하지 않는다.

## 0. 문서 사용법

- 화면 작업: `docs/design/UI_REFERENCE.md`와 `4`, `5`, `8`, `9`, `12`절을 먼저 읽는다.
- API client 또는 endpoint 작업: `2`, `3`, `6`, `7`, `11`절을 읽는다.
- migration·repository·Worker 작업: `2`, `7`, `10`, `11`절을 읽는다.
- 정확한 요청/응답 JSON, SQL 제약, 화면 문구가 필요하면 해당 최종 PDF를 확인한다.
- 새 기능 아이디어가 이 문서에 없으면 구현하지 말고 원본과 사용자에게 확인한다.

### 최종 기준의 역할

| 영역 | 최종 기준 | 이 문서의 역할 |
| --- | --- | --- |
| HTTP·DTO·오류 | `docs/api/이음_MVP_최종_API_명세서.pdf` | endpoint 탐색·핵심 계약 요약 |
| 스키마·Worker | `docs/database/이음_MVP_최종_DB_구조.pdf` | 테이블·상태·트랜잭션 요약 |
| 화면·내비게이션·동작 | `docs/design/이음_MVP_최종_화면_흐름.pdf` | 모드·탭·복원 규칙 요약 |
| UI 시각 구현 | `docs/design/UI_REFERENCE.md`, `docs/design/ui/screens/` | 캡처 매핑·보정·asset 경계 |
| 관계 | `docs/database/ERD.png` | 관계 시각 탐색 |

### UI 이미지와 코드 경계

- 화면 캡처는 시각 참고이며 앱 bundle에 포함하지 않는다.
- `docs/design/ui/reference-only/`의 버튼·입력·탭·게이지 조각은 코드 컴포넌트 참고용이고 import 금지다.
- 이 agent-kit이 제품 화면용 runtime brand 자산으로 추가하는 파일은 `apps/mobile/assets/brand/`의 로고와 마스코트 아홉 개다. 기존 Expo 프로젝트의 앱 아이콘·스플래시 등 설정 자산은 이 제한 대상이 아니며, 삭제하거나 사용 금지 대상으로 해석하지 않는다.
- 캡처 하나를 Route 하나로 해석하지 않는다. 홈과 계획관리는 서버 상태·`screenMode` variant로 구현한다.
- 점수·날짜·닉네임·이메일·할 일·고정 일정은 응답 데이터로 렌더링하고 캡처 값을 고정하지 않는다.
- CheckIn 결과의 마스코트는 점수 구간별 runtime asset을 선택하며, 점수 게이지 자체는 코드로 그린다.
- 캡처의 status bar와 home indicator는 native Safe Area·status bar를 사용한다.

## 1. 제품과 기술 경계

- 제품: AI가 사용자의 할 일과 고정 일정을 수집해 7일 계획을 분기별 PlanBlock으로 배치하고, 분기마다 자동 정산·재계획하는 앱.
- Mobile: React Native + Expo + TypeScript.
- Server: FastAPI.
- Auth: Supabase Auth의 이메일·카카오.
- DB: Supabase PostgreSQL, PostgreSQL 15+.
- AI: SOLAR가 자연어를 Task·고정 일정 카드로 구조화하고 부족 정보를 질문하며 PlanBlock 실행 문구를 확정한다.
- 기본 시간대: `Asia/Seoul`.
- FastAPI Base URL: `/api/v1`.
- 외부 API JSON: `camelCase`.
- DB: `snake_case`.
- 날짜: `YYYY-MM-DD`.
- 시각: UTC offset을 포함한 RFC 3339. DB `TIMESTAMPTZ`는 절대 시각으로 저장한다.

## 2. 시간과 공통 계산

### 논리 날짜·분기

| 분기 | 실제 시각 |
| --- | --- |
| `MORNING` | 04:00:00~11:59:59 |
| `AFTERNOON` | 12:00:00~17:59:59 |
| `EVENING` | 18:00:00~다음 날 03:59:59 |

`2026-07-29 02:00+09:00`은 `logicalDate=2026-07-28`, `period=EVENING`이다.

### 마감

- 사용자가 날짜와 시각을 모두 주면 그대로 저장한다.
- 날짜만 주면 해당 날짜 `23:59:59+09:00`.
- 재질문 후에도 모르면 `deadline_at=NULL`.
- cycle 밖의 실제 마감도 그대로 저장하되 배치용 마감은 `min(deadline_at, cycle_end_at)`.
- `cycle_end_at`은 `end_date` 다음 날 04:00 KST.

### 분기 용량

- 각 분기의 기본 PlanBlock 용량은 240분.
- PlanBlock 한 행은 정수 1~240분. 30분 단위 반올림·내림 금지.
- 고정 일정 점유 시간은 분기와 겹치는 구간의 합집합으로 계산한다. 겹치는 고정 일정을 중복 차감하지 않는다.
- 현재 분기는 240분 한도뿐 아니라 현재 시각부터 분기 종료까지의 실제 남은 시간도 반영한다.

미래 분기:

```text
fixed_schedule_occupied_minutes
= 해당 분기와 겹치는 고정 일정 구간 합집합의 실제 분 수

available_period_minutes
= max(0, 240 - fixed_schedule_occupied_minutes)

SUM(해당 미래 분기의 PLANNED.allocated_minutes)
<= available_period_minutes
```

현재 분기:

```text
checked_minutes
= 현재 분기의 CHECKED PlanBlock 시간 합

full_period_fixed_occupied_minutes
= 현재 분기 전체에서 고정 일정이 점유하는 구간 합집합

remaining_capacity_by_limit
= max(
    0,
    240
    - checked_minutes
    - full_period_fixed_occupied_minutes
)

remaining_clock_minutes
= 현재 시각부터 현재 분기 종료까지 남은 실제 분 수

future_fixed_occupied_minutes
= 현재 시각부터 분기 종료까지 고정 일정이 점유할 구간 합집합

remaining_clock_available_minutes
= max(
    0,
    remaining_clock_minutes
    - future_fixed_occupied_minutes
)

available_new_planned_minutes
= min(
    remaining_capacity_by_limit,
    remaining_clock_available_minutes
)

SUM(현재 분기의 새 PLANNED.allocated_minutes)
<= available_new_planned_minutes
```

- 현재 분기는 240분 총량 한도와 현재 시각 이후의 실제 남은 시간 중 더 작은 가용량을 사용한다.
- 현재 `CHECKED` 시간은 240분 총용량에서 차감하지만 현재 시각 이후 새 `PLANNED` 합계에 다시 포함하지 않는다.
- 모든 고정 일정 차감은 실제 겹침 구간의 합집합을 분 단위로 계산한다.

## 3. 인증·보안·공통 API 규칙

- 로그인, 회원가입, 카카오 OAuth, 로그아웃은 Supabase Auth SDK가 담당한다.
- `/health` 외 모든 FastAPI endpoint는 `Authorization: Bearer <Supabase access token>`이 필요하다.
- 클라이언트는 request body나 query에 `userId`를 보내지 않는다.
- 서버는 JWT `sub`를 `user_profiles.id`와 각 테이블 `user_id`로 사용한다.
- 타인의 `requestId`, `planBlockId`, `checkInId`, `taskId`는 리소스 존재 여부를 숨기고 404.
- `user_profiles.id`는 `auth.users.id`와 같은 UUID인 PK/FK다. 회원가입 시 대응 프로필을 생성하고 이메일은 `auth.users.email`에서 읽는다.
- 모든 앱 테이블은 RLS를 켠다. Mobile authenticated 세션은 자기 행만 볼 수 있다.
- 실제 쓰기는 FastAPI가 맡는다. Worker는 신뢰된 backend 연결 또는 service role을 사용한다.
- service-role key는 모바일 bundle에 절대 포함하지 않는다.
- 공통 성공 body는 `{"data": ...}`. 204 응답은 body가 없다.
- 공통 오류 body는 `error.code`, `error.message`, `error.details`, `error.traceId`.
- `X-Request-Id`는 선택적인 로그 추적 헤더다.

### 중복 방지

- 별도 실행 `Idempotency-Key`는 쓰지 않는다.
- execute/retry: `requestId`, 조건부 상태 전이, row/advisory lock.
- 최초 입력·사용자 메시지·결정: `clientEventId`.
- 같은 `clientEventId` 재전송은 같은 요청 안에서 중복 저장하지 않는다.

## 4. 앱 시작·동기화·내비게이션

### 앱 최초 실행 또는 완전 재실행

```text
Supabase session 확인
├─ 없음 → 로그인
└─ 있음 → GET /bootstrap
   ├─ onboardingCompleted=false → 닉네임 생성
   ├─ 현재 SOLAR 요청 있음 → 해당 계획관리 상태
   └─ 요청 없음 → 서버가 계산한 홈 상태
```

초기 화면 우선순위:

1. `NICKNAME_CREATION`
2. 현재 SOLAR 요청의 `COLLECTING / CHANGE_CONFIRMATION / CHANGE_INPUT / FINAL_REVIEW / EXECUTING / EXECUTION_SUCCESS / EXECUTION_FAILED`
3. 홈의 `FINALIZING / CHECK_IN_RESULT / DEADLINE_WARNING / NO_ACTIVE_CYCLE / NO_PLANS / IN_PROGRESS`

### 포그라운드 복귀

- `GET /bootstrap`으로 사용자, 온보딩, SOLAR 요청, 정산, 홈 캐시를 동기화한다.
- 현재 탭은 유지한다.
- SOLAR 결과가 바뀌어도 계획관리 탭으로 강제 이동하지 않는다.
- 세션 만료는 로그인, 온보딩 미완료는 닉네임 생성으로 이동한다.

### 탭 포커스

| 탭 | 재조회 |
| --- | --- |
| 홈 | `GET /home/current` |
| 캘린더 | 현재 범위로 `GET /calendar` |
| 계획관리 | `GET /plan-management/state` |
| 설정 | 필요 시 `GET /me` |

분기 경계 12:00, 18:00, 04:00에 현재 탭의 데이터를 다시 조회하거나 관련 캐시를 무효화한다. 탭을 강제 전환하지 않는다.

### 하단 탭

순서: `캘린더 / 홈 / 계획관리 / 설정`.

하단 탭 없음:

- 로고·초기 로딩, 로그인, 회원가입, 닉네임 생성
- `FINALIZING`, `DEADLINE_WARNING`, `CHECK_IN_RESULT`
- `EXECUTION_SUCCESS`, `EXECUTION_FAILED`
- 전체 네트워크 오류, 회원탈퇴 확인

`EXECUTING`은 하단 탭을 표시하고 다른 탭 이동을 허용한다. 서버 작업은 계속되며 실행 취소·요청 삭제는 불가하다.

## 5. 계획관리 상태 머신

계획관리 Route는 오직 `/plan-management` 하나다.

### 화면 모드 9개

- 계산 모드: `NEW_CYCLE_ENTRY`, `ACTIVE_CYCLE_ENTRY`, `EXECUTION_SUCCESS`, `EXECUTION_FAILED`
- DB 상태와 같은 모드: `COLLECTING`, `CHANGE_CONFIRMATION`, `CHANGE_INPUT`, `FINAL_REVIEW`, `EXECUTING`

계산:

| DB/현재 상태 | 화면 |
| --- | --- |
| 현재 요청 없음 + ACTIVE cycle 없음 | `NEW_CYCLE_ENTRY` |
| 현재 요청 없음 + ACTIVE cycle 있음 | `ACTIVE_CYCLE_ENTRY` |
| request status `COLLECTING` | `COLLECTING` |
| `CHANGE_CONFIRMATION` | `CHANGE_CONFIRMATION` |
| `CHANGE_INPUT` | `CHANGE_INPUT` |
| `FINAL_REVIEW` | `FINAL_REVIEW` |
| `EXECUTING` | `EXECUTING` |
| `COMPLETED` + `result_acknowledged_at IS NULL` | `EXECUTION_SUCCESS` |
| `FAILED` | `EXECUTION_FAILED` |

### 요청 목적

- `NEW_CYCLE`: ACTIVE cycle이 없을 때 새 7일 계획.
- `ACTIVE_CYCLE`: ACTIVE cycle의 Task·고정 일정 추가·수정·삭제.
- ACTIVE cycle이 있는 동안 새 cycle 강제 시작은 불가.

### COLLECTING

최초 분석, 카드 생성, 예상 시간·분량·마감·고정 일정 시각 질문, 모호한 대상 재질문은 모두 같은 `COLLECTING` 상태와 Route다.

같은 화면에서 갱신하는 값:

- `messages`
- `requestItems`
- `currentQuestion`
- `quickReplies`
- `inputPlaceholder`
- `pendingItemId`

질문 종류별 Route나 `ANALYZING`, `TASK_QUESTION` 같은 Enum을 만들지 않는다. 분석 중에는 입력만 잠그고 내부 로딩을 표시한다.

질문 정책:

- 가장 위의 `INFO_MISSING` 카드 하나만 질문한다.
- 첫 번째 “잘 모르겠어요”는 쉽게 재질문.
- 두 번째에도 예상 시간을 모르면 AI 추정.
- 분량을 모르면 `amountSource=UNKNOWN`, `amountText=null`.
- 마감을 모르면 `deadlineAt=null`.
- 고정 일정의 시작·종료 날짜·시각은 정확할 때까지 질문한다.
- 수정·삭제 대상이 모호하면 자동 선택하지 않고 같은 화면에서 재질문한다.

### 전이

```text
COLLECTING --모든 카드 READY--> CHANGE_CONFIRMATION
CHANGE_CONFIRMATION --YES--> CHANGE_INPUT
CHANGE_CONFIRMATION --NO--> FINAL_REVIEW
CHANGE_INPUT --정보 부족--> COLLECTING
CHANGE_INPUT --모든 카드 READY--> CHANGE_CONFIRMATION
FINAL_REVIEW --reopen--> CHANGE_INPUT
FINAL_REVIEW --execute 검증 성공--> EXECUTING
EXECUTING --성공--> COMPLETED
EXECUTING --실제 실행 실패--> FAILED
FAILED --retry 검증 성공--> EXECUTING
```

작성 중 `COLLECTING`, `CHANGE_CONFIRMATION`, `CHANGE_INPUT`, `FINAL_REVIEW`에서 탭 이동·뒤로 가기를 누르면 이탈 확인 팝업을 먼저 표시한다. “계속 작성”은 DB 변경 없음. “내용 삭제”는 DELETE 성공 후에만 이동한다.

`FAILED`도 사용자가 요청 취소 DELETE를 할 수 있다. `EXECUTING`은 삭제·취소 불가.

## 6. FastAPI endpoint 21개

모든 경로 앞에 `/api/v1`을 붙인다.

| # | Method | Path | 역할 |
| ---: | --- | --- | --- |
| 1 | GET | `/health` | 서버 상태, 유일한 비인증 endpoint |
| 2 | GET | `/me` | 프로필 조회 |
| 3 | PUT | `/me/onboarding` | 닉네임 설정·온보딩 완료 |
| 4 | PATCH | `/me/profile` | 닉네임 수정 |
| 5 | GET | `/bootstrap` | 앱 실행·복귀 전체 동기화 |
| 6 | GET | `/plan-management/state` | 계획관리 화면 복원 |
| 7 | POST | `/solar/requests` | 새 SOLAR 요청·최초 분석 |
| 8 | GET | `/solar/requests/{requestId}` | 특정 요청 상세 |
| 9 | DELETE | `/solar/requests/{requestId}` | 작성 중/FAILED 요청 취소 |
| 10 | POST | `/solar/requests/{requestId}/messages` | 질문 답변·변경 자연어 |
| 11 | POST | `/solar/requests/{requestId}/decisions` | YES/NO 결정 |
| 12 | POST | `/solar/requests/{requestId}/reopen` | FINAL_REVIEW→CHANGE_INPUT |
| 13 | POST | `/solar/requests/{requestId}/execute` | 실행 시작, 202 |
| 14 | GET | `/solar/requests/{requestId}/execution` | 실행 상태 조회 |
| 15 | POST | `/solar/requests/{requestId}/retry` | 같은 요청 재실행 |
| 16 | POST | `/solar/requests/{requestId}/acknowledge-result` | 성공 결과 확인 |
| 17 | GET | `/home/current` | 현재 홈 상태 |
| 18 | PATCH | `/plan-blocks/{planBlockId}/check-state` | 현재 분기 체크·해제 |
| 19 | POST | `/tasks/deadline-warnings/acknowledge` | 마감 경고 일괄 확인 |
| 20 | POST | `/check-ins/{checkInId}/acknowledge` | 결과와 이전 결과 확인 |
| 21 | GET | `/calendar` | 범위 캘린더 조회 |

### 주요 요청

- `POST /solar/requests`: `purpose`, `clientEventId`, nonblank `message`.
- `POST /messages`: `clientEventId`, nonblank `message`.
- `POST /decisions`: `clientEventId`, `decision=YES|NO`.
- `PATCH /check-state`: `checked: boolean`.
- 경고 확인: 현재 화면에 보인 모든 `taskIds`.
- calendar: 필수 `from`, `to`; `from <= to`.

### 구현하지 않는 endpoint

- FastAPI 로그인·회원가입·로그아웃.
- `DELETE /me`.
- 비밀번호 찾기·변경.
- 문서 업로드·파싱.
- 반복 일정.
- ACTIVE cycle 강제 종료·교체.
- Task 상세 CRUD와 `PATCH /tasks/{taskId}/remaining-minutes`.
- 단일 Task 마감 경고 확인.
- 별도 active cycle·최근 CheckIn 조회.
- 캘린더 쓰기.

## 7. DB 스키마

Supabase `auth.users`와 앱 DB 9개 테이블만 사용한다.

### Enum

| Enum | 값 |
| --- | --- |
| `plan_cycle_status` | `ACTIVE`, `ENDED` |
| `solar_request_purpose` | `NEW_CYCLE`, `ACTIVE_CYCLE` |
| `solar_request_status` | `COLLECTING`, `CHANGE_CONFIRMATION`, `CHANGE_INPUT`, `FINAL_REVIEW`, `EXECUTING`, `COMPLETED`, `FAILED` |
| `solar_action` | `CREATE`, `UPDATE`, `DELETE` |
| `solar_entity_type` | `TASK`, `FIXED_SCHEDULE` |
| `solar_item_status` | `INFO_MISSING`, `READY`, `EXECUTED` |
| `solar_message_role` | `USER`, `ASSISTANT` |
| `solar_message_kind` | `TEXT`, `QUESTION`, `ERROR`, `DECISION` |
| `plan_period` | `MORNING`, `AFTERNOON`, `EVENING` |
| `task_status` | `ACTIVE`, `COMPLETED`, `CANCELLED` |
| `plan_block_status` | `PLANNED`, `CHECKED`, `COMPLETED`, `NOT_DONE` |
| `estimate_source` | `USER`, `AI_ESTIMATED` |
| `amount_source` | `USER`, `AI_ESTIMATED`, `UNKNOWN` |

### 테이블·정확한 컬럼

| 테이블 | 컬럼 |
| --- | --- |
| `user_profiles` | `id`, `nickname`, `onboarding_completed`, `created_at`, `updated_at` |
| `planning_cycles` | `id`, `user_id`, `start_date`, `end_date`, `status`, `activated_at`, `ended_at`, `created_at`, `updated_at` |
| `solar_requests` | `id`, `user_id`, `plan_cycle_id`, `purpose`, `status`, `raw_input`, `current_item_order`, `confirmed_at`, `execution_started_at`, `executed_at`, `execution_attempt_count`, `execution_result`, `error_code`, `error_message`, `result_acknowledged_at`, `created_at`, `updated_at` |
| `solar_request_items` | `id`, `user_id`, `solar_request_id`, `item_order`, `action`, `entity_type`, `status`, `raw_line_text`, `normalized_payload`, `missing_fields`, `pending_question`, `target_task_id`, `target_fixed_schedule_id`, `executed_at`, `created_at`, `updated_at` |
| `solar_messages` | `id`, `user_id`, `solar_request_id`, `client_event_id`, `sequence_no`, `role`, `kind`, `content`, `metadata`, `created_at` |
| `tasks` | `id`, `user_id`, `plan_cycle_id`, `source_request_item_id`, `title`, `deadline_at`, `amount_text`, `amount_source`, `initial_minutes`, `estimated_minutes`, `estimated_minutes_source`, `remaining_minutes`, `status`, `deadline_warning_acknowledged_at`, `completed_at`, `cancelled_at`, `created_at`, `updated_at` |
| `fixed_schedules` | `id`, `user_id`, `plan_cycle_id`, `source_request_item_id`, `title`, `start_at`, `end_at`, `created_at`, `updated_at` |
| `plan_blocks` | `id`, `user_id`, `plan_cycle_id`, `task_id`, `plan_date`, `period`, `allocated_minutes`, `allocated_amount_text`, `display_title`, `display_order`, `status`, `checked_at`, `check_in_id`, `rescheduled_from_block_id`, `created_at`, `updated_at` |
| `check_ins` | `id`, `user_id`, `plan_cycle_id`, `check_date`, `period`, `total_plan_count`, `completed_plan_count`, `score`, `replan_unplaced_minutes`, `finalization_started_at`, `replanned_at`, `finalized_at`, `result_acknowledged_at`, `created_at` |

### 핵심 UNIQUE

- 사용자당 ACTIVE cycle 1개: partial UNIQUE on `planning_cycles(user_id)` where ACTIVE.
- 사용자당 현재 SOLAR 요청 1개: 작성/실행/FAILED 또는 미확인 COMPLETED를 포함한 partial UNIQUE.
- 요청 카드 순서: `(solar_request_id, item_order)`.
- 메시지 순서: `(solar_request_id, sequence_no)`.
- 메시지 이벤트: `(solar_request_id, client_event_id)` where nonnull.
- 생성 출처: `tasks.source_request_item_id`, `fixed_schedules.source_request_item_id` 각각 nonnull UNIQUE.
- PlanBlock: `(task_id, plan_date, period)`와 `(plan_cycle_id, plan_date, period, display_order)`.
- CheckIn: `(plan_cycle_id, check_date, period)`.

### 상태·필드 동시 제약

- `planning_cycles.ACTIVE`면 `ended_at IS NULL`; `ENDED`면 nonnull.
- `tasks.ACTIVE`: remaining > 0, 완료·취소 시각 null.
- `tasks.COMPLETED`: remaining=0, completed_at nonnull.
- `tasks.CANCELLED`: cancelled_at nonnull, completed_at null.
- `plan_blocks.PLANNED`: checked_at/check_in_id null.
- `CHECKED`: checked_at nonnull, check_in_id null.
- `COMPLETED`: checked_at/check_in_id nonnull.
- `NOT_DONE`: checked_at null, check_in_id nonnull.
- `solar_requests.EXECUTING`: started nonnull, attempt>=1, success/error 필드 null.
- `COMPLETED`: executed/result nonnull, error null.
- `FAILED`: executed/result null, error code/message nonnull.
- `solar_request_items.INFO_MISSING`: missing_fields nonempty, executed_at null.
- `READY`: missing_fields empty, executed_at null.
- `EXECUTED`: missing_fields empty, executed_at nonnull.

상태와 위 연관 필드는 반드시 같은 SQL UPDATE에서 변경한다.

## 8. 홈·PlanBlock·마감 경고

### 홈 우선순위

1. `FINALIZING`: `finalized_at IS NULL` CheckIn.
2. `CHECK_IN_RESULT`: 완료됐고 미확인 CheckIn.
3. `DEADLINE_WARNING`: 선택적 blocking notice.
4. `NO_ACTIVE_CYCLE`.
5. `NO_PLANS`: ACTIVE cycle은 있으나 현재 분기 PlanBlock 없음.
6. `IN_PROGRESS`: 현재 분기 `PLANNED` 또는 `CHECKED` 있음.

조회 API는 정산을 시작하거나 DB를 바꾸지 않는다.
`DEADLINE_WARNING`은 DB Enum이나 독립 `homeMode`가 아니라 기본 홈 위에 우선 표시하는 `blockingNotice`다.

### 진행률

- 완료 개수: 현재 분기 `CHECKED` 수.
- 전체 개수: `PLANNED + CHECKED` 수.
- percentage: checked/total.
- 시간 비율이 아니다.
- 현재 분기에 고정 일정만 있으면 홈은 `NO_PLANS`.

### PlanBlock 실행 문구

- 구조화 시간: `allocated_minutes`.
- 구조화 분량: `allocated_amount_text`.
- 화면 문구 스냅숏: `display_title`.
- `display_title`을 파싱해 구조화 데이터를 복원하지 않는다.
- 홈, CHECK_IN_RESULT, 캘린더는 동일한 저장 문구를 쓴다.
- 같은 행이 `PLANNED↔CHECKED→COMPLETED` 또는 `PLANNED→NOT_DONE`으로 바뀌어도 문구·배정 정보 유지.
- 재계획으로 수정 가능한 현재 미체크·미래 PLANNED를 삭제·재생성할 때만 새 문구를 만든다.
- 과거 `COMPLETED/NOT_DONE`과 현재 `CHECKED`는 이동·삭제·덮어쓰기 금지.
- 같은 Task·날짜·분기의 블록은 한 행으로 합친다.

### Task 실제 남은 시간

정산 전 현재 분기의 CHECKED 시간은 아직 `remaining_minutes`에 반영되지 않았다.

```text
effective_remaining_minutes
= max(0, remaining_minutes - unfinalized_checked_minutes)
```

마감 경고와 ACTIVE_CYCLE 재계획은 이 계산값을 쓴다. DB 컬럼을 새로 만들지 않는다.

### 마감 경고

대상:

- Task ACTIVE, deadline nonnull, remaining > 0.
- 아직 경고 미확인.
- effective remaining이 마감 전 실제 available minutes보다 큼.

반환:

```json
{
  "type": "DEADLINE_WARNING",
  "items": [
    {
      "taskId": "uuid",
      "title": "자료구조 과제",
      "deadlineAt": "2026-07-31T23:59:59+09:00",
      "requiredMinutes": 180,
      "availableMinutes": 120,
      "shortageMinutes": 60
    }
  ]
}
```

- 단일 `blockingNotice.task` 금지.
- requiredMinutes = effective remaining.
- `items` 정렬은 `deadline_at` 오름차순 → `shortage_minutes` 내림차순 → `created_at` 오름차순 → `task.id` 오름차순이다.
- 모든 표시 Task를 `taskIds`로 일괄 확인.
- 다른 사용자/없는 ID가 하나라도 있으면 전체 롤백.
- 이미 확인된 ID 포함은 성공 처리.
- Task의 deadline/remaining/estimated가 의미 있게 바뀌면 acknowledgement를 null로 초기화할 수 있다.
- 자동 타이머로 화면을 넘기거나 acknowledgement를 보내지 않는다. 사용자가 `[현재 계획 보기]`를 누를 때만 일괄 확인한다.

## 9. CheckIn·캘린더

### CheckIn

- 해당 분기 PlanBlock이 1개 이상일 때만 생성한다.
- `finalized_at IS NULL`은 `FINALIZING`.
- 완료 결과는 `total_plan_count`, `completed_plan_count`, `score`, `replan_unplaced_minutes`, `replanned_at`, `finalized_at`.

점수 계산:

```text
score
= ROUND_HALF_UP(
    completed_plan_count * 100.0
    / total_plan_count
  )
```

- `total_plan_count`가 1 이상일 때만 계산한다.
- 정수 나눗셈을 사용하지 않는다.
- 소수점이 정확히 0.5인 경우 올림하는 일반 반올림을 사용한다.
- Python 구현에서는 기본 `round()`에 의존하지 않고 `Decimal`과 `ROUND_HALF_UP`을 사용한다.

예시:

```text
1 / 8 → 13점
2 / 3 → 67점
5 / 7 → 71점
```

점수 경계의 역할:

- 30점은 마스코트 표정 선택 전용이다.
- 60점은 결과 피드백 문구 선택 전용이다.
- 100점은 최고 단계 마스코트 선택 전용이며 별도의 피드백 정책 기준이 아니다.
- 실제 재계획 여부는 점수 구간이 아니라 `NOT_DONE` 존재 여부로 결정한다.
- 100점도 일반 피드백에서는 `score >= 60`에 포함되므로 기존 긍정적 피드백 문구를 사용한다.
- CHECK_IN_RESULT 마스코트는 `0~29 → mascot-score-00.png`, `30~59 → mascot-score-30.png`, `60~99 → mascot-score-60.png`, `100 → mascot-score-100.png`로 선택한다.

`CHECK_IN_RESULT` 피드백 우선순위:

1. `cycleEnded = true`이면 7일 계획 종료 문구를 사용한다.
2. `cycleEnded = false AND score >= 60`이면 긍정적 피드백 문구를 사용한다.
3. `cycleEnded = false AND score < 60`이면 놓친 계획을 다시 이어두었다는 안내 문구를 사용한다.

`cycleEnded = true`이면 점수에 따른 일반 피드백보다 계획 종료 문구를 우선한다.

`CHECK_IN_RESULT` 배치·자산 규칙:

- 배치 순서는 `결과 제목·점수 게이지 → 점수별 이음이 마스코트 → 완료·미완료 개수 → 완료·미완료 PlanBlock 목록`이다.
- 마스코트는 점수 게이지를 대체하지 않는다.
- 마스코트 표시 영역은 128dp × 128dp로 고정하고 화면 가운데에 배치한다.
- 이미지 비율은 React Native `Image`의 `resizeMode="contain"` 또는 Expo Image의 `contentFit="contain"`으로 유지한다.
- 결과 목록은 스크롤할 수 있어야 한다.
- Expo/Metro 호환성을 위해 파일명 문자열을 조합한 동적 `require()`를 사용하지 않는다.
- 네 개의 점수별 마스코트 자산을 정적으로 import 또는 require한 명시적 매핑을 사용한다.
- 결과 상세는 `plan_blocks.check_in_id`의 `COMPLETED`와 `NOT_DONE` 모두.

미확인 결과가 여러 개면 홈은 `ORDER BY finalized_at DESC, id DESC LIMIT 1` 하나만 표시한다.

acknowledge:

- 화면에 표시된 CheckIn과 그보다 오래된 미확인 결과만 같은 시각으로 확인.
- 화면 이후 생성된 더 최근 결과는 건드리지 않음.
- 중복 요청은 멱등이며 새 결과를 추가 확인하지 않음.

### 캘린더

- 조회 전용.
- 기본 선택 날짜는 논리 날짜: 00:00~03:59에는 전날.

| 분기 시점 | PlanBlock | CheckIn | 고정 일정 |
| --- | --- | --- | --- |
| 과거 | `COMPLETED`만, `NOT_DONE` 숨김 | 있으면 실제 score | 겹치는 일정 |
| 현재 | `PLANNED`, `CHECKED` | null | 겹치는 일정 |
| 미래 | `PLANNED` | null | 겹치는 일정 |

- 0점은 실제 CheckIn이 있고 score=0일 때만 표시.
- 미래에 “완료 0개/진행률 0%”를 만들지 않는다.
- 세 종류 데이터가 모두 비면 통합 빈 화면. `emptyReason` 없음.
- 고정 일정은 자정을 넘어도 DB 한 행이고, 응답에서 선택 분기와 겹친 `segmentStartAt/segmentEndAt`을 계산한다.

## 10. 실행·정산 Worker

### execute/retry 사전 검증

공통:

- request 소유권과 상태.
- execute는 `FINAL_REVIEW`, retry는 `FAILED`.
- 동일 request 중복 실행 여부.

`NEW_CYCLE`:

- 실행 직전에도 ACTIVE cycle 부재.

`ACTIVE_CYCLE`:

- 정산 또는 장애 복구가 진행 중이지 않음.
- 대상 cycle이 여전히 ACTIVE.
- 최신 Task·PlanBlock·고정 일정 기준 수정·삭제 대상 유효.

검증 실패:

- execute는 `FINAL_REVIEW`, retry는 `FAILED` 유지.
- attempt/start 시각 변경 없음.
- Worker 등록·실제 계획 변경 없음.

검증 성공:

- 짧은 트랜잭션에서 request row lock과 최종 검증.
- 조건부 `EXECUTING` UPDATE와 attempt 증가.
- 커밋 후에만 Worker 등록.

### 실행 Worker

- requestId session-level advisory lock으로 동시에 하나만 실행.
- server 재시작 시 기존 `EXECUTING` 요청을 동일 Worker로 복구.
- 복구는 새 retry가 아니므로 attempt와 started_at을 다시 늘리지 않는다.

`NEW_CYCLE` 하나의 실행 트랜잭션:

1. ACTIVE cycle 최종 부재 확인.
2. planning cycle 생성.
3. Task·고정 일정 생성.
4. PlanBlock 생성.
5. 카드 `EXECUTED`.
6. request `COMPLETED`와 execution_result.
7. 전체 commit.

`ACTIVE_CYCLE` 하나의 실행 트랜잭션:

1. cycle·대상·재계획 행 lock과 최종 검증.
2. Task 추가·수정·취소.
3. 미래 고정 일정 추가·수정·물리 삭제.
4. 과거 결과와 현재 CHECKED 유지.
5. 현재 미체크 PLANNED와 미래 PLANNED 삭제·재생성.
6. 카드 `EXECUTED`.
7. request `COMPLETED`.
8. 전체 commit.

실제 실행 중 오류:

- 계획·카드·cycle 관련 트랜잭션 전체 rollback.
- 별도 트랜잭션에서 request만 `FAILED`, error code/message 저장.
- 동일 요청·카드는 유지하고 retry.

네트워크에서 execution 조회가 실패해도 DB 상태를 변경하지 않는다. 서버가 실제 `FAILED`를 반환한 경우만 실패 화면.

### 분기 정산 Worker

정시:

- MORNING: 같은 날 12:00.
- AFTERNOON: 같은 날 18:00.
- EVENING: 다음 날 04:00.

정산은 앱 접속과 무관하다. `/bootstrap`, `/home/current`는 읽기 전용.

복구:

- 서버 시작과 정시 Worker 전후에 scan.
- 오래된 `finalized_at IS NULL` CheckIn 재처리.
- 종료 시각이 지났지만 CheckIn 없는 분기 탐지.
- 가장 오래된 장애 대상부터.
- UNIQUE, row lock, cycle/block lock, advisory lock, 트랜잭션으로 중복 방지.

PlanBlock 0개:

- 일반 분기: CheckIn·결과·재계획 없음.
- 마지막 날짜 EVENING: CheckIn 없이 남은 ACTIVE Task CANCELLED, cycle ENDED.

PlanBlock 1개 이상:

1. CheckIn을 `finalized_at=NULL`로 먼저 만들고 commit해 FINALIZING 복원.
2. `CHECKED→COMPLETED`, `PLANNED→NOT_DONE`, 모두 check_in_id 연결.
3. Task remaining을 completed allocated minutes만큼 차감.
4. score 계산.
5. 마지막 EVENING이 아니면 미래 PLANNED 재계획.
6. 마지막 EVENING이면 남은 Task CANCELLED, cycle ENDED.
7. 최종 결과와 finalized_at 저장 후 commit.

cycle 종료 시각과 남은 Task cancelled_at은 논리적 `cycle_end_at`을 사용한다. Task는 다음 cycle로 자동 이월하지 않는다.

## 11. 오류 코드와 화면 처리

| HTTP | code | 핵심 처리 |
| --- | --- | --- |
| 400 | `MALFORMED_REQUEST` | 일반 오류 |
| 401 | `AUTH_REQUIRED` | 로그인 |
| 404 | `PROFILE_NOT_FOUND` | 일반 오류 |
| 404 | `REQUEST_NOT_FOUND` | 현재 화면 유지 |
| 404 | `PLAN_BLOCK_NOT_FOUND` | 체크 원상 복구 |
| 404 | `CHECK_IN_NOT_FOUND` | 홈 재조회 |
| 404 | `TASK_NOT_FOUND` | 경고 유지 |
| 409 | `ACTIVE_REQUEST_EXISTS` | 기존 요청 복원 |
| 409 | `INVALID_REQUEST_STATE` | 서버 상태 재조회 |
| 409 | `ACTIVE_CYCLE_EXISTS` | 현재 계획 수정 안내 |
| 409 | `NO_ACTIVE_CYCLE` | NEW_CYCLE_ENTRY 재조회 |
| 409 | `CYCLE_NOT_ACTIVE` | 요청 수정/취소 |
| 409 | `SETTLEMENT_IN_PROGRESS` | 정산 후 재시도 |
| 409 | `INFORMATION_STILL_MISSING` | COLLECTING 복원 |
| 409 | `BLOCK_NOT_IN_CURRENT_PERIOD` | 기존 체크 유지 |
| 409 | `PERIOD_ALREADY_FINALIZED` | 홈 재조회 |
| 409 | `TARGET_AMBIGUOUS` | COLLECTING 재질문 |
| 422 | `INVALID_NICKNAME` | 인라인 오류 |
| 422 | `INVALID_DATE_RANGE` | 기존 캘린더 유지 |
| 422 | `INVALID_CHECK_STATE` | 체크 원상 복구 |
| 422 | `INVALID_TASK_IDS` | 경고 유지 |
| 422 | `INVALID_FIXED_SCHEDULE_TIME` | COLLECTING 재질문 |
| 429 | `RATE_LIMITED` | 잠시 후 재시도 |
| 503 | `SOLAR_UNAVAILABLE` | 같은 COLLECTING에서 재시도 |
| 200 data | `PLAN_EXECUTION_FAILED` | 서버의 실제 FAILED, 실패 화면 |

일반 오류:

> 정보를 불러오지 못했어요.
>
> 잠시 후 다시 시도해 주세요.

`EXECUTING`·`FINALIZING` 조회 오류:

> 진행 상태를 확인하지 못했어요.
>
> 작업은 계속 진행 중일 수 있어요.

- 최초 조회 실패이고 기존 데이터가 없으면 전체 오류 화면.
- 재조회 실패면 기존 화면·데이터 유지.
- 로그인·회원가입·닉네임 검증은 입력별 인라인 오류이며 프론트 검증 실패 시 요청을 보내지 않는다.
- 로그인 형식이 유효하지만 인증에 실패하면 어느 값이 틀렸는지 단정하지 않고 “이메일 또는 비밀번호를 확인해 주세요.”를 공통 오류로 표시한다.
- 처리 중 버튼은 비활성화한다.

## 12. 설정·시연용 예외·제외 범위

### 실제 동작

- 닉네임 생성: `PUT /me/onboarding`; 중복·글자 수 제한 없음, 공백만 금지.
- 닉네임 수정: `PATCH /me/profile`.
- 이메일은 `auth.users.email` 읽기 전용이며 `user_profiles`에 중복 저장하지 않는다.
- 로그아웃: Supabase `signOut`, local auth와 캐시 초기화.

### 해커톤 시연용 예외

- 비밀번호 찾기: “준비 중” 안내만.
- 비밀번호 변경: 두 입력 일치만 프론트 검증, 실제 Auth·DB 변경 없이 성공 토스트.
- 회원탈퇴: 실제 계정·DB 삭제 없이 local 상태·캐시 초기화, signOut, 완료 안내.

실서비스로 오해해 실제 삭제·변경 API를 추가하지 않는다.

### 최종 제외

- 반복 Task·반복 고정 일정·recurrence 컬럼.
- PDF 업로드·Document Parse·Information Extract.
- 약관 동의 이력 저장.
- ACTIVE cycle 강제 종료·교체.
- Task 상세 수정 화면·직접 CRUD·남은 시간 전용 API.
- 캘린더 체크.
- 홈 고정 일정.
- 상점 Route·API·재화·구매·보상 지급.
- 자동 다음 cycle 생성·자동 Task 이월.
- 화면 Route, 탭 표시, 토스트, 네트워크 문구를 DB 컬럼/Enum으로 저장.
- 질문 종류별 Route/DB 상태.

## 13. 최소 수용 테스트

| 영역 | 반드시 확인할 사례 |
| --- | --- |
| 시간 | 03:59→04:00, 11:59→12:00, 17:59→18:00; 자정 초과 일정 |
| 인증 | token 없음/만료, JWT sub, 타 사용자 모든 ID 404 |
| 온보딩 | nickname null 허용, 공백 거부, 중복 허용 |
| cycle | 정확히 7일, ACTIVE 동시 생성 경쟁, 마지막 EVENING 종료 |
| 계획관리 | 9개 screenMode 복원, 단일 Route, 이탈 DELETE 실패 시 유지 |
| 수집 | multi-line 카드 순서, 두 번 모름, 고정 일정 필수 시각, 모호한 target |
| 중복 | clientEventId, execute double tap, retry double tap, Worker advisory lock |
| 실행 | 사전 검증 실패 무변경, 성공 전체 commit, 실제 오류 전체 rollback |
| 복구 | 서버 재시작의 EXECUTING·FINALIZING 복구와 attempt 불변 |
| PlanBlock | 정수 분, 240분 한도, display_title 불변, 재계획 보존 범위 |
| 체크 | 현재 분기만 `PLANNED↔CHECKED`, 정산 뒤 변경 금지 |
| 정산 | 블록 0개 일반/마지막 분기, score count 기준, NOT_DONE 재계획, 점수 경계 0·29·30·59·60·99·100의 마스코트 선택 |
| CheckIn | 최신 하나 표시, 오래된 결과까지 acknowledge, 새 결과 제외, 멱등 |
| 경고 | effective remaining, 복수 items 정렬, batch 전체 소유권·멱등 |
| 캘린더 | 과거/현재/미래 필터, NOT_DONE 숨김, 실제 score=0, 통합 빈 화면 |
| 네트워크 | execution/home polling 실패가 FAILED/정산 실패로 바뀌지 않음 |
| 내비게이션 | bootstrap 초기 라우팅, foreground 탭 유지, 하단 탭 표시 규칙 |
