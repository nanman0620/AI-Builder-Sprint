# 이음(E-um) Server

FastAPI 기반 이음 MVP 백엔드.

## 로컬 개발 환경 (Windows)

### 1. Python 3.13 가상환경 생성

`apps/server` 디렉터리에서 실행한다. 시스템에 설치된 Python 3.13을 사용해 `.venv`를 생성한다.

```powershell
cd apps\server
py -3.13 -m venv .venv
```

### 2. 가상환경 활성화

```powershell
.venv\Scripts\Activate.ps1
```

Git Bash를 사용하는 경우:

```bash
source .venv/Scripts/activate
```

### 3. 개발 의존성 설치

```powershell
python -m pip install -e ".[dev]"
```

### 4. 환경변수 설정

`.env.example`을 복사해 `apps/server/.env`를 만들고 `DATABASE_URL`과 `SUPABASE_URL`을 모두 설정한다. `.env`는 Git에 포함되지 않는다.

```powershell
copy .env.example .env
```

### 5. Uvicorn 서버 실행

```powershell
uvicorn app.main:app --reload
```

서버 실행 후 `http://127.0.0.1:8000/api/v1/health`에서 Health Check 응답을 확인할 수 있다.

### 6. Alembic migration 실행

```powershell
alembic upgrade head
```

### 7. pytest 실행

```powershell
pytest
```

## 환경변수

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL 연결 문자열 |
| `SUPABASE_URL` | Supabase Access Token의 JWKS 및 issuer 검증에 사용하는 프로젝트 URL |

실제 값은 `.env.example`이 아니라 로컬 `apps/server/.env`(git 제외)에만 설정한다.
