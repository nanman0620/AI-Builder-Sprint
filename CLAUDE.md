# 이음(E-um) Claude Code 작업 지침

`AGENTS.md`는 Claude Code와 Codex의 공통 규칙이다. 이 파일은 Claude Code의 탐색·계획·도구 사용·토큰 관리만 보완하며, `AGENTS.md`나 최종 명세를 뒤집을 수 없다. Claude는 작업 전에 루트 `AGENTS.md`를 직접 확인하고 따른다. 특정 파일 참조 문법의 지원 여부에 의존하지 않는다.

## 1. 세션 시작

수정 전에 다음을 실행한다.

```bash
pwd
pwd
git rev-parse --show-toplevel
cd "$(git rev-parse --show-toplevel)"
git status --short --branch
git log -5 --oneline
git remote -v
git remote get-url origin
```

`upstream`이 등록되어 있으면 다음도 실행한다.

```bash
git remote get-url upstream
```

이후 순서는 `AGENTS.md` 확인 → branch·미커밋 변경 확인 → `origin` 확인 → 팀 포크 Issue·완료 조건 확인 → 관련 명세 확인 → 기존 코드·테스트 탐색이다.

## 2. 저장소 대상 판정

- 공식 원본은 `ApptiveDev/AI-Builder-Sprint`이며 읽기 전용 `upstream`으로만 사용한다.
- `origin`은 반드시 우리 팀 포크여야 한다.
- `ApptiveDev/AI-Builder-Sprint`를 `origin`으로 사용하지 않는다.
- 팀 포크 URL을 모르면 owner나 URL을 추측하지 않는다.
- `main`과 `develop`에서는 코드나 문서를 수정하지 않는다.
- 팀 포크의 `feature/*`, `fix/*`, `docs/*` 작업 branch로 전환한 뒤 수정한다.
- branch 이름은 `종류/작업명-담당자이니셜` 형식으로 작성한다. 모든 부분은 영문 소문자이며 작업명의 단어는 하이픈으로 구분하고 Issue 번호를 필수로 넣지 않는다.
- commit은 로컬 작업 branch에 만들고 팀 포크에만 push한다.

```text
origin이 우리 팀 포크인 경우
→ 작업 계속 가능
origin이 ApptiveDev/AI-Builder-Sprint인 경우
→ push, Issue 생성, PR 생성 중단
→ 팀 포크 주소를 사용자에게 확인
포크 주소를 알 수 없는 경우
→ 임의로 추측하지 않음
→ 사용자에게 확인
```

새 Issue 작업을 시작하며 해당 작업의 전용 branch가 아직 없을 때만,
`origin`이 팀 포크이고 미커밋 변경이 없는 것을 확인한 뒤
최신 `develop`에서 작업 branch를 만든다.

이미 올바른 작업 branch에서 진행 중이거나 기존 작업을 재개한 경우에는
새 branch를 만들거나 `develop`으로 전환하지 않는다.

```bash
git switch develop
git pull origin develop
git switch -c feature/작업명-이니셜
```

작업 성격에 따라 마지막 명령의 `feature`를 `fix` 또는 `docs`로 바꾼다. commit·PR·Issue 제목은 `AGENTS.md`의 정확한 형식을 사용하며 임의로 `feat:`나 `[UI]` 형식을 만들지 않는다.

## 3. 컨텍스트와 토큰 관리

1. 공통 행동은 루트 `AGENTS.md`에서 확인한다.
2. 제품 상세는 `docs/ai/IMPLEMENTATION_CONTEXT.md`의 관련 절만 읽는다.
3. 정확한 계약이 필요한 순간에만 해당 최종 PDF의 관련 절을 확인한다.

