# 이음(E-um) Server

FastAPI 기반 이음 MVP 백엔드.

## 로컬 개발 환경

### 1. Python 3.13 가상환경 생성

저장소 루트에서 시작한다. 시스템에 설치된 Python 3.13 이상을 사용해 `apps/server/.venv`를 생성한다.

Windows PowerShell:

```powershell
cd apps\server
py -3.13 -m venv .venv
```

macOS / Linux:

macOS에 Python 3.13이 없으면 [Python 공식 macOS 다운로드](https://www.python.org/downloads/macos/)에서 먼저 설치한다.

```bash
cd "$(git rev-parse --show-toplevel)/apps/server"
python3.13 --version
python3.13 -m venv .venv
```

### 2. 가상환경 활성화

```powershell
.venv\Scripts\Activate.ps1
```

Git Bash를 사용하는 경우:

```bash
source .venv/Scripts/activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

### 3. 개발 의존성 설치

```powershell
python -m pip install -e ".[dev]"
```

### 4. 환경변수 설정

`.env.example`을 복사해 `apps/server/.env`를 만든다. `DATABASE_URL`, `SUPABASE_URL`, `SOLAR_API_KEY`는 기본 서버 동작에 필요하고 `SOLAR_API_KEY`는 서버 기동 시 필수로 검증된다. 계획 변경에는 `GEMINI_API_KEY`, 회원탈퇴에는 `SUPABASE_SERVICE_ROLE_KEY`가 추가로 필요하다. `.env`는 Git에 포함되지 않는다.

`SOLAR_API_KEY`는 팀원마다 [console.upstage.ai](https://console.upstage.ai)에서 개인 계정으로 직접 발급받아 각자의 로컬 `.env`에 넣는다. 팀 공용 키를 만들어 Slack·이메일·커밋 메시지·Issue·PR 본문 등으로 전달하지 않는다.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

macOS / Linux:

```bash
test -f .env || cp .env.example .env
```

### 5. Alembic migration 실행

```powershell
python -m alembic upgrade head
```

### 6. Uvicorn 서버 실행

```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

서버 실행 후 다음 주소를 확인할 수 있다.

- Health Check: http://127.0.0.1:8000/api/v1/health
- API 문서: http://127.0.0.1:8000/docs

### 7. pytest 실행

Uvicorn과 별도 터미널에서 같은 가상환경을 활성화한 뒤 실행한다.

```powershell
python -m pytest -q
```

## 환경변수

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL 연결 문자열 |
| `SUPABASE_URL` | Supabase Access Token의 JWKS 및 issuer 검증에 사용하는 프로젝트 URL |
| `SOLAR_API_KEY` | Upstage SOLAR(Chat Completions) API key. 서버 기동 시 필수로 검증된다 |
| `SOLAR_BASE_URL` | SOLAR API base URL. 비워두면 `https://api.upstage.ai/v1` |
| `SOLAR_MODEL` | 사용할 SOLAR 모델명. 비워두면 `solar-pro2` |
| `GEMINI_API_KEY` | 진행 중 계획의 `CHANGE_INPUT` structured output 생성에 사용하는 Google Gemini API key |
| `GEMINI_MODEL` | 사용할 Gemini 모델명. 비워두면 `gemini-3.6-flash` |
| `SUPABASE_SERVICE_ROLE_KEY` | 회원탈퇴 시 Supabase Auth Admin API(`auth.users` 삭제) 전용. 서버 전용 secret이며 모바일 `.env`/`EXPO_PUBLIC_*`에는 절대 포함하지 않는다 |

실제 값은 `.env.example`이 아니라 로컬 `apps/server/.env`(git 제외)에만 설정한다.
