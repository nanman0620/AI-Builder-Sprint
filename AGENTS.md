# 이음(E-um) 프로젝트 공통 에이전트 규칙

이 파일은 이 저장소에서 작업하는 Claude Code와 Codex가 공통으로 따라야 하는 행동 규칙이다.
제품 구현의 상세 계약은 `docs/ai/IMPLEMENTATION_CONTEXT.md`에서 탐색하고, 정확한 JSON·SQL·사용자 문구는 각 최종 원본 PDF에서 확인한다.

> [!IMPORTANT]
> **PR, Issue, 작업 branch와 commit push는 ApptiveDev/AI-Builder-Sprint가 아니라 반드시 우리 팀이 포크한 저장소에서 처리한다.**

## 1. 프로젝트 목표와 기술 스택

- 목표는 해커톤 기간 안에 이음 MVP의 동결된 핵심 흐름을 시연 가능한 상태로 완성하는 것이다.
- 새 기능을 발명하는 것보다 최종 화면 흐름·API·DB 계약을 정확히 연결하는 것을 우선한다.
- Mobile: React Native + Expo + TypeScript.
- Server: FastAPI와 서버 Worker.
- Auth: Supabase Auth.
- DB: Supabase PostgreSQL, PostgreSQL 15+.
- AI: Upstage SOLAR.
- 기본 시간대: `Asia/Seoul`.
- 상세 화면·API·DB·Worker 규칙은 `docs/ai/IMPLEMENTATION_CONTEXT.md`를 확인한다.
- 정확한 요청·응답 JSON, SQL, 사용자 문구는 최종 원본 PDF를 확인한다.
- 이 문서 또는 구현 컨텍스트에 없는 MVP 기능을 임의로 추가하지 않는다.

## 2. 최종 기준 문서와 권한

| 작업 영역 | 최종 기준 | 용도 |
| --- | --- | --- |
| HTTP 경로, DTO, 상태 코드, 오류 코드 | `docs/api/이음_MVP_최종_API_명세서.pdf` | API 계약 |
| 테이블, 컬럼, Enum, FK, UNIQUE, CHECK, INDEX, 트랜잭션, Worker | `docs/database/이음_MVP_최종_DB_구조.pdf` | DB·서버 계약 |
| 화면 존재·상태·문구·내비게이션·오류 동작 | `docs/design/이음_MVP_최종_화면_흐름.pdf` | 제품·화면 계약 |
| 색상, 간격, 배치, 컴포넌트 외형, 이미지 | `docs/design/UI_REFERENCE.md`, `docs/design/ui/screens/` | 시각 구현 참고 |
| 테이블 관계 개요 | `docs/database/ERD.png` | 관계 탐색 보조 |
| 구현용 요약 | `docs/ai/IMPLEMENTATION_CONTEXT.md` | 빠른 탐색 |

- 정확한 요청·응답 JSON은 최종 API 명세서가 우선한다.
- 정확한 컬럼·SQL 제약·트랜잭션은 최종 DB 구조 문서가 우선한다.
- 화면의 존재·상태·문구·내비게이션·API 동작은 최종 화면 흐름 PDF를 따른다.
- 색상·간격·배치·컴포넌트 외형은 `UI_REFERENCE.md`와 연결된 화면 캡처를 따른다.
- `UI_REFERENCE.md`의 보정 표는 캡처와 최종 계약의 확인된 차이에 대한 구현 규칙이다.
- 그 외 캡처와 최종 계약 충돌은 임의로 합치지 않고 위치·영향·선택지를 보고한다.
- ERD와 구현 컨텍스트는 탐색용이며 원본 계약을 대체하지 않는다.
- 요약 문서와 원본 PDF가 충돌하면 원본 PDF를 따른다.
- 서로 다른 최종 원본끼리 충돌하면 임의로 해석하지 않는다.
- 충돌 위치, 영향 범위, 가능한 선택지를 보고하고 팀 결정을 기다린다.
- 원본 PDF가 변경되면 관련 코드와 `docs/ai/IMPLEMENTATION_CONTEXT.md`를 같은 PR에서 갱신한다.
- 위 경로는 목표 구조다. 실제 저장소에 적용하기 전에 `rg --files docs`로 실제 파일명과 경로를 확인한다.
- 실제 경로가 다르면 링크를 실제 경로와 맞춘다. 파일을 찾지 못한 채 비슷한 문서를 추측해 사용하지 않는다.