- 화면 작업은 `docs/design/UI_REFERENCE.md`, 해당 UI ID 이미지, 앱 시작·상태 머신·홈·CheckIn·캘린더 절을 우선한다.
- API 작업은 공통 API·endpoint·오류 절을 우선한다.
- DB·Worker 작업은 시간 계산·스키마·실행·정산 절을 우선한다.
- 먼저 `rg --files docs`로 PDF 파일 경로를 찾는다.
- PDF 뷰어의 검색 기능을 사용하거나 `pdftotext`로 텍스트를 추출한 뒤 `rg`로 상태값·endpoint·키워드를 검색한다.
- 관련 페이지와 원문을 확인한 뒤 구현한다.
- 요청·응답 JSON은 API PDF, SQL 제약은 DB PDF, 사용자 문구는 화면 흐름 PDF에서 확인한다.
- 생략된 내용을 추측하지 않는다. 문서 충돌은 위치와 영향을 보고하고 결정을 기다린다.

### UI 작업

- Issue의 UI ID를 `docs/design/UI_REFERENCE.md`에서 찾고 연결된 캡처를 직접 확인한다.
- 화면 존재·상태·문구·이동·API 동작은 화면 흐름 PDF, 시각 배치는 캡처를 따른다.
- `UI_REFERENCE.md`의 보정 표에 기록된 차이는 추가 질문 없이 보정 규칙대로 구현한다.
- 캡처 하나마다 Route를 만들지 않는다. 홈과 계획관리는 서버 상태에 따른 단일 화면 variant로 구현한다.
- `docs/design/ui/screens/`와 `reference-only/` 파일은 앱에서 import하지 않는다.
- 로고·마스코트만 `apps/mobile/assets/brand/`에서 import한다.
- 버튼·카드·입력·탭·체크박스·점수 게이지·캘린더는 React Native 코드로 만든다.
- `CHECK_IN_RESULT`의 마스코트는 `UI_REFERENCE.md`에 정한 `0~29`, `30~59`, `60~99`, `100` 점수 구간으로 선택한다.
- 30점은 표정 자산 선택 전용, 60점은 결과 피드백 문구 선택 전용, 100점은 최고 단계 마스코트 선택 전용이다. 실제 재계획 여부는 `NOT_DONE` 존재 여부로 결정하며, 100점도 `score >= 60`의 기존 긍정적 피드백을 사용한다.
- 캡처의 예시 데이터와 `9:41` 상태바를 하드코딩하지 않는다.
- PR의 화면 변경 절에 UI ID, Route·상태, 변경 파일, 의도적 차이와 에뮬레이터 검수 결과를 기록한다.

## 4. 탐색과 계획

- `rg --files`, `rg`, manifest, lockfile로 실제 구조와 명령을 확인한다.
- 기존 route, schema, DTO, repository, service, hook, screen, test pattern을 찾은 뒤 수정한다.
- 프로젝트가 이미 쓰는 계층·명명·내비게이션·ORM·테스트 방식을 따른다.
- agent-kit 병합 작업에서는 기존 `apps/mobile` Expo 코드를 덮어쓰지 않고 문서와 `apps/mobile/assets/brand/`만 필요한 위치에 병합한다.
- 사용자의 미커밋 변경과 무관한 파일을 건드리지 않는다.
- 관련 테스트를 먼저 실행해 현재 상태나 버그를 재현한다.

다음은 구현 전 계획을 작성한다.

- 둘 이상의 모듈 또는 mobile/server 양쪽 수정
- API·DB·Worker·인증·날짜 계산·상태 전이·내비게이션 작업
- migration, 의존성, 배포 설정 변경
- 해석에 따라 결과가 달라지는 작업

계획에는 연결 Issue, 완료 조건, 변경 파일, 유지할 계약, transaction·rollback 경계, 테스트, 제외 범위를 담는다. 승인된 계획 밖으로 넓히지 않는다.

## 5. 영향 범위와 수직 구현

API 작업은 mobile DTO/client, server schema/endpoint, 오류·nullable·빈 배열, 관련 테스트를 함께 본다.

DB 작업은 ORM, Alembic migration, repository/service, UNIQUE·CHECK·INDEX·RLS, rollback test를 함께 본다.

