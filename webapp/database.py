from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    Base.metadata.create_all(bind=engine)
    # Run migrations for new columns
    _run_migrations()


def _run_migrations():
    """Add new columns to existing tables if they don't exist."""
    with engine.connect() as conn:
        # Check if download_options column exists in channels table
        result = conn.execute(text("PRAGMA table_info(channels)"))
        columns = [row[1] for row in result.fetchall()]

        if 'download_options' not in columns:
            conn.execute(text("ALTER TABLE channels ADD COLUMN download_options TEXT"))
            conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

