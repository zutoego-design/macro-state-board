"""Tracker.

Most providers hand out history. A few only ever publish "today's number",
and a third group quietly revises what they published last week. Both cases
have the same answer: look every day and write down what you saw.

Each run appends, for every catalogued series, the latest print and the period
it refers to. Run it from Task Scheduler / cron and you get:

  * a first-print log — what the number was before it was revised;
  * a revision detector — `changed` counts how many series moved since the
    previous run, which is how you notice a print you would otherwise miss;
  * a history for anything that only exposes a current value.

Nothing is overwritten: `tracker` is keyed on (series_id, observed_at).
"""

from __future__ import annotations

import datetime as dt

from .. import catalog, db


def _series_to_track() -> list[str]:
    ids = [s["series_id"] for s in catalog.RAW + catalog.DERIVED + catalog.BREADTH
           + catalog.COMPOSITES]
    ids += [s["series_id"] for s in catalog.TRACKED]
    return list(dict.fromkeys(ids))


def run(conn=None, *, today: str | None = None, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    db.init(conn)
    today = today or dt.date.today().isoformat()

    if catalog.TRACKED:
        db.upsert_series(conn, catalog.TRACKED)

    snap = db.snapshot(conn)
    run_id = db.start_run(conn, "track")

    recorded, changed, failed = 0, 0, []
    movers: list[tuple[str, float | None, float | None]] = []

    for sid in _series_to_track():
        rows = snap.get(sid)
        if not rows:
            failed.append((sid, "no data"))
            continue
        period, value = rows[-1]
        prev = conn.execute(
            "SELECT value FROM tracker WHERE series_id=? AND observed_at<? "
            "ORDER BY observed_at DESC LIMIT 1",
            (sid, today),
        ).fetchone()
        prev_value = prev["value"] if prev else None
        try:
            db.tracker_append(conn, sid, today, value,
                              as_of_label=period,
                              payload={"period": period, "n_obs": len(rows)})
            recorded += 1
            if prev_value is not None and abs(value - prev_value) > 1e-12:
                changed += 1
                movers.append((sid, prev_value, value))
        except Exception as exc:  # noqa: BLE001
            db.tracker_error(conn, sid, repr(exc))
            failed.append((sid, repr(exc)[:120]))

    db.finish_run(conn, run_id, status="ok" if not failed else "partial",
                  n_series=recorded, n_rows=recorded,
                  detail=f"{changed} changed" + ("; " + str(failed[:3]) if failed else ""))

    if verbose:
        print(f"tracker {today}: {recorded} series recorded, {changed} changed since last run")
        for sid, before, after in movers[:8]:
            print(f"  ~ {sid:<28} {before:>12.4f} -> {after:>12.4f}")
        if failed:
            print(f"  {len(failed)} skipped")
    return {"date": today, "recorded": recorded, "changed": changed, "failed": failed}
