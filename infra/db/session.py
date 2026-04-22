from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from infra.db.config import get_database_url


def create_db_engine(echo: bool = False) -> Engine:
    return create_engine(get_database_url(), echo=echo, future=True)


def create_session_factory(echo: bool = False) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(echo=echo), expire_on_commit=False, future=True)