## 3. 저장소 구조와 파일 배치 책임

```text
AI-BUILDER-SPRINT/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── apps/
│   ├── mobile/
│   │   └── assets/
│   │       ├── brand/
│   │       └── images/
│   └── server/
├── scripts/
├── docs/
│   ├── api/
│   ├── database/
│   ├── design/
│   │   ├── UI_REFERENCE.md
│   │   └── ui/
│   └── ai/
│       ├── IMPLEMENTATION_CONTEXT.md
│       ├── HUMAN_ACTIONS.md
│       └── AI_USAGE_LOG.md
└── .github/
    ├── ISSUE_TEMPLATE/
    │   ├── ui-feature.md
    │   ├── backend-feature.md
    │   ├── bug.md
    │   └── docs.md
    └── PULL_REQUEST_TEMPLATE.md
```

- 모바일 제품 코드는 `apps/mobile/`에 둔다.
- FastAPI, repository, service, Worker 코드는 `apps/server/`에 둔다.
- 저장소 공용 개발·검증 스크립트만 `scripts/`에 둔다.
- API 원본은 `docs/api/`, DB 원본과 ERD는 `docs/database/`, 화면 원본·UI 참고는 `docs/design/`에 둔다.
- 에이전트용 구현 요약과 AI 활용 기록은 `docs/ai/`에 둔다.
- 앱에서 실제 사용하는 로고·마스코트는 `apps/mobile/assets/brand/`에 둔다.
- 하단 탭 runtime PNG 예외는 `docs/design/UI_REFERENCE.md`에 승인된 여덟 장만 `apps/mobile/assets/images/`에 둔다.
- 앱 전용 스크립트는 해당 앱 내부에 둔다.
- 새 최상위 디렉터리, 프레임워크, ORM, 상태관리 도구, 작업 큐를 임의로 도입하지 않는다.
- 실제 저장소 구조가 예시와 다르면 먼저 기존 구조와 manifest를 확인한다.
- 기존 구조를 무시하고 유사한 디렉터리나 중복 계층을 새로 만들지 않는다.
- Expo 구조가 이미 있는 저장소에 이 agent-kit을 적용할 때는 `apps/mobile` 전체를 덮어쓰지 않는다. 기존 코드를 보존하고 문서, `apps/mobile/assets/brand/` 자산과 승인된 하단 탭 runtime PNG만 필요한 위치에 병합한다.

## 4. GitHub 협업과 저장소 경계

### 저장소 대상 확인

- 공식 upstream은 `ApptiveDev/AI-Builder-Sprint`다.
- 공식 upstream은 운영진이 관리하는 읽기 전용 원본 저장소로 취급한다.
- 모든 쓰기 작업 대상은 우리 팀 포크 저장소다.
- Issue, 작업 branch push, commit push, Pull Request, review 후 merge는 모두 팀 포크 안에서 수행한다.
- upstream은 읽기와 공식 최신 변경 확인 용도로만 사용한다.
- `origin`은 팀 포크, `upstream`은 공식 원본 저장소로 설정한다.
- 공식 원본을 remote로 등록할 때 이름은 `upstream`을 사용한다.
- 공식 원본 저장소에 Issue를 만들지 않는다.
- 공식 원본 저장소에 branch나 commit을 push하지 않는다.
- 공식 원본 저장소를 base repository로 하는 PR을 만들지 않는다.
- 공식 원본 저장소에서 우리 팀 변경을 merge하지 않는다.
- 사용자가 명시적으로 요청하더라도 공식 upstream에는 Issue, branch, commit, PR, merge 등의 쓰기 작업을 수행하지 않는다.
- upstream 관련 쓰기 요청을 받으면 중단하고 팀 포크 저장소에서 처리하도록 안내한다.
- 포크 주소가 확인되지 않으면 임의로 계정명이나 URL을 추측하지 않고 사용자에게 확인한다.
- `origin`이 `ApptiveDev/AI-Builder-Sprint`를 가리키면 push, Issue 생성, PR 생성, merge를 즉시 중단한다.
- Issue, push, PR을 수행하기 직전에 remote와 대상 repository를 다시 확인한다.

