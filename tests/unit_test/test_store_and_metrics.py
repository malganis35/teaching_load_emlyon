"""Tests for DuckDB persistence, sync safety and workload metrics."""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from teaching_load.core.config import Settings
from teaching_load.core.data_io import store, sync
from teaching_load.core.data_io.ade import parse_ade
from teaching_load.core.data_io.makersboard import parse_makersboard
from teaching_load.core.data_io.reconcile import reconcile
from teaching_load.core.features import workload

NOW = datetime(2026, 11, 9, 12, 0)
START, END = date(2026, 9, 1), date(2027, 8, 31)


def _con_with_data(mb: str, ade: str):  # noqa: ANN202
    con = store.connect(":memory:")
    store.upsert_sessions(con, reconcile(parse_makersboard(mb), parse_ade(ade)), NOW, START, END)
    store.sync_courses(con)
    return con


def test_upsert_is_idempotent_and_keeps_first_seen(mb_ics: str, ade_ics: str) -> None:
    """Syncing twice keeps one row per session and the original first_seen."""
    con = _con_with_data(mb_ics, ade_ics)
    later = datetime(2026, 11, 10)
    store.upsert_sessions(con, reconcile(parse_makersboard(mb_ics), parse_ade(ade_ics)), later, START, END)
    assert con.execute("SELECT count(*) FROM sessions").fetchone()[0] == 4
    first_seen = con.execute("SELECT DISTINCT first_seen FROM sessions").fetchall()
    assert first_seen == [(NOW,)]


def test_vanished_sessions_are_flagged_not_deleted(mb_ics: str, ade_ics: str) -> None:
    """A session missing from a later sync is flagged is_deleted and excluded from default loads."""
    con = _con_with_data(mb_ics, ade_ics)
    smaller = reconcile(parse_makersboard(mb_ics), parse_ade(ade_ics)).iloc[:3]
    deleted = store.upsert_sessions(con, smaller, datetime(2026, 11, 10), START, END)
    assert deleted == 1
    assert len(store.load_sessions(con)) == 3
    assert len(store.load_sessions(con, include_deleted=True)) == 4


def test_course_choices_survive_resync(mb_ics: str, ade_ics: str) -> None:
    """Excluding a course persists and new syncs do not reset it."""
    con = _con_with_data(mb_ics, ade_ics)
    courses = store.load_courses(con)
    courses.loc[courses["course_code"] == "VIS_01", "included"] = False
    store.save_courses(con, courses)
    store.sync_courses(con)
    sessions = store.load_sessions(con)
    assert not sessions.loc[sessions["course_code"] == "VIS_01", "included"].any()
    assert sessions.loc[sessions["course_code"] != "VIS_01", "included"].all()


def test_settings_roundtrip() -> None:
    """Settings fall back to defaults and can be overwritten."""
    con = store.connect(":memory:")
    assert store.get_setting(con, "target_hours", "220") == "220"
    store.set_setting(con, "target_hours", "200")
    assert store.get_setting(con, "target_hours", "220") == "200"


def _sessions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "start_ts": pd.to_datetime(
                ["2026-10-01 08:00", "2026-11-05 08:00", "2026-12-01 08:00", "2027-01-10 08:00"]
            ),
            "end_ts": pd.to_datetime(["2026-10-01 10:00", "2026-11-05 11:00", "2026-12-01 10:00", "2027-01-10 09:00"]),
            "duration_h": [2.0, 3.0, 2.0, 1.0],
            "course_name": ["A", "A", "B", "B"],
            "programme": ["P1", "P1", "P2", "P2"],
        }
    )


def test_summarize() -> None:
    """Realised counts finished sessions; gap is target minus projection."""
    s = workload.summarize(_sessions(), target=10.0, year_end=END, now=NOW)
    assert (s.realised, s.planned_remaining, s.projected) == (5.0, 3.0, 8.0)
    assert s.gap == 2.0 and s.missing_per_week > 0
    assert s.realised_pct == 50.0