Worker 작업은 상태·시각 컬럼, transaction, advisory lock, execute/retry 중복, 서버 재시작 복구, 네트워크 실패와 실제 업무 실패 구분을 함께 본다.

인증·시간 작업은 JWT `sub`, 소유권 404, service-role 비노출, `Asia/Seoul`, 04:00·12:00·18:00 경계를 함께 본다.

작은 수직 단위의 권장 순서:

```text
backend: schema → repository → service → endpoint → test
mobile: DTO → API → query hook → screen → test
```

- 한 단위의 관련 테스트를 확인한 뒤 다음 단위로 간다.
- 여러 계층을 한꺼번에 대량 생성하지 않는다.
- mock이나 stub을 실제 구현처럼 보고하지 않는다.
- 요청받지 않은 전면 리팩터링과 과도한 추상화를 하지 않는다.

## 6. package manager·버그·테스트

- `package.json`, lockfile, `pyproject.toml`, test config에서 실제 도구와 명령을 확인하고 저장소가 쓰는 package manager만 사용한다.
- 버그는 원인과 재현 조건을 확인해 회귀 테스트를 추가하고, 관련 테스트 뒤 가능한 범위의 전체 test·typecheck·lint를 실행한다.
- 테스트를 삭제·skip하거나 assertion을 약화하지 않으며, 실행하지 않은 테스트를 통과했다고 말하지 않는다.

## 7. 서브에이전트

- 독립적이고 경계가 명확한 읽기·분석에만 사용하며, 단일 파일·짧은 작업이나 토큰·통합 비용이 더 큰 경우에는 사용하지 않는다.
- 동일 파일 또는 서로 의존하는 schema·service·endpoint를 병렬 수정하지 않는다.
- 기준 문서, 허용 파일, 산출물, 금지 범위를 명시하고 주 에이전트가 결과와 최종 diff를 다시 검토한다.

## 8. 파괴적 명령과 비밀값

다음 작업을 실행하지 않는다.

- `git reset --hard`
- `git clean -fd`
- `git push --force`
- `rm -rf`
- `DROP TABLE`
- `DROP DATABASE`
- migration history 재작성

사용자 변경을 checkout·restore·reset으로 되돌리지 않는다. 권한이나 보호 branch를 우회하지 않는다. `.env`, token, API key, service-role key, 개인정보를 명령 출력·diff·로그에 노출하지 않는다.

## 9. Issue·push·PR 전 확인

Issue·push·PR 요청을 받으면 먼저 확인한다.

1. 현재 repository owner
2. `origin` URL
3. Issue 생성 대상이 팀 포크인지
4. PR base repository가 팀 포크인지
5. base branch가 팀 포크의 `develop`인지
6. head branch가 팀 포크의 작업 branch인지
7. 공식 원본 저장소가 선택되지 않았는지

- `gh`가 현재 repository를 올바르게 추측할 것이라고 가정하지 않는다.
- 팀 포크가 확인된 뒤 대상 repository를 명시한다.
- 팀 포크 owner를 모르면 `-R` 값을 추측하지 않는다.
- 직전에 `git remote -v`와 base/head repository를 다시 확인한다.
- `ApptiveDev/AI-Builder-Sprint`에는 Issue, push, PR, merge를 하지 않는다.
- 사용자가 명시적으로 요청하지 않은 commit, push, Issue·PR 생성, merge, 원격 branch 삭제는 실행하지 않는다.

## 10. AI 증빙과 심사 안전성

