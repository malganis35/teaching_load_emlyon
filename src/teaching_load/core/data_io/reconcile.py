"""Merge Makersboard (names) and ADE (codes, programmes) sessions into one table."""

from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

from teaching_load.core.data_io.models import RawSession

Slot = tuple[datetime, datetime]
Pair = tuple[RawSession | None, RawSession | None]

PROGRAMMES = {"FI_MS/MSC-IN": "MSc in", "FI_PGE": "PGE", "FI_BACHELORS": "Bachelors"}

COLUMNS = [
    "session_id",
    "makersboard_uid",
    "ade_uid",
    "start_ts",
    "end_ts",
    "duration_h",
    "course_code",
    "course_name",
    "programme",
    "location",
    "groups",
    "filiere",
    "formation_type",
    "responsable",
    "source",
]


def programme_of(filiere: str, formation_type: str) -> str:
    """Derive a readable programme label from ADE labels."""
    if filiere in PROGRAMMES:
        return PROGRAMMES[filiere]
    if formation_type == "FORMATION_CONTINUE":
        return "Formation continue"
    return filiere or "Inconnu"


def _learn_code_names(mb: list[RawSession], ade: list[RawSession]) -> dict[str, str]:
    """Learn ADE code -> Makersboard name from slots holding exactly one session on each side."""
    mb_slots: dict[Slot, list[RawSession]] = defaultdict(list)
    ade_slots: dict[Slot, list[RawSession]] = defaultdict(list)
    for s in mb:
        mb_slots[s.slot].append(s)
    for s in ade:
        ade_slots[s.slot].append(s)
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for slot, mbs in mb_slots.items():
        ades = ade_slots.get(slot, [])
        if len(mbs) == 1 and len(ades) == 1:
            votes[ades[0].code][mbs[0].title] += 1
    return {code: counter.most_common(1)[0][0] for code, counter in votes.items()}


def _pair_slots(mb: list[RawSession], ade: list[RawSession], code_names: dict[str, str]) -> list[Pair]:
    """Return (mb_session | None, ade_session | None) pairs."""
    mb_slots: dict[Slot, list[RawSession]] = defaultdict(list)
    ade_slots: dict[Slot, list[RawSession]] = defaultdict(list)
    for s in mb:
        mb_slots[s.slot].append(s)
    for s in ade:
        ade_slots[s.slot].append(s)

    pairs: list[Pair] = []
    for slot in sorted(set(mb_slots) | set(ade_slots)):
        mbs = list(mb_slots.get(slot, []))
        ades = list(ade_slots.get(slot, []))
        for m in list(mbs):
            match = next((a for a in ades if code_names.get(a.code) == m.title), None)
            if match is None and len(mbs) == 1 and len(ades) == 1:
                match = ades[0]
            if match is not None:
                pairs.append((m, match))
                mbs.remove(m)
                ades.remove(match)
        pairs.extend((m, None) for m in mbs)
        pairs.extend((None, a) for a in ades)
    return pairs


def reconcile(mb: list[RawSession], ade: list[RawSession]) -> pd.DataFrame:
    """Build the consolidated sessions table with a ``source`` of both / makersboard_only / ade_only."""
    code_names = _learn_code_names(mb, ade)
    name_codes: dict[str, set[str]] = defaultdict(set)
    for code, name in code_names.items():
        name_codes[name].add(code)

    rows: list[dict[str, object]] = []
    for m, a in _pair_slots(mb, ade, code_names):
        ref = a or m
        assert ref is not None  # noqa: S101 - pairs always hold at least one side
        if a is not None:
            code = a.code
            name = m.title if m else code_names.get(a.code, a.code)
            source = "both" if m else "ade_only"
        else:
            assert m is not None  # noqa: S101
            codes = name_codes.get(m.title, set())
            code = next(iter(codes)) if len(codes) == 1 else f"MB:{m.title}"
            name = m.title
            source = "makersboard_only"
        rows.append(
            {
                "session_id": ref.uid,
                "makersboard_uid": m.uid if m else None,
                "ade_uid": a.uid if a else None,
                "start_ts": ref.start.replace(tzinfo=None),
                "end_ts": ref.end.replace(tzinfo=None),
                "duration_h": ref.hours,
                "course_code": code,
                "course_name": name,
                "programme": programme_of(a.filiere, a.formation_type) if a else "Inconnu",
                "location": ref.location,
                "groups": " | ".join(a.groups) if a else "",
                "filiere": a.filiere if a else "",
                "formation_type": a.formation_type if a else "",
                "responsable": a.responsable if a else "",
                "source": source,
            }
        )
    df = pd.DataFrame(rows, columns=COLUMNS)
    return _fill_unknown_metadata(df)


def _fill_unknown_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Give Makersboard-only sessions the programme/filiere of their course seen in ADE."""
    known = df[df["programme"] != "Inconnu"]
    for col in ["programme", "filiere", "formation_type", "responsable"]:
        by_course = known.groupby("course_code")[col].agg(lambda x: x.mode().iat[0] if len(x.mode()) else "")
        missing = (df[col] == "") | (df[col] == "Inconnu")
        df.loc[missing, col] = df.loc[missing, "course_code"].map(by_course).fillna(df.loc[missing, col])
    return df
