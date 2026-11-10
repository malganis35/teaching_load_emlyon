"""Teaching-load metrics: realised / planned / projected hours against the yearly target."""

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd


@dataclass(frozen=True)
class WorkloadSummary:
    """Headline numbers of the dashboard (all hours are presence hours)."""

    target: float
    realised: float
    planned_remaining: float
    projected: float
    gap: float  # target - projected; > 0 means hours are still missing
    weeks_left: float
    missing_per_week: float
    realised_pct: float
    projected_pct: float


def summarize(sessions: pd.DataFrame, target: float, year_end: date, now: datetime) -> WorkloadSummary:
    """Compute headline metrics from sessions already filtered to the courses to count."""
    done = sessions["end_ts"] <= now
    realised = float(sessions.loc[done, "duration_h"].sum())
    planned = float(sessions.loc[~done, "duration_h"].sum())
    projected = realised + planned
    gap = target - projected
    weeks_left = max((datetime.combine(year_end, datetime.min.time()) - now).days / 7, 0.0)
    missing_per_week = max(gap, 0.0) / weeks_left if weeks_left > 0 else 0.0

    def pct(v: float) -> float:
        return 100 * v / target if target else 0.0

    return WorkloadSummary(
        target, realised, planned, projected, gap, weeks_left, missing_per_week, pct(realised), pct(projected)
    )


def cumulative_curve(
    sessions: pd.DataFrame, year_start: date, year_end: date, target: float, now: datetime
) -> pd.DataFrame:
    """Daily cumulative hours: projected (all sessions), realised (until now) and a linear path to the target."""
    days = pd.date_range(year_start, year_end, freq="D")
    daily = sessions.assign(day=sessions["start_ts"].dt.normalize()).groupby("day")["duration_h"].sum()
    projected = daily.reindex(days, fill_value=0.0).cumsum()
    realised = projected.where(days <= pd.Timestamp(now.date()))
    linear = pd.Series(
        [target * i / max(len(days) - 1, 1) for i in range(len(days))],
        index=days,
    )
    return pd.DataFrame(
        {"date": days, "projected": projected.values, "realised": realised.values, "linear": linear.values}
    )


def hours_by(sessions: pd.DataFrame, column: str, now: datetime) -> pd.DataFrame:
    """Realised vs planned hours grouped by ``column`` (course_name, programme, ...)."""
    status = sessions["end_ts"].le(now).map({True: "realised", False: "planned"})
    table = sessions.assign(status=status).pivot_table(
        index=column, columns="status", values="duration_h", aggfunc="sum", fill_value=0.0
    )
    for col in ("realised", "planned"):
        if col not in table:
            table[col] = 0.0
    table["total"] = table["realised"] + table["planned"]
    return table[["realised", "planned", "total"]].sort_values("total", ascending=False).reset_index()


def hours_by_month(sessions: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Realised vs planned hours per calendar month."""
    month = sessions["start_ts"].dt.to_period("M").astype(str)
    return hours_by(sessions.assign(month=month), "month", now).sort_values("month").reset_index(drop=True)
