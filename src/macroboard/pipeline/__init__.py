"""Pipeline stages. Each stage reads the current vintage and writes into it."""

from __future__ import annotations

import statistics
from typing import Callable, Iterable

Pair = tuple[str, float]
Series = list[Pair]


# ---------------------------------------------------------------------------
# numeric helpers shared by the stages
# ---------------------------------------------------------------------------

def as_dict(pairs: Iterable[Pair]) -> dict[str, float]:
    return {p: v for p, v in pairs if v is not None}


def log_change(a: float, b: float) -> float | None:
    if not a or not b or a <= 0 or b <= 0:
        return None
    import math
    return 100.0 * math.log(a / b)


def pct_change(pairs: Series, steps: int = 12) -> Series:
    out = []
    for i in range(steps, len(pairs)):
        v = log_change(pairs[i][1], pairs[i - steps][1])
        if v is not None:
            out.append((pairs[i][0], v))
    return out


def annualise(pairs: Series, months: int, per_year: int = 12) -> Series:
    scale = per_year / months
    out = []
    for i in range(months, len(pairs)):
        v = log_change(pairs[i][1], pairs[i - months][1])
        if v is not None:
            out.append((pairs[i][0], v * scale))
    return out


def level_change(pairs: Series, steps: int = 6, scale: float = 1.0) -> Series:
    out = []
    for i in range(steps, len(pairs)):
        out.append((pairs[i][0], (pairs[i][1] - pairs[i - steps][1]) * scale))
    return out


def diff_bp(a: Series, b: Series) -> Series:
    other = as_dict(b)
    return [(p, 100.0 * (v - other[p])) for p, v in a if p in other]


def diff_level(a: Series, b: Series) -> Series:
    other = as_dict(b)
    return [(p, v - other[p]) for p, v in a if p in other]


def monthly_mean(daily: Series) -> Series:
    acc: dict[str, list[float]] = {}
    for p, v in daily:
        acc.setdefault(p[:7], []).append(v)
    return sorted((m, statistics.fmean(vs)) for m, vs in acc.items())


def drawdown(pairs: Series, window: int = 252) -> Series:
    vals = [v for _, v in pairs]
    out = []
    for i, (p, v) in enumerate(pairs):
        peak = max(vals[max(0, i - window + 1):i + 1])
        if peak > 0:
            out.append((p, 100.0 * (v / peak - 1.0)))
    return out


def rolling_z(pairs: Series, window: int = 252, min_obs: int | None = None) -> Series:
    vals = [v for _, v in pairs]
    need = min_obs or max(8, window // 6)
    out = []
    for i, (p, v) in enumerate(pairs):
        win = vals[max(0, i - window + 1):i + 1]
        if len(win) < need:
            continue
        mu = statistics.fmean(win)
        sd = statistics.pstdev(win)
        if sd > 1e-12:
            out.append((p, (v - mu) / sd))
    return out


# ---------------------------------------------------------------------------
# monthly alignment — the grid every composite lives on
# ---------------------------------------------------------------------------

def to_monthly(pairs: Series, frequency: str) -> Series:
    """Collapse any frequency onto a month label.

    Daily/weekly -> monthly mean (less noisy than a single print).
    Quarterly    -> repeated on each month of the quarter (forward fill).
    """
    f = frequency.upper()
    if f in ("D", "W"):
        return monthly_mean(pairs)
    if f == "M":
        return list(pairs)
    if f == "Q":
        out = []
        for p, v in pairs:
            try:
                y, q = p.split("-Q")
                m0 = (int(q) - 1) * 3 + 1
            except ValueError:
                continue
            for m in range(3):
                out.append((f"{y}-{m0 + m:02d}", v))
        return out
    return list(pairs)


def align_monthly(series_by_id: dict[str, tuple[Series, str]], *, max_fill: int = 3) -> dict[str, dict[str, float]]:
    """Put every input on one monthly axis, forward-filling gaps up to `max_fill`."""
    monthly = {sid: dict(to_monthly(rows, freq)) for sid, (rows, freq) in series_by_id.items()}
    months = sorted({m for mm in monthly.values() for m in mm})
    aligned: dict[str, dict[str, float]] = {}
    for sid, mm in monthly.items():
        out, last, gap = {}, None, 0
        for m in months:
            if m in mm:
                last, gap = mm[m], 0
            else:
                gap += 1
                if last is None or gap > max_fill:
                    continue
            out[m] = last
        aligned[sid] = out
    return aligned


# ---------------------------------------------------------------------------
# z-scoring on a trailing window
# ---------------------------------------------------------------------------

def zscore_map(monthly: dict[str, float], window: int = 120, min_obs: int = 36) -> dict[str, float]:
    months = sorted(monthly)
    vals = [monthly[m] for m in months]
    out: dict[str, float] = {}
    for i, m in enumerate(months):
        win = vals[max(0, i - window + 1):i + 1]
        if len(win) < min_obs:
            continue
        mu = statistics.fmean(win)
        sd = statistics.pstdev(win)
        if sd > 1e-12:
            out[m] = (vals[i] - mu) / sd
    return out


def percentile_map(monthly: dict[str, float], window: int = 120, min_obs: int = 36) -> dict[str, float]:
    months = sorted(monthly)
    vals = [monthly[m] for m in months]
    out: dict[str, float] = {}
    for i, m in enumerate(months):
        win = vals[max(0, i - window + 1):i + 1]
        if len(win) < min_obs:
            continue
        below = sum(1 for x in win if x <= vals[i])
        out[m] = 100.0 * below / len(win)
    return out
