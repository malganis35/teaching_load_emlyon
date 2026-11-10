"""Fetch both calendars, reconcile them and update the DuckDB database."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import requests
from loguru import logger

from teaching_load.core.config import Settings, get_settings
from teaching_load.core.data_io import store
from teaching_load.core.data_io.ade import parse_ade
from teaching_load.core.data_io.makersboard import parse_makersboard
from teaching_load.core.data_io.models import RawSession
from teaching_load.core.data_io.reconcile import reconcile


@dataclass(frozen=True)
class SyncResult:
    """Counts describing one synchronisation."""

    synced_at: datetime
    n_makersboard: int
    n_ade: int
    n_sessions: int
    n_both: int
    n_makersboard_only: int
    n_ade_only: int
    n_marked_deleted: int


def build_ade_url(base_url: str, start: date, end: date) -> str:
    """Append the date window to the ADE base URL."""
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}firstDate={start.isoformat()}&lastDate={end.isoformat()}"


def fetch(url: str, timeout: float) -> bytes:
    """Download a feed, raising on any HTTP error."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def fetch_sessions(
    url: str,
    parse: Callable[[bytes], list[RawSession]],
    timeout: float,
    retries: int = 4,
    delay_s: float = 5.0,
) -> tuple[bytes, list[RawSession]]:
    """Fetch and parse a feed, retrying while it is empty.

    The Makersboard feed sometimes answers with a valid but empty calendar (cold cache) and
    returns the real events a few seconds later. An empty feed after all retries is an error,
    so that a flaky response can never wipe sessions from the database.
    """
    for attempt in range(1, retries + 1):
        content = fetch(url, timeout)
        sessions = parse(content)
        if sessions:
            return content, sessions
        logger.warning(f"Empty calendar (attempt {attempt}/{retries}), retrying in {delay_s}s")
        if attempt < retries:
            time.sleep(delay_s)
    raise RuntimeError("Feed returned no events after several attempts; nothing was written")


def _archive(settings: Settings, name: str, content: bytes, now: datetime) -> None:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    (settings.raw_dir / f"{name}_{now:%Y%m%d_%H%M%S}.ics").write_bytes(content)


def run_sync(settings: Settings | None = None, now: datetime | None = None) -> SyncResult:
    """Run a full synchronisation. Aborts (nothing written) if either feed cannot be fetched."""
    settings = settings or get_settings()
    now = now or datetime.now()  # noqa: DTZ005 - local naive time, consistent with stored timestamps
    if not settings.makersboard_ical_url or not settings.ade_ical_url:
        raise ValueError("MAKERSBOARD_ICAL_URL and ADE_ICAL_URL must be set in .env")

    con = store.connect(settings.db_path)
    try:
        start = date.fromisoformat(store.get_setting(con, "year_start", settings.default_year_start.isoformat()))
        end = date.fromisoformat(store.get_setting(con, "year_end", settings.default_year_end.isoformat()))

        mb_raw, mb = fetch_sessions(
            settings.makersboard_ical_url, parse_makersboard, settings.http_timeout_s, delay_s=settings.retry_delay_s
        )
        ade_raw, ade = fetch_sessions(
            build_ade_url(settings.ade_ical_url, start, end),
            parse_ade,
            settings.http_timeout_s,
            delay_s=settings.retry_delay_s,
        )
        _archive(settings, "makersboard", mb_raw, now)
        _archive(settings, "ade", ade_raw, now)

        df = reconcile(mb, ade)
        deleted = store.upsert_sessions(con, df, now, start, end)
        store.sync_courses(con)

        counts = df["source"].value_counts()
        result = SyncResult(
            now,
            len(mb),
            len(ade),
            len(df),
            int(counts.get("both", 0)),
            int(counts.get("makersboard_only", 0)),
            int(counts.get("ade_only", 0)),
            deleted,
        )
        store.record_snapshot(con, tuple(result.__dict__.values()))
        logger.info(f"Sync done: {result}")
        return result
    finally:
        con.close()


def main() -> None:
    """CLI entry point (``make sync``)."""
    result = run_sync()
    print(  # noqa: T201
        f"{result.n_sessions} sessions ({result.n_both} matched, {result.n_makersboard_only} Makersboard only, "
        f"{result.n_ade_only} ADE only, {result.n_marked_deleted} marked deleted)"
    )


if __name__ == "__main__":
    main()
