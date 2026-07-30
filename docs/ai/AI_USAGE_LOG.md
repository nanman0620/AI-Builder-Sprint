# AI 활용 기록

Claude Code 또는 Codex가 분석·기획·설계·구현·테스트·검증·리뷰를 지원한 작업을 기능 단위로 기록한다. 이 문서는 AI가 대신 결정했다는 증명이 아니라, AI의 지원 범위와 사람의 최종 검토를 구분하는 증빙이다.

| 날짜(KST) | 도구·모델 | 작업 단계 | 작업 목적 | 주요 변경 또는 커밋 | 실행한 검증 | 사람의 검토·핵심 결정·남은 일 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | 최종 UI 캡처를 개발 기준에 연결 | 캡처 32장 의미 기반 분류, runtime asset 5개와 reference-only 24개 분리, README·UI_REFERENCE·역할 체크리스트·Issue/PR 규칙 갱신 | 61개 PNG 형식·크기 확인, 최종 화면 흐름 55쪽 텍스트·렌더 대조, Markdown 링크·파일 수·ZIP 검증 | 최종 화면 흐름을 동작 기준으로 유지. 상점·자동 경고 이동·오류 문구·이메일·캘린더 체크 충돌을 보정. 실제 앱 구현과 에뮬레이터 검수는 후속 Issue |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | Git 협업 규칙 보정과 점수별 이음이 자산 연결 | branch·commit·PR·Issue 형식, develop 동기화 명령, 시점 의존 문구, 마감 경고 정렬, 일반 Issue 템플릿 수정. 점수별 runtime asset 4개와 `CHECK_IN_RESULT` 구간·배치·정적 자산 매핑 규칙 추가 | 원본 PDF와 추출 본문·페이지 수 비교, PDF 55·28·95쪽 파싱, PNG 66개 형식 확인, 신규 자산 4개 hash 비교, 금지 문구·필수 규칙 검사, 82개 파일·ZIP 무결성 검사 | 자산명의 0·30·60·100을 각 구간의 하한으로 사용. 30점은 표정 전용이며 60점 피드백·NOT_DONE 재계획은 유지. 실제 팀 포크 URL 반영, 기존 Expo 구조와의 병합, 에뮬레이터 육안 검수는 후속 작업 |
| 2026-07-29 | Claude Code | 설계·구현·검증 | Expo 공통 기반 및 앱 라우팅 구축 | `2fd22f4` feat: Expo 공통 기반 및 앱 라우팅 구축 — Expo Router 인증·탭 Route 뼈대 구축, 하단 탭 4개 구성, `/` 진입 시 `/login` 이동, 공통 디자인 토큰과 공통 컴포넌트 추가, API·Supabase 클라이언트 기반 구성, Expo 기본 데모 파일 정리 | `npx tsc --noEmit` 통과, `npm run lint` 통과, 웹 `/` → `/login` 이동 확인, `/home` 및 하단 탭 전환 확인 | 실제 인증과 bootstrap 연동은 후속 Issue로 분리. 프론트엔드 담당자가 브라우저 동작을 최종 확인 |
| 2026-07-30 | Claude Code / Claude Sonnet 5, ChatGPT / GPT-5.6 Thinking | 설계·구현·테스트·검증·리뷰 | Issue #10 Supabase PostgreSQL 연결 기반 구성 및 `user_profiles` 초기 migration 구현 | SQLAlchemy engine/session과 환경변수 기반 DB 연결(`app/core/config.py`, `app/db/session.py`), `auth.users` 참조용 최소 stub(`app/db/external.py`), 최종 DB 명세 기반 `user_profiles` 모델(`app/models/user_profile.py`), Alembic 초기 구성과 migration(`alembic.ini`, `alembic/env.py`, `alembic/versions/0001_create_user_profiles.py`) — 테이블, CHECK 제약, FK `ON DELETE RESTRICT`, `updated_at` 트리거, RLS, `user_profiles_select_own` 정책 포함. commit `8812567` | `pytest -v` 7 passed·1 warning(기존 health 테스트 유지 확인), `alembic upgrade head --sql`로 오프라인 SQL 사전 검토, 실제 테스트용 Supabase DB에서 `alembic upgrade head` 성공, `alembic current` → `0001_create_user_profiles (head)` 확인, `user_profiles` 테이블·`set_updated_at()` 함수·트리거·RLS·`user_profiles_select_own` 정책 존재 여부 SQL로 확인, `git diff --check` 통과, staged 파일 민감정보 패턴 검사 통과 | 파일별 변경 내용과 실제 migration 실행을 단계마다 사람이 직접 승인. 초기 `.env` 파일이 `DATABASE_URL=` 키 없이 저장돼 있어 형식 확인 중 연결 문자열이 도구 출력에 노출된 사고가 있었으며, 실제 값은 기록하지 않고 DB 비밀번호 즉시 교체 및 `.env` 형식 수정 완료로만 기록한다. 실제 `.env`와 비밀정보는 계속 Git에서 제외됨. PR #15 리뷰 및 팀 포크 `develop` 병합 대기 |
| 2026-07-30 | Claude Code / Claude Sonnet 5 | 분석·설계·구현·테스트 | 홈 현재 상태 조회(`GET /home/current`)와 현재 분기 PlanBlock 체크/해제(`PATCH /plan-blocks/{planBlockId}/check-state`) API 구현(`NO_ACTIVE_CYCLE`/`NO_PLANS`/`IN_PROGRESS` 세 상태만, 자동 CheckIn·정산·마감 경고는 제외) | 신규: `app/core/clock.py`(Asia/Seoul aware 시각 주입), `app/services/home_service.py`, `app/schemas/home.py`, `app/schemas/plan_block.py`, `app/api/v1/home.py`, `app/api/v1/plan_blocks.py`, `tests/test_clock.py`, `tests/test_home_service.py`, `tests/test_home_api.py`, `tests/test_plan_blocks_api.py`. 수정: `app/services/plan_block_service.py`(`get_active_planning_cycle`, `list_current_period_plan_blocks`, `PlanBlockProgress`/`compute_plan_block_progress`, `PlanBlockCheckStateResult`/`set_plan_block_check_state`, 공식 오류 코드 3종 추가), `app/main.py`(라우터 2개 등록), `tests/test_plan_block_service.py`(확장). migration·DB 스키마·프론트엔드 변경 없음 | 로컬에 Python 3.13이 없어(시스템 python3은 3.9.6이며 pyenv/asdf/uv/docker 모두 미설치) `pytest`를 실제로 실행하지 못했다. 대신 `python3 -m py_compile`로 신규·수정 파일 13개 전체의 문법 오류만 확인(통과) — import/실행 검증은 아님. 사용자에게 Python 3.13/uv 설치 여부를 확인 후 실제 `pytest` 실행 결과를 별도 행으로 추가할 예정 | 계획 단계에서 응답 필드 구성(`serverTime`/`activeCycle`/`blockingNotice`/`finalizing`/`checkInResult` 포함 10개 키 골격, `PlanBlockOut`에 `taskId` 포함, check-state 응답을 `{planBlock, progress}` 중첩 구조로 재계산), clock 함수의 Asia/Seoul 기준 여부, `CheckStateRequest.checked`의 `StrictBool` 적용, PATCH 경로의 OpenAPI `planBlockId` 노출(`Path(alias=...)`)까지 사용자가 파일 단위로 diff를 검토·승인. **실제 `pytest` 실행과 결과 검증은 아직 완료되지 않은 상태이며, 이 log 행 자체가 "테스트 완료"를 의미하지 않는다** |
| 2026-07-30 | Claude Code / Claude Sonnet 5 | 분석·설계·구현·테스트 | 앱 초기화·동기화 `GET /bootstrap` API 구현. 조사 결과 `GET /me`(router)와 `GET /plan-management/state`(router·schema·service 전체)가 미구현이라는 의존 기능 누락을 먼저 보고했고, 사용자가 "현재 요청 존재 여부만 최소 조회 추가" 범위로 축소 승인 — messages/requestItems/decisionPrompt 등 SOLAR 요청 상세 payload와 `GET /plan-management/state` endpoint 자체는 이번 범위에서 제외 | 신규: `app/services/profile_service.py`(profile·email 읽기 전용 조회, `GET /me` 부재로 기존에 없던 함수를 새로 분리), `app/services/solar_request_service.py`(`get_current_solar_request` — `uq_solar_requests_one_current_per_user` partial unique index와 동일 조건 재사용, `PlanManagementScreenMode` 및 상태→화면모드 순수 변환 함수 2개), `app/services/bootstrap_service.py`(`InitialScreen` Enum, `get_bootstrap_state` 조회 전용 오케스트레이션 — `home_service`/`profile_service`/`solar_request_service` 기존 함수만 호출하고 db.execute/db.begin을 직접 호출하지 않음), `app/schemas/bootstrap.py`(`BootstrapResponse` 등, `home.py`의 `ActiveCycleOut`/`to_active_cycle_out`/`to_home_current_response` 재사용), `app/api/v1/bootstrap.py`, `tests/test_solar_request_service.py`, `tests/test_bootstrap_service.py`, `tests/test_bootstrap_api.py`. 수정: `app/api/v1/me.py`(이메일 조회 중복 SQL을 `profile_service.get_user_email` 호출로 교체, 동작 변경 없음), `app/main.py`(`bootstrap_router` 등록). migration·DB 스키마·프론트엔드 변경 없음 | `./.venv/Scripts/python.exe -m pytest -q`: 200 passed(신규 22건 포함), 1 warning(기존 httpx deprecation, 무관). `test_onboarding_api.py`/`test_home_api.py`/`test_plan_blocks_api.py` 회귀 없음 재확인. 모든 서비스가 조회 전용 fake(`db.begin()` 호출 시 `AssertionError`)로 db 쓰기 부재 검증 | 사용자가 최소 조회 범위(id/purpose/status/resultAcknowledgedAt, 7개 상태→화면모드 매핑)와 제외 범위(messages/requestItems/카드·채팅 조립/`GET /plan-management/state` 자체)를 직접 확정. `planManagement.request`는 의도적으로 축소된 요약 스키마(`SolarRequestSummaryOut`)이며 최종 API 명세의 전체 request 상세(messages/requestItems/currentQuestion/quickReplies/decisionPrompt)는 아직 미구현 — 실제 SOLAR 요청 작성 플로우(`POST /solar/requests` 등 7~16번 endpoint)가 구현되기 전까지는 bootstrap이 이 필드를 완전히 채울 수 없음. home 상태는 `NO_ACTIVE_CYCLE`/`NO_PLANS`/`IN_PROGRESS` 세 가지만 지원(`FINALIZING`/`CHECK_IN_RESULT`/`DEADLINE_WARNING`은 home_service 자체가 미구현). commit·push는 미실행 |

