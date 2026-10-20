"""L0: pull the catalogue into a new vintage."""

from __future__ import annotations

import time

from .. import catalog, db
from ..providers import fetch


def run(conn=None, *, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    db.init(conn)
    declared = db.upsert_series(conn, catalog.RAW + catalog.DERIVED + catalog.BREADTH
                                + catalog.COMPOSITES + catalog.TRACKED)
    run_id = db.start_run(conn, "ingest")
    vintage = db.open_vintage(conn, kind="snapshot", source="ingest",
                              note=f"ingest run {run_id}")

    ok, failed, rows_total = 0, [], 0
    started = time.time()
    for spec in catalog.RAW:
        sid = spec["series_id"]
        t0 = time.time()
        try:
            obs = fetch(spec)
            if not obs:
                raise RuntimeError("provider returned no observations")
            clean = [(db.normalize_period(p, spec["frequency"]), v) for p, v in obs]
            clean = [(p, v) for p, v in clean if v is not None]
            n = db.write_observations(conn, sid, clean, vintage)
            rows_total += n
            ok += 1
            if verbose:
                print(f"  ok   {sid:<26} {n:>6} obs  {clean[0][0]} .. {clean[-1][0]}  "
                      f"{time.time() - t0:5.1f}s")
        except Exception as exc:  # one dead provider must not kill the run
            failed.append((sid, repr(exc)[:160]))
            if verbose:
                print(f"  FAIL {sid:<26} {exc!r}"[:170])

    db.bump_vintage_count(conn, vintage)
    status = "ok" if not failed else ("partial" if ok else "failed")
    db.finish_run(conn, run_id, status=status, vintage_id=vintage, n_series=ok,
                  n_rows=rows_total,
                  detail="; ".join(f"{s}: {e}" for s, e in failed)[:2000] or None)
    if verbose:
        print(f"\n{ok}/{len(catalog.RAW)} series, {rows_total:,} rows, "
              f"{time.time() - started:.1f}s, vintage {vintage}")
    return {"vintage": vintage, "ok": ok, "failed": failed, "rows": rows_total,
            "declared": declared}
