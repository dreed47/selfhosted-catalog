"""SQLite models. The database file lives in ./data, same idea as iptv-manager."""
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config

logger = logging.getLogger(__name__)

os.makedirs(config.DATA_DIR, exist_ok=True)

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Thread(Base):
    __tablename__ = "threads"
    id = Column(String(20), primary_key=True)  # reddit post id
    title = Column(String(300), nullable=False)
    week_label = Column(String(80), nullable=False, default="")
    permalink = Column(String(400), nullable=False, default="")
    created_utc = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="partial")  # partial, open, complete
    project_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    comment_id = Column(String(32), unique=True, nullable=False, index=True)
    thread_id = Column(String(20), ForeignKey("threads.id"), nullable=False, index=True)
    author = Column(String(80), nullable=False, default="")
    score = Column(Integer, nullable=False, default=0)
    created_utc = Column(DateTime, nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    summary = Column(Text, nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    repo_url = Column(String(400), nullable=True)
    website_url = Column(String(400), nullable=True)
    github_owner = Column(String(120), nullable=True)
    github_repo = Column(String(120), nullable=True)
    category = Column(String(40), nullable=False, default="Uncategorized", index=True)
    category_source = Column(String(20), nullable=False, default="post")
    topics = Column(String(500), nullable=False, default="")
    language = Column(String(40), nullable=True, index=True)
    stars = Column(Integer, nullable=True, index=True)
    forks = Column(Integer, nullable=True, index=True)
    license = Column(String(40), nullable=True)
    github_description = Column(Text, nullable=True)
    github_pushed_at = Column(DateTime, nullable=True)
    archived = Column(Integer, nullable=False, default=0)
    github_status = Column(String(20), nullable=False, default="none", index=True)
    github_error = Column(String(300), nullable=True)
    permalink = Column(String(400), nullable=False, default="")
    source = Column(String(20), nullable=False, default="megathread")  # megathread, feed
    feed_permalink = Column(String(400), nullable=True)


class Favorite(Base):
    """A saved search term or category. One catalog, no accounts."""
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("kind", "value"),)
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)  # search, category
    value = Column(String(200), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    reason = Column(String(40), nullable=False, default="")
    status = Column(String(20), nullable=False, default="running")
    message = Column(Text, nullable=False, default="")
    threads_seen = Column(Integer, nullable=False, default=0)
    projects_upserted = Column(Integer, nullable=False, default=0)


def _add_column(conn, table, name, ddl):
    have = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    if name not in have:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_forks ON projects (forks)"))
        _add_column(conn, "projects", "source", "VARCHAR(20) NOT NULL DEFAULT 'megathread'")
        _add_column(conn, "projects", "feed_permalink", "VARCHAR(400)")
        conn.commit()
    logger.info("Database ready at %s", config.DB_PATH)