작업 시작 시 다음을 실행한다.

```bash
pwd
git status --short --branch
git log -5 --oneline
git remote -v
git remote get-url origin
```

`upstream`이 등록되어 있으면 다음도 실행한다.

```bash
git remote get-url upstream
```

정상 구조의 예:

```text
origin
https://github.com/우리팀계정/AI-Builder-Sprint.git

upstream
https://github.com/ApptiveDev/AI-Builder-Sprint.git
```

비정상 구조의 예:

```text
origin
https://github.com/ApptiveDev/AI-Builder-Sprint.git
```

비정상 상태에서는 GitHub 쓰기 작업을 진행하지 않는다.
팀 포크 URL을 사용자에게 확인한 뒤 remote가 바로잡힌 것을 다시 검증한다.

### 팀 내부 branch 흐름

```text
팀 포크 feature/*, fix/*, docs/*
→ 팀 포크 develop
→ 통합 테스트
→ 팀 포크 main
```

- 공식 원본 저장소에는 이 흐름의 Issue나 PR을 올리지 않는다.
- `main`과 `develop`에 직접 commit하거나 push하지 않는다.
- `main` 또는 `develop`에 있다면 수정 전에 팀 포크의 작업 branch로 전환한다.
- 작업 branch는 팀 포크의 최신 `develop`을 기준으로 만든다.
- 하나의 branch에는 하나의 Issue 또는 하나의 명확한 작업만 담는다.
- 기능은 `feature/*`, 버그 수정은 `fix/*`, 문서는 `docs/*`를 사용한다.
- branch 이름은 `종류/작업명-담당자이니셜` 형식을 사용한다.
- 종류·작업명·담당자 이니셜은 영문 소문자로 작성하고, 작업명의 단어 구분에는 하이픈을 사용한다.
- branch 이름에 Issue 번호를 필수로 넣지 않으며, `feature/123-login-screen-yr`처럼 임의로 번호를 앞에 붙이지 않는다.
- 관련 없는 변경은 같은 branch나 PR에 섞지 않는다.

예:

```text
feature/login-screen-yr
fix/login-error-yr
docs/add-agent-docs-yr
```

작업 branch를 만들기 전에 `origin`이 팀 포크인지와 미커밋 변경을 확인한 뒤 다음 순서를 사용한다.

```bash
git switch develop
git pull origin develop
git switch -c feature/작업명-이니셜
```

마지막 명령의 `feature`는 작업 성격에 따라 `fix` 또는 `docs`로 바꾼다.

### Issue

- 구현 전 팀 포크 저장소에 Issue가 있는지 확인한다.
- Issue도 공식 upstream이 아니라 팀 포크에 생성한다.
- Issue에는 문제, 범위, 제외 범위, 완료 조건을 적는다.
- 요청이 모호하면 완료 조건을 확인하기 전 구현 범위를 넓히지 않는다.
- 하나의 Issue가 지나치게 크면 독립적으로 검증 가능한 단위로 나눈다.
- Issue 제목은 아래 형식을 사용한다.

```text
[Feat] 작업 내용
[Fix] 작업 내용
[Docs] 작업 내용
```

### Commit과 push

- 코드 수정과 로컬 테스트는 수행할 수 있지만, commit, push, Issue 생성, PR 생성은 사용자의 명시적 요청이 있을 때만 수행한다.
- PR merge와 branch 삭제는 사람이 직접 수행하며, 에이전트는 실행하지 않는다.
- commit은 로컬 작업 branch에만 생성한다.
- commit은 한 기능 또는 한 수정 목적의 작은 단위로 나눈다.
- 코드 변경과 그 변경을 검증하는 테스트는 같은 목적의 commit에 포함할 수 있다.
- 무관한 포맷팅, 전면 리팩터링, 설정 변경을 섞지 않는다.
- commit 전 diff와 관련 테스트 결과를 확인한다.
- commit push는 팀 포크의 해당 작업 branch에만 한다.
- remote와 branch가 불명확하면 push하지 않는다.
- 기존 사용자의 commit 기록을 재작성하지 않는다.
- commit 제목은 아래 prefix만 사용한다. 에이전트가 임의로 `feat:` 같은 다른 prefix로 바꾸지 않는다.

