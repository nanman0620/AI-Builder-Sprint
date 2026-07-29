from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_database_url

engine = create_engine(get_database_url())
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
