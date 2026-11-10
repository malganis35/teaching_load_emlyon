"""Shared data structures for calendar sessions."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def to_paris(value: datetime) -> datetime:
    """Return a timezone-aware datetime in Europe/Paris (naive values are assumed Paris local time)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=PARIS)
    return value.astimezone(PARIS)


@dataclass(frozen=True)
class RawSession:
    """One calendar event as read from a feed, before reconciliation."""

    source: str
    uid: str
    start: datetime
    end: datetime
    title: str
    location: str = ""
    code: str = ""
    groups: tuple[str, ...] = ()
    filiere: str = ""
    formation_type: str = ""
    responsable: str = ""

    @property
    def slot(self) -> tuple[datetime, datetime]:
        """Timezone-normalised (start, end) used to match sessions across sources."""
        return (self.start, self.end)

    @property
    def hours(self) -> float:
        """Duration in hours."""
        return (self.end - self.start).total_seconds() / 3600
