import os

from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되어 있지 않다.")

    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://"):]
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://"):]

    return database_url


def get_supabase_url() -> str:
    supabase_url = os.environ.get("SUPABASE_URL")
    if not supabase_url or not supabase_url.strip():
        raise RuntimeError("SUPABASE_URL 환경변수가 설정되어 있지 않다.")

    return supabase_url.strip().rstrip("/")