```text
feature: 작업 내용
fix: 작업 내용
design: 작업 내용
refactor: 작업 내용
docs: 작업 내용
test: 작업 내용
chore: 작업 내용
rename: 작업 내용
remove: 작업 내용
```

### Pull Request, review, merge

- PR은 팀 포크의 작업 branch에서 팀 포크의 `develop`로 만든다.
- PR 본문에 연결 Issue, 변경 요약, 제외 범위, 테스트 결과, 남은 위험을 적는다.
- PR 제목은 `[타입] 작업 내용` 형식을 사용한다.
- 허용 타입은 `[Feature]`, `[Fix]`, `[Design]`, `[Refactor]`, `[Docs]`, `[Test]`, `[Chore]`, `[Rename]`, `[Remove]`다.
- 최소 한 명의 팀원이 계약과 테스트 결과를 검토한다.
- review 지적을 해결한 뒤 관련 테스트를 다시 실행한다.
- 작업 branch PR은 팀 포크 `develop`에 Squash merge한다.
- 통합 테스트가 끝난 뒤 팀 포크 `develop`에서 팀 포크 `main`으로 승격한다.
- 공식 upstream을 base 또는 merge 대상으로 선택하지 않는다.

### PR 생성 전 확인

- [ ] base repository가 우리 팀 포크인지 확인했다.
- [ ] base branch가 우리 팀 포크의 `develop`인지 확인했다.
- [ ] head repository가 우리 팀 포크인지 확인했다.
- [ ] head branch가 우리 팀 포크의 작업 branch인지 확인했다.
- [ ] `ApptiveDev/AI-Builder-Sprint`가 PR 대상으로 선택되지 않았는지 확인했다.
- [ ] `git remote -v`와 `git remote get-url origin`을 다시 확인했다.

## 5. 작업 시작 순서

1. 현재 디렉터리, branch, 최근 commit, 변경 파일을 확인한다.
2. `git remote -v`와 `origin` URL을 확인한다.
3. `origin`이 팀 포크이고 공식 upstream이 아닌지 확인한다.
4. 팀 포크의 Issue와 완료 조건, 제외 범위를 확인한다.
5. 관련 최종 명세와 `docs/ai/IMPLEMENTATION_CONTEXT.md`의 해당 절을 읽고, UI 작업이면 `docs/design/UI_REFERENCE.md`의 해당 ID를 확인한다.
6. 실제 코드 구조, manifest, lockfile, 유사 구현, 기존 테스트를 탐색한다.
7. 변경 파일, 유지할 계약, 테스트를 포함한 작은 구현 계획을 작성한다.
8. 승인된 범위만 작은 단위로 구현한다.
9. 관련 테스트를 먼저 실행하고 가능한 범위의 정적 검사와 회귀 테스트를 실행한다.
10. 최종 diff, 문서, AI 사용 로그, GitHub 대상 repository를 확인한다.

## 6. 구현 행동 규칙

### 기존 코드를 먼저 탐색

- 이름만 보고 새 파일을 만들지 않는다.
- 기존 route, screen, component, DTO, schema, repository, service, test pattern을 먼저 찾는다.
- 실제 프로젝트가 사용하는 내비게이션, 상태관리, ORM, 테스트 프레임워크를 따른다.
- 기존 구조와 문서 예시가 다르면 계약을 유지하는 범위에서 실제 구조를 따른다.
- 같은 책임의 파일이나 추상화를 중복 생성하지 않는다.
- 화면 캡처 하나마다 Route를 만들지 않고 서버 상태와 `screenMode` variant로 구현한다.
- `docs/design/ui/screens/`와 `reference-only/` 경로의 이미지를 앱 화면·컴포넌트로 직접 import하지 않는다.
- 하단 탭은 `UI_REFERENCE.md`에 승인된 여덟 장의 동일 복사본만 `apps/mobile/assets/images/`에서 runtime 사용한다.
- 승인된 하단 탭 PNG 외의 점수 게이지, 버튼, 카드, 입력창, 탭, 체크박스와 캘린더는 코드로 구현한다.
- CheckIn 결과의 마스코트는 `score`에 따라 `UI_REFERENCE.md`의 네 구간 자산을 선택한다. 30점은 표정 선택 전용, 60점은 결과 피드백 문구 선택 전용, 100점은 최고 단계 마스코트 선택 전용이며, 실제 재계획 여부는 `NOT_DONE` 존재 여부로 결정한다. 100점도 `score >= 60`의 기존 긍정적 피드백을 사용한다.

