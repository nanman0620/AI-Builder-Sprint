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


def get_solar_api_key() -> str:
    solar_api_key = os.environ.get("SOLAR_API_KEY")
    if not solar_api_key or not solar_api_key.strip():
        raise RuntimeError("SOLAR_API_KEY 환경변수가 설정되어 있지 않다.")

    return solar_api_key.strip()


def get_solar_base_url() -> str:
    solar_base_url = os.environ.get("SOLAR_BASE_URL")
    if not solar_base_url or not solar_base_url.strip():
        return "https://api.upstage.ai/v1"

    return solar_base_url.strip().rstrip("/")


def get_solar_model() -> str:
    solar_model = os.environ.get("SOLAR_MODEL")
    if not solar_model or not solar_model.strip():
        return "solar-pro2"

    return solar_model.strip()


def get_gemini_api_key() -> str:
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key or not gemini_api_key.strip():
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되어 있지 않다.")
    return gemini_api_key.strip()


def get_gemini_model() -> str:
    gemini_model = os.environ.get("GEMINI_MODEL")
    if not gemini_model or not gemini_model.strip():
        return "gemini-3.6-flash"
    return gemini_model.strip()
