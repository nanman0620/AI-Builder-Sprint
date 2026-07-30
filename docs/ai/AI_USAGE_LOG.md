# AI 활용 기록

Claude Code 또는 Codex가 분석·기획·설계·구현·테스트·검증·리뷰를 지원한 작업을 기능 단위로 기록한다. 이 문서는 AI가 대신 결정했다는 증명이 아니라, AI의 지원 범위와 사람의 최종 검토를 구분하는 증빙이다.

| 날짜(KST) | 도구·모델 | 작업 단계 | 작업 목적 | 주요 변경 또는 커밋 | 실행한 검증 | 사람의 검토·핵심 결정·남은 일 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | 최종 UI 캡처를 개발 기준에 연결 | 캡처 32장 의미 기반 분류, runtime asset 5개와 reference-only 24개 분리, README·UI_REFERENCE·역할 체크리스트·Issue/PR 규칙 갱신 | 61개 PNG 형식·크기 확인, 최종 화면 흐름 55쪽 텍스트·렌더 대조, Markdown 링크·파일 수·ZIP 검증 | 최종 화면 흐름을 동작 기준으로 유지. 상점·자동 경고 이동·오류 문구·이메일·캘린더 체크 충돌을 보정. 실제 앱 구현과 에뮬레이터 검수는 후속 Issue |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | Git 협업 규칙 보정과 점수별 이음이 자산 연결 | branch·commit·PR·Issue 형식, develop 동기화 명령, 시점 의존 문구, 마감 경고 정렬, 일반 Issue 템플릿 수정. 점수별 runtime asset 4개와 `CHECK_IN_RESULT` 구간·배치·정적 자산 매핑 규칙 추가 | 원본 PDF와 추출 본문·페이지 수 비교, PDF 55·28·95쪽 파싱, PNG 66개 형식 확인, 신규 자산 4개 hash 비교, 금지 문구·필수 규칙 검사, 82개 파일·ZIP 무결성 검사 | 자산명의 0·30·60·100을 각 구간의 하한으로 사용. 30점은 표정 전용이며 60점 피드백·NOT_DONE 재계획은 유지. 실제 팀 포크 URL 반영, 기존 Expo 구조와의 병합, 에뮬레이터 육안 검수는 후속 작업 |
| 2026-07-29 | Claude Code | 설계·구현·검증 | Expo 공통 기반 및 앱 라우팅 구축 | `2fd22f4` feat: Expo 공통 기반 및 앱 라우팅 구축 — Expo Router 인증·탭 Route 뼈대 구축, 하단 탭 4개 구성, `/` 진입 시 `/login` 이동, 공통 디자인 토큰과 공통 컴포넌트 추가, API·Supabase 클라이언트 기반 구성, Expo 기본 데모 파일 정리 | `npx tsc --noEmit` 통과, `npm run lint` 통과, 웹 `/` → `/login` 이동 확인, `/home` 및 하단 탭 전환 확인 | 실제 인증과 bootstrap 연동은 후속 Issue로 분리. 프론트엔드 담당자가 브라우저 동작을 최종 확인 |
| 2026-07-30 | Claude Code / Claude Sonnet 5, ChatGPT / GPT-5.6 Thinking | 설계·구현·테스트·검증·리뷰 | Issue #10 Supabase PostgreSQL 연결 기반 구성 및 `user_profiles` 초기 migration 구현 | SQLAlchemy engine/session과 환경변수 기반 DB 연결(`app/core/config.py`, `app/db/session.py`), `auth.users` 참조용 최소 stub(`app/db/external.py`), 최종 DB 명세 기반 `user_profiles` 모델(`app/models/user_profile.py`), Alembic 초기 구성과 migration(`alembic.ini`, `alembic/env.py`, `alembic/versions/0001_create_user_profiles.py`) — 테이블, CHECK 제약, FK `ON DELETE RESTRICT`, `updated_at` 트리거, RLS, `user_profiles_select_own` 정책 포함. commit `8812567` | `pytest -v` 7 passed·1 warning(기존 health 테스트 유지 확인), `alembic upgrade head --sql`로 오프라인 SQL 사전 검토, 실제 테스트용 Supabase DB에서 `alembic upgrade head` 성공, `alembic current` → `0001_create_user_profiles (head)` 확인, `user_profiles` 테이블·`set_updated_at()` 함수·트리거·RLS·`user_profiles_select_own` 정책 존재 여부 SQL로 확인, `git diff --check` 통과, staged 파일 민감정보 패턴 검사 통과 | 파일별 변경 내용과 실제 migration 실행을 단계마다 사람이 직접 승인. 초기 `.env` 파일이 `DATABASE_URL=` 키 없이 저장돼 있어 형식 확인 중 연결 문자열이 도구 출력에 노출된 사고가 있었으며, 실제 값은 기록하지 않고 DB 비밀번호 즉시 교체 및 `.env` 형식 수정 완료로만 기록한다. 실제 `.env`와 비밀정보는 계속 Git에서 제외됨. PR #15 리뷰 및 팀 포크 `develop` 병합 대기 |
| 2026-07-30 | Claude Code / Claude Sonnet 5 | 설계·구현·테스트·검증 | FE-02 bootstrap 초기 라우팅 및 세션 복원 구현 — 앱 최초 실행 시 Supabase session과 `GET /bootstrap` 응답으로 최초 Route를 결정하고, 포그라운드 복귀 시 현재 탭을 유지한 채 상태만 동기화 | `src/features/bootstrap/types.ts`(bootstrap 응답 camelCase 타입, 온보딩 전 null 허용), `api.ts`(`getBootstrap`), `route.ts`(`resolveInitialRoute`/`resolveAppRoute` 순수 함수, 계획관리 7개·홈 6개 initialScreen 분기, 알 수 없는 값은 오류 처리), `bootstrap-context.tsx`(`BootstrapProvider`/`useBootstrap` — 중복 요청 방지, unmount 후 상태 갱신 방지, 오래된 응답 무시, AUTH_REQUIRED 시 signOut 후 상태 초기화), `components/bootstrap-splash.tsx`(로고 초기 로딩 화면, 기존 `eum-logo.png` 재사용), `route.test.ts`. `app/index.tsx`(session 확인 → bootstrap → 최초 Route `router.replace`, 오류 시 재시도), `app/_layout.tsx`(`BootstrapProvider` 연결, `AppState` 기반 포그라운드 재동기화 훅 추가, 최초 mount는 재동기화로 취급하지 않음), `src/features/auth/services/auth-service.ts`에 `signOut` 최소 공개 함수 1개 추가(FE-01에 없던 함수, AUTH_REQUIRED 정리에 필요해 최소 범위로 추가) | `route.test.ts`를 로컬 `tsc`로 CommonJS 컴파일 후 `node --test`로 실행해 순수 함수 20개 케이스(session 없음/AUTH_REQUIRED/오류/온보딩/계획관리 7종/홈 6종/알 수 없는 화면/success 위임) 모두 통과, `npx tsc --noEmit` 통과, `npm run lint`(`expo lint`) 통과, `npx expo export --platform web`으로 `/`·`/home`·`/plan-management`·`/onboarding` 포함 19개 static route 정적 렌더링·번들 성공 확인(추가 패키지 설치 없이 기존 로컬 Expo 사용) | 백엔드에 `GET /bootstrap`이 아직 구현되어 있지 않음(서버는 `/health`·`/me`만 등록, `apps/server/app/main.py` 확인)을 확인해 서버 코드는 수정하지 않았고 mock API도 만들지 않았다 — 최종 API 명세(`docs/api` PDF 5-1) 기준 타입·API 함수·순수 라우팅 함수·테스트 구조까지만 구현했으며 실제 `GET /bootstrap` 통합 검증은 차단된 상태다. 계획관리 9개 screenMode 세부 UI(FE-03~05)와 홈 6개 상태 세부 UI(FE-06), 탭 포커스 재조회·분기 경계 타이머·EXECUTING polling(FE-09)은 구현하지 않고 기존 `RoutePlaceholder` 기반 계획관리/홈 Route까지만 이동하게 했다. commit·push는 아직 수행하지 않음(사용자 명시 요청 대기) |
| 2026-07-30 | Claude Code / Claude Sonnet 5 | 분석·설계·구현·테스트 | 홈 현재 상태 조회(`GET /home/current`)와 현재 분기 PlanBlock 체크/해제(`PATCH /plan-blocks/{planBlockId}/check-state`) API 구현(`NO_ACTIVE_CYCLE`/`NO_PLANS`/`IN_PROGRESS` 세 상태만, 자동 CheckIn·정산·마감 경고는 제외) | 신규: `app/core/clock.py`(Asia/Seoul aware 시각 주입), `app/services/home_service.py`, `app/schemas/home.py`, `app/schemas/plan_block.py`, `app/api/v1/home.py`, `app/api/v1/plan_blocks.py`, `tests/test_clock.py`, `tests/test_home_service.py`, `tests/test_home_api.py`, `tests/test_plan_blocks_api.py`. 수정: `app/services/plan_block_service.py`(`get_active_planning_cycle`, `list_current_period_plan_blocks`, `PlanBlockProgress`/`compute_plan_block_progress`, `PlanBlockCheckStateResult`/`set_plan_block_check_state`, 공식 오류 코드 3종 추가), `app/main.py`(라우터 2개 등록), `tests/test_plan_block_service.py`(확장). migration·DB 스키마·프론트엔드 변경 없음 | 로컬에 Python 3.13이 없어(시스템 python3은 3.9.6이며 pyenv/asdf/uv/docker 모두 미설치) `pytest`를 실제로 실행하지 못했다. 대신 `python3 -m py_compile`로 신규·수정 파일 13개 전체의 문법 오류만 확인(통과) — import/실행 검증은 아님. 사용자에게 Python 3.13/uv 설치 여부를 확인 후 실제 `pytest` 실행 결과를 별도 행으로 추가할 예정 | 계획 단계에서 응답 필드 구성(`serverTime`/`activeCycle`/`blockingNotice`/`finalizing`/`checkInResult` 포함 10개 키 골격, `PlanBlockOut`에 `taskId` 포함, check-state 응답을 `{planBlock, progress}` 중첩 구조로 재계산), clock 함수의 Asia/Seoul 기준 여부, `CheckStateRequest.checked`의 `StrictBool` 적용, PATCH 경로의 OpenAPI `planBlockId` 노출(`Path(alias=...)`)까지 사용자가 파일 단위로 diff를 검토·승인. **실제 `pytest` 실행과 결과 검증은 아직 완료되지 않은 상태이며, 이 log 행 자체가 "테스트 완료"를 의미하지 않는다** |

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