def test_summarize_zero_target_and_past_year() -> None:
    """Edge cases do not divide by zero."""
    s = workload.summarize(_sessions(), target=0.0, year_end=date(2026, 1, 1), now=NOW)
    assert s.realised_pct == 0.0 and s.missing_per_week == 0.0


def test_cumulative_curve_and_groupings() -> None:
    """Curve ends at the projected total; realised stops at today; groupings add up."""
    curve = workload.cumulative_curve(_sessions(), START, END, 10.0, NOW)
    assert curve["projected"].iloc[-1] == 8.0
    assert curve["linear"].iloc[-1] == 10.0
    assert curve.loc[curve["date"] > pd.Timestamp(NOW.date()), "realised"].isna().all()
    by_course = workload.hours_by(_sessions(), "course_name", NOW)
    assert by_course.set_index("course_name").loc["A", "total"] == 5.0
    monthly = workload.hours_by_month(_sessions(), NOW)
    assert monthly["total"].sum() == 8.0


def test_hours_by_without_realised_sessions() -> None:
    """Missing status columns are created as zeros."""
    future = _sessions().assign(end_ts=pd.Timestamp("2030-01-01"))
    assert (workload.hours_by(future, "course_name", NOW)["realised"] == 0).all()


def _settings(tmp_path: Path, mb: str = "http://mb", ade: str = "http://ade") -> Settings:
    return Settings(
        makersboard_ical_url=mb,
        ade_ical_url=ade,
        db_path=tmp_path / "t.duckdb",
        raw_dir=tmp_path / "raw",
        retry_delay_s=0,
    )


def test_build_ade_url() -> None:
    """Dates are appended with the right separator."""
    assert sync.build_ade_url("http://x?a=1", START, END).endswith("&firstDate=2026-09-01&lastDate=2027-08-31")
    assert sync.build_ade_url("http://x", START, END).startswith("http://x?firstDate=")


def test_run_sync_end_to_end(tmp_path: Path, mb_ics: str, ade_ics: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sync archives raw files, fills the DB and records a snapshot."""
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: (mb_ics if "mb" in url else ade_ics).encode())
    result = sync.run_sync(_settings(tmp_path), now=NOW)
    assert (result.n_both, result.n_makersboard_only, result.n_ade_only) == (2, 1, 1)
    assert len(list((tmp_path / "raw").glob("*.ics"))) == 2
    con = store.connect(tmp_path / "t.duckdb")
    assert con.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 1


def test_empty_feed_aborts_without_touching_db(tmp_path: Path, mb_ics: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty calendar (flaky feed) raises after retries and never flags sessions as deleted."""
    empty = b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: empty if "mb" in url else mb_ics.encode())
    with pytest.raises(RuntimeError, match="no events"):
        sync.run_sync(_settings(tmp_path), now=NOW)
    assert not (tmp_path / "raw").exists()


def test_empty_feed_recovers_on_retry(monkeypatch: pytest.MonkeyPatch, mb_ics: str) -> None:
    """The first empty answer is retried and the real content is used."""
    answers = iter([b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n", mb_ics.encode()])
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: next(answers))
    _, sessions = sync.fetch_sessions("http://mb", parse_makersboard, 1.0, delay_s=0)
    assert len(sessions) == 3


def test_missing_urls_raise(tmp_path: Path) -> None:
    """Sync refuses to run without both URLs."""
    with pytest.raises(ValueError, match="MAKERSBOARD_ICAL_URL"):
        sync.run_sync(_settings(tmp_path, mb="", ade=""), now=NOW)


def test_fetch_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP errors propagate."""
    import requests

    class Resp:
        content = b""

        def raise_for_status(self) -> None:
            raise requests.HTTPError("boom")

    monkeypatch.setattr(sync.requests, "get", lambda url, timeout: Resp())
    with pytest.raises(requests.HTTPError):
        sync.fetch("http://x", 1.0)
