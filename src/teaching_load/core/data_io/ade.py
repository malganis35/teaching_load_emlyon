"""Parser for the ADE Campus iCal feed (course codes, groups, programme metadata)."""

from datetime import datetime

from icalendar import Calendar

from teaching_load.core.data_io.models import RawSession, to_paris

FORMATION_TYPES = {"FORMATION_INITIALE", "FORMATION_CONTINUE"}
NOISE_LINES = {"Cours de management"}


def split_description(description: str, code: str) -> tuple[tuple[str, ...], str, str, str]:
    """Extract (groups, filiere, formation_type, responsable) from an ADE DESCRIPTION block.

    The block is a list of lines: internal id, groups, course code, labels, 'RP. <name>',
    the exporting teacher, then an '(Exported ...)' footer.
    """
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("(Exported")]
    if lines and lines[0].isdigit():
        lines = lines[1:]
    if lines and not lines[-1].startswith("RP."):
        lines = lines[:-1]  # last line is the teacher resource this feed belongs to

    groups: list[str] = []
    filiere = formation_type = responsable = ""
    for line in lines:
        if line.startswith("RP."):
            responsable = line.removeprefix("RP.").strip()
        elif line in FORMATION_TYPES:
            formation_type = line
        elif line.startswith("FI_"):
            filiere = line
        elif line != code and line not in NOISE_LINES:
            groups.append(line)
    return tuple(groups), filiere, formation_type, responsable


def parse_ade(content: str | bytes) -> list[RawSession]:
    """Parse an ADE .ics payload into sessions (timestamps are UTC in the feed)."""
    calendar = Calendar.from_ical(content)
    sessions: list[RawSession] = []
    for event in calendar.walk("VEVENT"):
        start = event.decoded("DTSTART")
        end = event.decoded("DTEND")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        title = str(event.get("SUMMARY", "")).strip()
        code = title.split(" (")[0].strip()
        groups, filiere, formation_type, responsable = split_description(str(event.get("DESCRIPTION", "")), code)
        sessions.append(
            RawSession(
                source="ade",
                uid=str(event.get("UID", "")),
                start=to_paris(start),
                end=to_paris(end),
                title=title,
                location=str(event.get("LOCATION", "")).strip(),
                code=code,
                groups=groups,
                filiere=filiere,
                formation_type=formation_type,
                responsable=responsable,
            )
        )
    return sessions
