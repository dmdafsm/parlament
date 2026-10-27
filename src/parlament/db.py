"""PostgreSQL access: connections and numbered SQL migrations (no ORM)."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources

import psycopg
from psycopg.rows import dict_row

from parlament.config import settings


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or settings().database_url, row_factory=dict_row)


@contextmanager
def transaction(url: str | None = None) -> Iterator[psycopg.Connection]:
    with connect(url) as conn, conn.transaction():
        yield conn


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("parlament") / "migrations"
    files = sorted(item.name for item in folder.iterdir() if item.name.endswith(".sql"))
    return [(name, (folder / name).read_text(encoding="utf-8")) for name in files]


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations in order; each file runs once, in its own transaction."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
    )
    conn.commit()
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name, sql in migration_files():
        if name in done:
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
        applied.append(name)
    return applied


def log_start(conn: psycopg.Connection, source: str, command: str) -> int:
    row = conn.execute(
        "INSERT INTO ingest_log (source, command) VALUES (%s, %s) RETURNING id", (source, command)
    ).fetchone()
    conn.commit()
    return row["id"]


def log_end(conn: psycopg.Connection, log_id: int, status: str, rows: int, error: str | None = None) -> None:
    conn.execute(
        "UPDATE ingest_log SET finished_at = now(), status = %s, rows = %s, error = %s WHERE id = %s",
        (status, rows, error, log_id),
    )
    conn.commit()