### 동결 계약 보호

- 명세에 없는 endpoint, table, column, Enum, route를 추가하지 않는다.
- 최종 API 21개를 임의로 추가·삭제·변경하지 않는다.
- 앱 DB 9개 테이블을 임의로 추가·삭제·변경하지 않는다.
- 새로운 MVP 기능을 범위에 추가하지 않는다.
- API·DB 계약 변경은 영향 분석과 팀의 명시적 승인이 필요하다.
- ORM 모델을 바꾸면 대응하는 Alembic migration을 반드시 추가한다.
- 적용된 migration history를 수정하거나 과거 migration을 재작성하지 않는다.
- 정확한 동작이 불분명하면 원본 PDF를 확인하고, 충돌이면 질문한다.

### 변경 범위

- 요청받지 않은 전면 리팩터링을 하지 않는다.
- 해커톤 MVP에 불필요한 범용화와 과도한 추상화를 하지 않는다.
- 단일 사용처를 위해 복잡한 프레임워크나 계층을 추가하지 않는다.
- 사용자 변경과 무관한 파일을 정리하거나 되돌리지 않는다.
- 구현되지 않은 기능을 구현됐다고 문서화하지 않는다.

### 인증·환경변수·보안

- `.env`, access token, API key, service-role key, OAuth secret, 서명 키를 출력하거나 commit하지 않는다.
- 예시는 `.env.example`에 변수 이름과 설명만 남긴다.
- 모바일 bundle에는 service-role key를 절대 포함하지 않는다.
- 클라이언트가 보낸 사용자 ID를 신뢰하지 않고 JWT `sub`를 사용한다.
- 서버와 DB의 소유권 검증을 생략하지 않는다.
- 로그, 테스트 fixture, AI 사용 로그에 실제 비밀값이나 개인정보를 넣지 않는다.

### 네트워크 실패와 업무 실패

- timeout, 연결 실패, polling 실패는 전송·조회 실패다.
- 네트워크 실패만으로 서버의 업무 상태를 `FAILED`로 변경하지 않는다.
- 마지막으로 확인된 화면과 데이터를 가능한 범위에서 유지한다.
- 실제 업무 실패는 서버가 검증된 오류 상태를 저장하거나 계약된 실패 응답을 반환한 경우에만 표시한다.
- 특히 `EXECUTING` 조회 실패를 실행 실패로, `FINALIZING` 조회 실패를 정산 실패로 해석하지 않는다.

## 7. 테스트 규칙

### 공통

- 핵심 도메인 로직, 상태 전이, 날짜 계산, Worker, 버그 수정은 실패 테스트 또는 재현 테스트를 먼저 작성한다.
- 단순 UI 조립과 스타일 변경은 구현 후 component test 또는 실제 앱 smoke test로 검증할 수 있다.
- 버그 수정은 원인을 설명하고 같은 문제가 다시 발생하지 않는 회귀 테스트를 추가한다.
- 테스트를 통과시키려고 기존 테스트를 삭제·skip하지 않는다.
- assertion을 약화하거나 의미 없는 snapshot으로 바꾸지 않는다.
- 테스트 fixture가 최종 API·DB 계약을 우회하지 않게 한다.
- 실행하지 않은 테스트를 통과했다고 말하지 않는다.
- 실패한 테스트와 실행하지 못한 테스트를 최종 보고에서 구분한다.

### Mobile

- 실제 `package.json`과 lockfile에서 package manager와 script를 확인한다.
- 변경한 DTO, API client, query hook, screen, navigation의 관련 테스트를 실행한다.
- 가능하면 typecheck, lint, unit/component test를 실행한다.
- UI 전용 변경도 component/navigation test 또는 실제 앱 smoke test를 남긴다.
- 서버 계약의 `camelCase`, nullable, 빈 배열 처리를 fixture로 검증한다.
- 중복 탭, optimistic update rollback, bootstrap 복원을 관련 작업에서 검증한다.

