from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(get_database_url())


@lru_cache(maxsize=1)
def get_session_local() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
