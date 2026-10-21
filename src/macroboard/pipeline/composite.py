"""L2: composites.

A composite is a weighted mean of standardised inputs, computed on a monthly
grid. The definition lives in `composite_input`, so every aggregate can be
decomposed on the dashboard and re-derived by hand.

Two things are deliberate:

* inputs keep their own sign convention, and `sign` flips the ones where a
  rise is bad news (unemployment, drawdown);
* the risk composite is a percentile, not a z-score, because "0-100 how close
  is the cycle to breaking" is easier to argue about than "-1.4 sigma".
"""

from __future__ import annotations

from .. import catalog, db
from . import align_monthly, percentile_map, zscore_map

def _month_key(period: str) -> str | None:
    """Any period label -> YYYY-MM, a quarter mapped to its last month."""
    p = str(period)
    if "-Q" in p.upper():
        y, q = p.upper().split("-Q")
        try:
            return f"{int(y)}-{int(q) * 3:02d}"
        except ValueError:
            return None
    return p[:7] if len(p) >= 7 else None


Z_WINDOW = 120       # trailing months used to standardise an input
MIN_OBS = 36


def _order(composites: list[dict]) -> list[dict]:
    """Dependency order: a composite that feeds another is computed first."""
    ids = {c["series_id"] for c in composites}
    done: set[str] = set()
    order: list[dict] = []
    pending = list(composites)
    guard = 0
    while pending and guard < 50:
        guard += 1
        for spec in list(pending):
            deps = {i["input_id"] for i in spec.get("inputs", [])} & ids
            if deps <= done:
                order.append(spec)
                done.add(spec["series_id"])
                pending.remove(spec)
        if len(order) < len(composites) and guard > len(composites) + 2:
            break
    return order + pending


def build(store: dict[str, list[tuple[str, float]]],
          catalog_rows: list[dict],
          *, verbose: bool = True) -> dict[str, list[tuple[str, float]]]:
    freq = {}
    for spec in catalog.RAW + catalog.DERIVED + catalog.BREADTH + catalog.COMPOSITES:
        freq[spec["series_id"]] = spec["frequency"]

    produced: dict[str, list[tuple[str, float]]] = {}
    meta_by_id: dict[str, list[dict]] = {}
    available = dict(store)

    for spec in _order(catalog.COMPOSITES):
        cid = spec["series_id"]
        inputs = spec.get("inputs", [])
        ready = []
        for inp in inputs:
            rows = available.get(inp["input_id"])
            if rows:
                ready.append((inp, rows))
        if not ready:
            if verbose:
                print(f"  skip {cid:<26} no inputs available")
            continue

        # 6 months of forward-fill, not 3: a quarterly input is legitimately
        # four months old by the time the next quarter prints, and dropping it
        # would silently change the composite's composition month to month.
        aligned = align_monthly(
            {inp["input_id"]: (rows, freq.get(inp["input_id"], "M")) for inp, rows in ready},
            max_fill=6,
        )
        zs = {sid: zscore_map(monthly, Z_WINDOW, MIN_OBS) for sid, monthly in aligned.items()}

        weight_of = {inp["input_id"]: (inp.get("weight", 1.0), inp.get("sign", 1.0))
                     for inp, _ in ready}

        months = sorted(set().union(*[set(z) for z in zs.values()]))
        total_w = sum(max(inp.get("weight", 1.0), 1e-9) for inp in inputs)
        raw: list[tuple[str, float]] = []
        meta: list[dict] = []
        last_seen: dict[str, str] = {}
        for m in months:
            # remember the newest period each input has reached by this month.
            # Quarters must be converted to a month key first: comparing the
            # string "2026-Q2" with "2026-10" lexicographically is nonsense.
            for inp, rows_in in ready:
                for p, _ in rows_in:
                    key = _month_key(p)
                    if key and key <= m:
                        last_seen[inp["input_id"]] = key
            num = den = 0.0
            used = []
            for sid, zmap in zs.items():
                if m not in zmap:
                    continue
                w, s = weight_of[sid]
                num += w * s * zmap[m]
                den += w
                used.append(sid)
            # a composite needs most of its inputs, not just one: otherwise
            # the early history is a single series wearing a composite's name
            if den > 0 and den / total_w >= 0.6:
                raw.append((m, num / den))
                stamps = sorted(last_seen[s] for s in used if s in last_seen)
                meta.append({
                    "composite_id": cid, "period": m,
                    "n_inputs": len(used), "weight_covered": den / total_w,
                    "oldest_input": stamps[0] if stamps else None,
                    "newest_input": stamps[-1] if stamps else None,
                })

        if not raw:
            continue

        if spec.get("unit") == "score":
            monthly = dict(raw)
            pct = percentile_map(monthly, Z_WINDOW, MIN_OBS)
            series = [(m, round(pct[m], 1)) for m in sorted(pct)]
        else:
            series = raw

        produced[cid] = series
        meta_by_id[cid] = meta
        available[cid] = series
        if verbose and series:
            latest = meta[-1] if meta else {}
            print(f"  ok   {cid:<26} {len(series):>6} obs  {series[0][0]} .. {series[-1][0]}  "
                  f"last={series[-1][1]:+.2f}  inputs {latest.get('oldest_input')}"
                  f"→{latest.get('newest_input')}")
    return produced, meta_by_id


def run(conn=None, *, vintage: int | None = None, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    vintage = vintage or db.latest_vintage(conn)
    if not vintage:
        raise RuntimeError("no snapshot vintage")

    db.upsert_series(conn, catalog.COMPOSITES)
    rows = []
    for spec in catalog.COMPOSITES:
        for inp in spec.get("inputs", []):
            rows.append({**inp, "composite_id": spec["series_id"]})
    db.upsert_composite_inputs(conn, rows)

    store = db.snapshot(conn, vintage)
    run_id = db.start_run(conn, "composite")
    produced, meta = build(store, catalog.COMPOSITES, verbose=verbose)

    total = 0
    for spec in catalog.COMPOSITES:
        obs = produced.get(spec["series_id"])
        if obs:
            total += db.write_observations(conn, spec["series_id"], obs, vintage)["written"]
    for cid, rows_meta in meta.items():
        db.write_composite_meta(conn, rows_meta)
    db.bump_vintage_count(conn, vintage)
    db.finish_run(conn, run_id, status="ok", vintage_id=vintage,
                  n_series=len(produced), n_rows=total,
                  detail="weighted z-composites on a monthly grid")
    if verbose:
        print(f"\nL2: {len(produced)}/{len(catalog.COMPOSITES)} composites, {total:,} rows")
    return {"vintage": vintage, "series": len(produced), "rows": total}