### Backend

- 실제 설정 파일에서 Python·dependency·test 명령을 확인한다.
- schema, repository, service, endpoint의 관련 unit/integration test를 실행한다.
- ORM 변경 시 새 DB에서 Alembic upgrade가 성공하는지 확인한다.
- 트랜잭션, UNIQUE/CHECK, RLS·소유권, Worker 중복 실행을 관련 작업에서 검증한다.
- 시간 계산은 `Asia/Seoul`의 논리 날짜와 분기 경계를 포함한다.
- execute/retry, 정산, 재시작 복구는 성공뿐 아니라 rollback과 멱등성을 검증한다.

## 8. 계획과 승인

- 둘 이상의 모듈 또는 mobile/server 양쪽을 수정하면 구현 전에 계획을 작성한다.
- API, DB, 인증, 날짜 계산, 상태 전이, Worker, 내비게이션 변경은 구현 전에 영향 범위를 검토한다.
- 의존성, migration, 배포 설정 변경도 계획과 승인이 필요하다.
- 계획에는 변경 파일, 유지할 계약, 테스트, 제외 범위를 포함한다.
- 요구 해석에 따라 결과가 달라지면 추측하지 않고 질문한다.
- 명백한 오탈자나 단순한 한 파일 문서 수정은 짧은 계획으로 바로 처리할 수 있다.

## 9. AI 활용 기록

- 의미 있는 AI 작업은 `docs/ai/AI_USAGE_LOG.md`에 기록한다.
- 같은 날 같은 목적의 연속 작업은 한 줄로 합칠 수 있다.
- 실제 도구와 화면에 표시된 모델명, 단계, 목적, 변경, 실행한 검증, 사람의 결정을 적는다.
- `Codex`처럼 도구명만 적지 말고 `Codex / GPT-5.6 Sol`처럼 확인된 모델명까지 기록한다. 표시명을 확인할 수 없으면 추측하지 않고 `모델명 미확인`으로 적는다.
- 프롬프트 원문, 비밀값, 개인정보는 기록하지 않는다.
- 실패, 보류, 문서 충돌, 실행하지 못한 테스트도 숨기지 않는다.
- 공식 원본 저장소에서 작업한 것처럼 오해될 표현을 쓰지 않는다.

## 10. Claude와 Codex 간 인수인계

- 다음 도구가 같은 branch와 worktree를 이어서 사용할 수 있게 현재 상태를 보존한다.
- 완료된 작업과 미완료 작업을 명확히 구분한다.
- 변경 파일, 핵심 결정, 관련 Issue, 남은 위험을 전달한다.
- 실제 실행한 명령과 결과를 그대로 요약한다.
- 실행하지 않은 테스트는 미실행으로 표시한다.
- 문서 충돌과 사용자 확인이 필요한 항목을 숨기지 않는다.
- 이미 완료된 작업을 이유 없이 다시 만들거나 되돌리지 않는다.
- 비밀값, 인증 정보, 개인 로컬 경로를 인수인계 문서에 넣지 않는다.

권장 인수인계 형식:

```text
작업/Issue:
현재 branch:
대상 repository:
완료:
변경 파일:
핵심 결정:
실행한 검증과 결과:
실패·미실행:
남은 작업:
주의할 계약:
```

## 11. 작업 종료 보고

다음 형식으로 사실만 보고한다.

```text
작업/Issue:
branch:
대상 repository:
변경 요약:
변경 파일:
실행한 테스트:
테스트 결과:
미실행·실패:
문서·migration:
AI_USAGE_LOG:
남은 위험 또는 후속 작업:
```

완료 보고 전 다음을 확인한다.

- 승인된 범위만 변경했는가.
- 최종 API·DB·화면 계약과 일치하는가.
- team fork만 GitHub 쓰기 대상으로 사용했는가.
- `main`과 `develop`에 직접 commit·push하지 않았는가.
- 비밀값과 사용자 변경을 건드리지 않았는가.
- 관련 테스트를 실제로 실행했는가.
- 새 결정과 AI 활용 기록을 갱신했는가.
