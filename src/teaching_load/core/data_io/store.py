"""DuckDB persistence: sessions, courses (user choices), snapshots and settings."""

from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR PRIMARY KEY,
    makersboard_uid VARCHAR, ade_uid VARCHAR,
    start_ts TIMESTAMP, end_ts TIMESTAMP, duration_h DOUBLE,
    course_code VARCHAR, course_name VARCHAR, programme VARCHAR,
    location VARCHAR, groups VARCHAR, filiere VARCHAR, formation_type VARCHAR,
    responsable VARCHAR, source VARCHAR,
    first_seen TIMESTAMP, last_seen TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS courses (
    course_code VARCHAR PRIMARY KEY, course_name VARCHAR, programme VARCHAR, included BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS snapshots (
    synced_at TIMESTAMP, n_makersboard INTEGER, n_ade INTEGER, n_sessions INTEGER,
    n_both INTEGER, n_makersboard_only INTEGER, n_ade_only INTEGER, n_marked_deleted INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key VARCHAR PRIMARY KEY, value VARCHAR);
"""


def connect(path: Path | str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the database (creating the schema when writable)."""
    if str(path) != ":memory:" and not read_only:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con


def upsert_sessions(
    con: duckdb.DuckDBPyConnection, df: pd.DataFrame, now: datetime, window_start: date, window_end: date
) -> int:
    """Insert/update consolidated sessions; flag sessions that vanished from the feeds inside the window.

    Returns the number of sessions newly flagged as deleted.
    """
    existing = dict(con.execute("SELECT session_id, first_seen FROM sessions").fetchall())
    new = df.copy()
    new["first_seen"] = [existing.get(sid, now) for sid in new["session_id"]]
    new["last_seen"] = now
    new["is_deleted"] = False
    con.execute("DELETE FROM sessions WHERE session_id IN (SELECT session_id FROM new)")
    cols = ", ".join(new.columns)
    con.execute(f"INSERT INTO sessions ({cols}) SELECT {cols} FROM new")  # noqa: S608 - fixed column names
    before = con.execute("SELECT count(*) FROM sessions WHERE is_deleted").fetchone()[0]  # type: ignore[index]
    con.execute(
        "UPDATE sessions SET is_deleted = TRUE "
        "WHERE last_seen < ? AND start_ts >= ? AND start_ts < ? AND NOT is_deleted",
        [now, datetime.combine(window_start, datetime.min.time()), datetime.combine(window_end, datetime.max.time())],
    )
    after = con.execute("SELECT count(*) FROM sessions WHERE is_deleted").fetchone()[0]  # type: ignore[index]
    return int(after - before)


def sync_courses(con: duckdb.DuckDBPyConnection) -> None:
    """Add any new course code to ``courses`` (included by default), keeping existing user choices."""
    con.execute(
        """
        INSERT INTO courses (course_code, course_name, programme, included)
        SELECT course_code, any_value(course_name), any_value(programme), TRUE
        FROM sessions WHERE course_code NOT IN (SELECT course_code FROM courses)
        GROUP BY course_code
        """
    )


def load_courses(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return the courses table ordered by name."""
    return con.execute("SELECT * FROM courses ORDER BY course_name, course_code").df()


def save_courses(con: duckdb.DuckDBPyConnection, courses: pd.DataFrame) -> None:
    """Persist edits of name / programme / included for existing course codes."""
    for row in courses.itertuples(index=False):
        con.execute(
            "UPDATE courses SET course_name = ?, programme = ?, included = ? WHERE course_code = ?",
            [row.course_name, row.programme, bool(row.included), row.course_code],
        )


def load_sessions(con: duckdb.DuckDBPyConnection, include_deleted: bool = False) -> pd.DataFrame:
    """Return sessions joined with course choices (name, programme and ``included`` come from ``courses``)."""
    where = "" if include_deleted else "WHERE NOT s.is_deleted"
    return con.execute(
        f"""
        SELECT s.session_id, s.start_ts, s.end_ts, s.duration_h, s.course_code,
               coalesce(c.course_name, s.course_name) AS course_name,
               coalesce(c.programme, s.programme) AS programme,
               coalesce(c.included, TRUE) AS included,
               s.location, s.groups, s.filiere, s.responsable, s.source, s.is_deleted
        FROM sessions s LEFT JOIN courses c USING (course_code)
        {where}
        ORDER BY s.start_ts
        """  # noqa: S608 - clause is a fixed literal
    ).df()


def record_snapshot(con: duckdb.DuckDBPyConnection, values: tuple[object, ...]) -> None:
    """Append a synchronisation snapshot row."""
    con.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)", list(values))


def get_setting(con: duckdb.DuckDBPyConnection, key: str, default: str) -> str:
    """Read a setting, falling back to ``default``."""
    row = con.execute("SELECT value FROM settings WHERE key = ?", [key]).fetchone()
    return str(row[0]) if row else default


def set_setting(con: duckdb.DuckDBPyConnection, key: str, value: str) -> None:
    """Create or update a setting."""
    con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", [key, value])
