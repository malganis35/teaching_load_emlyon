"""Parser for the Makersboard iCal feed (readable course names, local Paris times)."""

from datetime import datetime

from icalendar import Calendar

from teaching_load.core.data_io.models import RawSession, to_paris


def parse_makersboard(content: str | bytes) -> list[RawSession]:
    """Parse a Makersboard .ics payload into sessions (all-day events are ignored)."""
    calendar = Calendar.from_ical(content)
    sessions: list[RawSession] = []
    for event in calendar.walk("VEVENT"):
        start = event.decoded("DTSTART")
        end = event.decoded("DTEND")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        sessions.append(
            RawSession(
                source="makersboard",
                uid=str(event.get("UID", "")),
                start=to_paris(start),
                end=to_paris(end),
                title=str(event.get("SUMMARY", "")).strip(),
                location=str(event.get("LOCATION", "")).strip(),
            )
        )
    return sessions