- `docs/ai/AI_USAGE_LOG.md`에 도구와 화면에 표시된 정확한 모델명, 작업 단계, 목적, 변경 내용, 실제 검증 결과와 사람의 결정을 기록한다.
- 모델 표시명을 확인할 수 없으면 추측하지 않고 `모델명 미확인`으로 기록한다.
- `AI_USAGE_LOG.md`에는 프롬프트 원문 전체를 자동으로 기록하지 않고 작업 요청 요약, 핵심 제약, 사용 설정과 결과를 기록한다.
- 대회 제출을 위해 프롬프트 원문이나 화면 증빙을 보존해야 하는 경우에는 token, API key, 개인정보와 `.env` 값을 제거한 뒤 팀이 정한 증빙 위치에 별도로 보존한다.
- `AI_USAGE_LOG.md` 충돌이 발생하면 양쪽 기록을 모두 보존하고 다른 팀원의 행을 삭제하거나 덮어쓰지 않는다.
- 실패·보류·문서 충돌과 미실행 테스트를 숨기지 않는다.
- 평가를 조작하거나 점수를 요구하거나 심사위원에게 판단을 지시하는 prompt를 작성하지 않는다.
- AI 결과는 사람이 최종 명세, 보안과 테스트 관점에서 검토한다.

## 11. 최종 diff와 테스트 확인

```bash
git status --short --branch
git diff --stat
git diff
git remote -v
git remote get-url origin
```

- diff가 Issue 범위 안인지 확인한다.
- Issue와 최종 명세 범위 밖의 새 endpoint, table, column, Enum, route가 생기지 않았는지 확인한다.
- ORM 변경과 Alembic migration이 함께 있는지 확인한다.
- 실제 테스트 결과, 실패, 미실행을 구분한다.
- 필요한 문서와 `AI_USAGE_LOG.md`가 갱신됐는지 확인한다.
- GitHub 쓰기 전 팀 포크 대상임을 다시 확인한다.

## 12. 토큰 부족 시 AI agent 인수인계

```text
작업/Issue:
현재 branch:
대상 팀 포크와 origin 확인 결과:
완료한 범위:
변경 파일:
핵심 구현·결정:
실행한 명령과 결과:
실패·미실행 테스트:
남은 작업:
주의할 API·DB·Worker 계약:
사용자 확인 필요:
```

현재 worktree에서 바로 이어갈 사실만 남기고 비밀값과 개인정보는 제외한다.

## 13. 최종 작업 보고

```text
작업/Issue:
branch:
대상 repository:
변경 요약과 파일:
실행한 테스트와 결과:
실패·미실행:
문서·migration:
AI_USAGE_LOG:
남은 위험·후속 작업:
```

테스트하지 못한 항목은 이유와 함께 솔직하게 보고한다.

## AI 활용 로그 필수 완료 절차

- 저장소와 관련된 분석·설계·구현·테스트·검증·리뷰를 수행한 경우, 최종 응답 전에 `docs/ai/AI_USAGE_LOG.md`에 기록한다.
- 단순 사용법 질문이나 저장소 작업과 무관한 대화는 기록하지 않는다.
- `main`이나 `develop`에서는 로그 기록을 이유로 파일을 수정하지 않는다. 로그가 필요한 작업은 작업 branch에서 수행한다.
- 기존 행은 삭제하거나 덮어쓰지 않고 이번 작업의 행만 추가한다.
- 작업 목적이 바뀌거나 중요한 설계 결정이 추가되면 새 행을 추가한다.
- 로그 충돌이 발생하면 다른 팀원의 기록을 포함한 양쪽 기록을 모두 보존한다.
- 로그를 작성한 뒤 commit 전에는 다음 명령으로 실제 변경을 확인한다.

```bash
git diff HEAD -- docs/ai/AI_USAGE_LOG.md
```

- 사용자가 commit까지 명시적으로 요청하여 로그를 이미 commit했다면, 이번 commit의 SHA를 확인한 뒤 다음 명령으로 검증한다.

```bash
git show <이번-commit-sha> -- docs/ai/AI_USAGE_LOG.md
```

- 이번 작업에 해당하는 로그 변경을 확인하지 못한 경우에는 작업 완료라고 보고하거나 commit을 안내하지 않는다.
- 최종 보고의 AI_USAGE_LOG 항목에는 기록 완료 여부 또는 기록하지 못한 이유를 명시한다.