## 작업 단계

- 분석
- 기획
- 설계
- 구현
- 테스트
- 검증
- 리뷰

## 기록 원칙

- 프롬프트 원문을 저장하지 않는다.
- access token, API key, 개인정보, `.env` 값을 기록하지 않는다.
- “테스트 완료”라고만 쓰지 않고 실제 명령 또는 suite와 결과를 적는다.
- 실패·보류·문서 충돌도 숨기지 않는다.
- 같은 날 같은 목적의 연속 작업은 한 줄로 합칠 수 있다.
- 기능 단위나 중요한 설계 결정이 바뀌면 줄을 추가한다.
- 사람이 최종 검토한 내용과 핵심 결정을 AI 지원 내용과 구분해 기록한다.
- `Codex`처럼 도구명만 쓰지 않고 작업 화면에 표시된 실제 모델명까지 함께 적는다. 표시명을 확인할 수 없으면 추측하지 않고 `모델명 미확인`으로 적는다.
- 실제 작업 branch나 팀 포크 정보가 필요한 경우에만 짧게 기록한다.
- 공식 원본 저장소에 작업한 것처럼 오해될 표현을 사용하지 않는다.
- 아직 구현되지 않은 기능이나 실행하지 않은 검증을 완료된 것처럼 기록하지 않는다.
