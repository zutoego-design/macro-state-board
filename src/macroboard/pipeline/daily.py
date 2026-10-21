"""Daily panel: every bottom-up series projected onto one business-day grid.

The observation table is period-based (a daily yield, a monthly PCE, a
quarterly GDP). That is the right way to store facts, and the wrong way to do
analysis: regressions, correlations and diffing all want one row per day with
one column per series.

This stage builds that table. Two rules make it honest:

1. **No look-ahead.** An observation is only used from the day *after* the
   period it describes has ended. A monthly print for August first appears on
   1 September, not on 1 August. This is a lower bound on the real publication
   date — the true release is usually a couple of weeks later — and stating it
   as a lower bound is the only defensible option without release calendars.

2. **Staleness is data, not noise.** Every cell carries the age of the source
   observation in days, so a reader can tell a fresh 10Y yield (0 days) from a
   carried-forward GDP print (100+ days) without guessing.

Output: `daily_wide` (one row per business day, one column per series) and
`daily_column` (the mapping from SQL-safe column name back to series_id).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .. import catalog, db

CAL = None  # lazily built US federal business-day calendar


def _calendar():
    global CAL
    if CAL is None:
        from pandas.tseries.holiday import USFederalHolidayCalendar
        CAL = USFederalHolidayCalendar()
    return CAL


def business_days(start: dt.date, end: dt.date) -> pd.DatetimeIndex:
    """Weekdays minus US federal holidays (Fed/Treasury settlement calendar)."""
    return pd.bdate_range(start=start, end=end, freq=pd.offsets.CustomBusinessDay(calendar=_calendar()))


def period_end(period: str) -> dt.date:
    """Last calendar day the observation refers to."""
    p = str(period)
    if "-Q" in p.upper():
        y, q = p.upper().split("-Q")
        y, q = int(y), int(q)
        month = q * 3
        nxt = dt.date(y + (month == 12), 1 if month == 12 else month + 1, 1)
        return nxt - dt.timedelta(days=1)
    if len(p) == 7:
        y, m = int(p[:4]), int(p[5:7])
        nxt = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        return nxt - dt.timedelta(days=1)
    return dt.date.fromisoformat(p[:10])


def known_from(period: str, frequency: str) -> dt.date:
    """First day an observation can legitimately be used.

    A daily close is usable at the end of its own day; a monthly or quarterly
    print only after the period it describes is closed, which is a lower bound
    on the real release date.
    """
    end = period_end(period)
    if (frequency or "D").upper() in ("D", "W"):
        return end
    return end + dt.timedelta(days=1)


def column_name(series_id: str) -> str:
    """us.rates.ust10y -> us_rates_ust10y (SQL-safe, stable)."""
    return series_id.replace(".", "_").replace("-", "_")


def build(conn, *, start: str | None = None, verbose: bool = True) -> dict:
    snap = db.snapshot(conn)
    if not snap:
        raise RuntimeError("no observations — run ingest first")

    cat = {r["series_id"]: r for r in db.catalog(conn)}
    series = {sid: rows for sid, rows in snap.items() if sid in cat and rows}
    if not series:
        raise RuntimeError("catalogue and observations do not overlap")

    ends = {sid: period_end(rows[-1][0]) for sid, rows in series.items()}
    first = min(period_end(rows[0][0]) for rows in series.values())
    today = dt.date.today()
    # never invent days that have not happened: a composite stamped with an
    # unfinished month has a period_end in the future, so cap at today
    grid_end = today
    grid_start = dt.date.fromisoformat(start) if start else first

    grid = pd.DataFrame({"date": business_days(grid_start, grid_end)})
    if grid.empty:
        raise RuntimeError("empty business-day grid")

    wide = pd.DataFrame({"date": grid["date"]})
    ages = pd.DataFrame({"date": grid["date"]})
    mapping = []

    for sid, rows in sorted(series.items()):
        frame = pd.DataFrame(rows, columns=["period", "value"])
        freq = cat[sid]["frequency"]
        frame["ref"] = pd.to_datetime([known_from(p, freq).isoformat() for p in frame["period"]])
        frame = (frame.drop(columns=["period"])
                      .sort_values("ref")
                      .drop_duplicates("ref", keep="last"))
        merged = pd.merge_asof(grid, frame, left_on="date", right_on="ref",
                               direction="backward", allow_exact_matches=True)
        col = column_name(sid)
        wide[col] = merged["value"].astype("float64")
        ages[col] = (grid["date"] - merged["ref"]).dt.days.astype("Int64")
        mapping.append({"col": col, "series_id": sid,
                        "unit": cat[sid]["unit"], "freq": cat[sid]["frequency"],
                        "layer": cat[sid]["layer"]})

    wide["date"] = wide["date"].dt.strftime("%Y-%m-%d")
    ages["date"] = ages["date"].dt.strftime("%Y-%m-%d")

    conn.execute("DROP TABLE IF EXISTS daily_wide")
    conn.execute("DROP TABLE IF EXISTS daily_age")
    conn.commit()
    wide.to_sql("daily_wide", conn, if_exists="replace", index=False)
    ages.to_sql("daily_age", conn, if_exists="replace", index=False)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_daily_wide_date ON daily_wide(date)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_daily_age_date ON daily_age(date)")
    conn.execute("DROP TABLE IF EXISTS daily_column")
    conn.execute(
        "CREATE TABLE daily_column (col TEXT PRIMARY KEY, series_id TEXT NOT NULL, "
        "unit TEXT, freq TEXT, layer TEXT)"
    )
    conn.executemany(
        "INSERT INTO daily_column (col, series_id, unit, freq, layer) VALUES (?,?,?,?,?)",
        [(m["col"], m["series_id"], m["unit"], m["freq"], m["layer"]) for m in mapping],
    )
    conn.commit()

    n_days = len(wide)
    n_series = len(mapping)
    if verbose:
        filled = wide.drop(columns=["date"]).notna().sum().sum()
        print(f"  daily panel: {n_days:,} business days x {n_series} series "
              f"({grid_start} .. {grid_end}), {filled:,} non-null cells")
    return {"rows": n_days, "cols": n_series, "start": str(grid_start), "end": str(grid_end),
            "filled": int(wide.drop(columns=['date']).notna().sum().sum())}


def run(conn=None, *, start: str | None = None, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    db.init(conn)
    db.upsert_series(conn, catalog.RAW + catalog.DERIVED + catalog.BREADTH + catalog.COMPOSITES)
    run_id = db.start_run(conn, "daily")
    res = build(conn, start=start, verbose=verbose)
    db.finish_run(conn, run_id, status="ok", n_series=res["cols"], n_rows=res["rows"],
                  detail=f"{res['start']}..{res['end']}")
    return res
