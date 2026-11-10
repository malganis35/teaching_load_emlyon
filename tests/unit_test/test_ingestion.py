"""Tests for feed parsing and reconciliation."""

from teaching_load.core.data_io.ade import parse_ade, split_description
from teaching_load.core.data_io.makersboard import parse_makersboard
from teaching_load.core.data_io.models import to_paris
from teaching_load.core.data_io.reconcile import programme_of, reconcile


def test_parse_makersboard(mb_ics: str) -> None:
    """Floating times are interpreted as Paris local time."""
    sessions = parse_makersboard(mb_ics)
    assert len(sessions) == 3
    assert sessions[0].title == "Data visualization"
    assert sessions[0].start.hour == 8 and sessions[0].start.utcoffset().total_seconds() == 7200
    assert sessions[0].hours == 1.5


def test_parse_ade_extracts_metadata(ade_ics: str) -> None:
    """Code, groups, filiere and responsable are read from the description."""
    first = parse_ade(ade_ics)[0]
    assert first.code == "VIS_01"
    assert first.groups == ("MSc in_MNGT",)
    assert first.filiere == "FI_MS/MSC-IN"
    assert first.formation_type == "FORMATION_INITIALE"
    assert first.responsable == "DOE John"
    assert first.start.hour == 8  # 06:00Z -> 08:00 Paris (summer time)


def test_split_description_keeps_group_when_rp_is_last() -> None:
    """If the last line is an RP line, no teacher line is dropped."""
    groups, _, _, rp = split_description("\n1\nGRP\nCODE\nRP. A B\n", "CODE")
    assert groups == ("GRP",) and rp == "A B"


def test_programme_of() -> None:
    """Programme labels fall back on formation type, then filiere."""
    assert programme_of("FI_PGE", "") == "PGE"
    assert programme_of("", "FORMATION_CONTINUE") == "Formation continue"
    assert programme_of("", "") == "Inconnu"


def test_to_paris_handles_aware_datetimes(ade_ics: str) -> None:
    """Aware datetimes are converted, not relabelled."""
    s = parse_ade(ade_ics)[0]
    assert to_paris(s.start) == s.start


def test_reconcile_matches_and_flags_sources(mb_ics: str, ade_ics: str) -> None:
    """Matched slots get ADE codes + Makersboard names; leftovers are flagged by source."""
    df = reconcile(parse_makersboard(mb_ics), parse_ade(ade_ics))
    by_source = df["source"].value_counts().to_dict()
    assert by_source == {"both": 2, "makersboard_only": 1, "ade_only": 1}
    matched = df[df["source"] == "both"]
    assert set(matched["course_code"]) == {"VIS_01"}
    assert set(matched["course_name"]) == {"Data visualization"}
    assert set(matched["programme"]) == {"MSc in"}
    ade_only = df[df["source"] == "ade_only"].iloc[0]
    assert ade_only["course_name"] == "ADEONLY_01" and ade_only["programme"] == "Formation continue"
    mb_only = df[df["source"] == "makersboard_only"].iloc[0]
    assert mb_only["course_code"] == "MB:Python programming"


def test_reconcile_fills_programme_for_makersboard_only(mb_ics: str, ade_ics: str) -> None:
    """A Makersboard-only session of a known course inherits the course programme."""
    extra = mb_ics.replace("END:VCALENDAR", "").rstrip() + (
        "\nBEGIN:VEVENT\nUID:mb-9\nDTSTART:20261110T080000\nDTEND:20261110T093000\n"
        "SUMMARY:Data visualization\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    df = reconcile(parse_makersboard(extra), parse_ade(ade_ics))
    row = df[df["makersboard_uid"] == "mb-9"].iloc[0]
    assert row["course_code"] == "VIS_01" and row["programme"] == "MSc in"
