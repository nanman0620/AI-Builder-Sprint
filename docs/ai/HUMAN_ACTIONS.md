# 사용자가 직접 할 일

## 지금 할 일

- 친구의 Expo 구조가 `develop`에 들어간 뒤, 에이전트에게 기존 코드를 보존하면서 이 agent-kit의 문서와 `apps/mobile/assets/brand/`만 병합하도록 요청한다.
- `apps/mobile` 전체를 이 묶음으로 덮어쓰지 않는다.
- GitHub 작업을 요청할 때 실제 팀 포크 URL과 대상 branch를 확인한다. 문서의 `우리팀계정` 예시는 주소가 확정될 때만 실제 값으로 교체한다.
- 첫 개발 Issue의 범위와 완료 조건을 승인한다.

화면 캡처 정리, 파일명 변경, 화면-코드 연결표와 문서 수정은 사용자가 직접 하지 않는다. 실제 저장소 구조·실행 명령·추가 자산이 바뀌면 에이전트가 관련 문서를 같은 PR에서 갱신하고 사용자가 결과만 검수한다.

## 개발 중 직접 할 일

- Supabase 프로젝트와 Upstage API key를 발급한다.
- 에이전트가 만든 `.env.example`을 보고 실제 비밀값을 로컬 `.env`에 입력한다.
- Alembic migration의 실제 DB 적용을 승인한다.
- Android 에뮬레이터 또는 실기기에서 화면·문구·터치 동작을 육안 검수한다.
- 명세끼리 새 충돌이 발견되거나 MVP 범위를 바꾸려 할 때 최종 결정을 내린다.
- PR을 검토하고 merge와 branch 삭제를 직접 수행한다.

## 에이전트에게 시킬 일

- React Native + Expo 프로젝트 구조와 화면 구현
- FastAPI 구조, 21개 API, Pydantic, SQLAlchemy, Alembic
- Supabase JWT 검증과 사용자 소유권 처리
- Upstage SOLAR 연동
- 실행 Worker와 분기 정산 Worker
- 자동 테스트, typecheck, lint, 문서와 `.env.example`
- 구현하면서 확정되는 화면 상태와 코드 파일을 PR에 기록

FastAPI도 에이전트 구현 범위다. 사용자는 코드를 처음부터 직접 작성하는 대신 실행 결과, 명세 일치 여부와 UI를 검수한다.

## 에이전트에게 맡기지 않는 일

- 실제 API key·token 입력 또는 출력
- 공식 upstream 쓰기
- PR merge
- branch 삭제
- 명세 충돌의 최종 제품 결정

## 서버가 아직 없을 때 첫 Issue 권장 범위

```text
[Feat] FastAPI 기본 구조와 health endpoint

포함:
- apps/server 기본 구조
- 환경설정 모듈
- GET /api/v1/health
- pytest
- .env.example
- README 실행 명령

제외:
- DB 모델
- Supabase 인증
- SOLAR
- Worker
```
