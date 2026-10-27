import os
import uuid
from pathlib import Path

import psycopg
import pytest

from parlament import db

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN_URL = os.environ.get("PARLAMENT_TEST_DATABASE_URL", "postgresql://parlament:parlament@127.0.0.1:5432/postgres")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def database_url():
    """A fresh, migrated PostgreSQL database per test, dropped afterwards."""
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL unavailable ({error}); start it with `docker compose up -d db`")
    name = f"parlament_test_{uuid.uuid4().hex[:10]}"
    admin.execute(f'CREATE DATABASE "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    try:
        with db.connect(url) as conn:
            db.migrate(conn)
        yield url
    finally:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture
def conn(database_url):
    with db.connect(database_url) as connection:
        yield connection
