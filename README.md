# 이음(E-um) MVP

이음은 사용자의 할 일과 고정 일정을 AI가 구조화해 7일 계획으로 배치하고, 오전·오후·저녁 분기마다 자동 정산·재계획하는 해커톤 MVP다.

이 폴더는 팀 저장소 루트에 병합할 최종 개발 기준 묶음이다. 적용 시점의 앱·서버 구현 현황은 대상 저장소에서 직접 확인하며, 이미 존재하는 코드는 보존하고 문서와 필요한 자산만 병합한다.

## 기준 문서

| 영역 | 최종 기준 |
| --- | --- |
| 화면 존재·상태·문구·이동·오류 동작 | `docs/design/이음_MVP_최종_화면_흐름.pdf` |
| 화면의 색상·간격·배치·컴포넌트 외형 | `docs/design/UI_REFERENCE.md`와 `docs/design/ui/screens/` |
| HTTP·DTO·상태 코드·오류 코드 | `docs/api/이음_MVP_최종_API_명세서.pdf` |
| DB·Enum·제약·트랜잭션·Worker | `docs/database/이음_MVP_최종_DB_구조.pdf` |
| 테이블 관계 개요 | `docs/database/ERD.png` |
| 에이전트용 구현 요약 | `docs/ai/IMPLEMENTATION_CONTEXT.md` |

화면 캡처는 시각 참고다. 캡처와 최종 화면 흐름이 다르면 `UI_REFERENCE.md`에 기록된 보정 규칙을 적용하며, 캡처의 예시 날짜·닉네임·할 일·점수는 코드에 고정하지 않는다.

## 기술 스택

- Mobile: React Native + Expo + TypeScript
- Server: FastAPI + 서버 Worker
- Auth: Supabase Auth
- DB: Supabase PostgreSQL 15+
- AI: Upstage SOLAR
- Timezone: `Asia/Seoul`

## 목표 구조

```text
.
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── apps/
│   ├── mobile/
│   │   └── assets/brand/
│   └── server/
├── docs/
│   ├── api/
│   ├── database/
│   ├── design/
│   │   ├── UI_REFERENCE.md
│   │   └── ui/
│   └── ai/
└── .github/
```

## 개발 시작

1. 이 묶음을 공식 upstream이 아닌 팀 포크 저장소 루트에 반영한다.
2. `apps/mobile`에 Expo 구조가 이미 있으면 폴더 전체를 덮어쓰지 않는다. 기존 코드를 보존한 채 이 묶음의 문서와 `apps/mobile/assets/brand/` 자산만 병합한다.
3. 대상 저장소의 실제 구조·manifest·실행 명령을 확인하고, README의 구조와 명령을 같은 PR에서 맞춘다.
4. 첫 작업은 작은 Issue로 나눈다. 서버가 아직 없다면 FastAPI 기본 구조와 `GET /api/v1/health`부터 시작한다.
5. 이후 DB 모델·migration, 인증·프로필, SOLAR 수집, 실행 Worker, 홈·정산, 캘린더 순으로 구현한다.
6. UI 작업 전 `docs/design/UI_REFERENCE.md`에서 해당 상태·보정 규칙·점수별 마스코트 자산을 확인한다.
7. 존재하지 않는 실행 명령이나 `.env` 값을 추측해 문서화하지 않는다.

사용자와 에이전트의 역할 구분은 `docs/ai/HUMAN_ACTIONS.md`에 짧게 정리되어 있다.
