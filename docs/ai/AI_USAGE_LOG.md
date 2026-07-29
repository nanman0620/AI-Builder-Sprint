# AI 활용 기록

Claude Code 또는 Codex가 분석·기획·설계·구현·테스트·검증·리뷰를 지원한 작업을 기능 단위로 기록한다. 이 문서는 AI가 대신 결정했다는 증명이 아니라, AI의 지원 범위와 사람의 최종 검토를 구분하는 증빙이다.

| 날짜(KST) | 도구·모델 | 작업 단계 | 작업 목적 | 주요 변경 또는 커밋 | 실행한 검증 | 사람의 검토·핵심 결정·남은 일 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | 최종 UI 캡처를 개발 기준에 연결 | 캡처 32장 의미 기반 분류, runtime asset 5개와 reference-only 24개 분리, README·UI_REFERENCE·역할 체크리스트·Issue/PR 규칙 갱신 | 61개 PNG 형식·크기 확인, 최종 화면 흐름 55쪽 텍스트·렌더 대조, Markdown 링크·파일 수·ZIP 검증 | 최종 화면 흐름을 동작 기준으로 유지. 상점·자동 경고 이동·오류 문구·이메일·캘린더 체크 충돌을 보정. 실제 앱 구현과 에뮬레이터 검수는 후속 Issue |
| 2026-07-29 | Codex / GPT-5.6 Sol | 분석·설계·검증 | Git 협업 규칙 보정과 점수별 이음이 자산 연결 | branch·commit·PR·Issue 형식, develop 동기화 명령, 시점 의존 문구, 마감 경고 정렬, 일반 Issue 템플릿 수정. 점수별 runtime asset 4개와 `CHECK_IN_RESULT` 구간·배치·정적 자산 매핑 규칙 추가 | 원본 PDF와 추출 본문·페이지 수 비교, PDF 55·28·95쪽 파싱, PNG 66개 형식 확인, 신규 자산 4개 hash 비교, 금지 문구·필수 규칙 검사, 82개 파일·ZIP 무결성 검사 | 자산명의 0·30·60·100을 각 구간의 하한으로 사용. 30점은 표정 전용이며 60점 피드백·NOT_DONE 재계획은 유지. 실제 팀 포크 URL 반영, 기존 Expo 구조와의 병합, 에뮬레이터 육안 검수는 후속 작업 |
| 2026-07-30 | Claude Code / Claude Sonnet 5, ChatGPT / GPT-5.6 Thinking | 설계·구현·테스트·검증·리뷰 | Issue #10 Supabase PostgreSQL 연결 기반 구성 및 `user_profiles` 초기 migration 구현 | SQLAlchemy engine/session과 환경변수 기반 DB 연결(`app/core/config.py`, `app/db/session.py`), `auth.users` 참조용 최소 stub(`app/db/external.py`), 최종 DB 명세 기반 `user_profiles` 모델(`app/models/user_profile.py`), Alembic 초기 구성과 migration(`alembic.ini`, `alembic/env.py`, `alembic/versions/0001_create_user_profiles.py`) — 테이블, CHECK 제약, FK `ON DELETE RESTRICT`, `updated_at` 트리거, RLS, `user_profiles_select_own` 정책 포함. commit `8812567` | `pytest -v` 7 passed·1 warning(기존 health 테스트 유지 확인), `alembic upgrade head --sql`로 오프라인 SQL 사전 검토, 실제 테스트용 Supabase DB에서 `alembic upgrade head` 성공, `alembic current` → `0001_create_user_profiles (head)` 확인, `user_profiles` 테이블·`set_updated_at()` 함수·트리거·RLS·`user_profiles_select_own` 정책 존재 여부 SQL로 확인, `git diff --check` 통과, staged 파일 민감정보 패턴 검사 통과 | 파일별 변경 내용과 실제 migration 실행을 단계마다 사람이 직접 승인. 초기 `.env` 파일이 `DATABASE_URL=` 키 없이 저장돼 있어 형식 확인 중 연결 문자열이 도구 출력에 노출된 사고가 있었으며, 실제 값은 기록하지 않고 DB 비밀번호 즉시 교체 및 `.env` 형식 수정 완료로만 기록한다. 실제 `.env`와 비밀정보는 계속 Git에서 제외됨. PR #15 리뷰 및 팀 포크 `develop` 병합 대기 |

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
