"""L1: single-series transforms, computed from the vintage being written."""

from __future__ import annotations

from .. import catalog, db
from . import (annualise, diff_bp, diff_level, drawdown, level_change,
               monthly_mean, pct_change, rolling_z)

VINTAGE_NOTE = "L1 derived from this vintage's raw observations"


def compute(store: dict[str, list[tuple[str, float]]]) -> dict[str, list[tuple[str, float]]]:
    """Pure function: raw series in, derived series out."""
    g = store.get
    out: dict[str, list[tuple[str, float]]] = {}

    def need(*ids) -> bool:
        return all(g(i) for i in ids)

    if need("us.rates.ust10y", "us.rates.ust2y"):
        out["us.curve.10y2y"] = diff_bp(g("us.rates.ust10y"), g("us.rates.ust2y"))
    if need("us.rates.ust10y", "us.rates.ust3m"):
        out["us.curve.10y3m"] = diff_bp(g("us.rates.ust10y"), g("us.rates.ust3m"))
    if need("us.rates.ust5y", "us.rates.ust2y"):
        out["us.curve.5y2y"] = diff_bp(g("us.rates.ust5y"), g("us.rates.ust2y"))
    if need("us.rates.ust10y", "us.rates.effr"):
        out["us.rates.term_premium"] = diff_bp(g("us.rates.ust10y"), g("us.rates.effr"))

    if need("us.prices.pce_core"):
        core = g("us.prices.pce_core")
        out["us.infl.pce_core_yoy"] = pct_change(core, 12)
        out["us.infl.pce_core_3m"] = annualise(core, 3)
    if need("us.prices.pce"):
        out["us.infl.pce_yoy"] = pct_change(g("us.prices.pce"), 12)

    if need("us.growth.gdp_level"):
        out["us.growth.gdp_yoy"] = pct_change(g("us.growth.gdp_level"), 4)
    if need("us.growth.ip"):
        out["us.growth.ip_yoy"] = pct_change(g("us.growth.ip"), 12)
    if need("us.growth.cli"):
        out["us.growth.cli_6m"] = level_change(g("us.growth.cli"), 6)

    if need("us.labor.unrate"):
        out["us.labor.unrate_chg12"] = level_change(g("us.labor.unrate"), 12)

    if need("us.rates.effr") and out.get("us.infl.pce_core_yoy"):
        out["us.rates.real_policy"] = diff_level(
            monthly_mean(g("us.rates.effr")), out["us.infl.pce_core_yoy"]
        )

    if need("us.market.spx"):
        out["us.market.spx_dd"] = drawdown(g("us.market.spx"), 252)
    if need("us.market.vix"):
        out["us.market.vix_z"] = rolling_z(g("us.market.vix"), 252)

    return out


def run(conn=None, *, vintage: int | None = None, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    db.init(conn)
    db.upsert_series(conn, catalog.RAW + catalog.DERIVED + catalog.BREADTH + catalog.COMPOSITES)
    vintage = vintage or db.latest_vintage(conn)
    if not vintage:
        raise RuntimeError("no snapshot vintage — run ingest first")

    store = db.snapshot(conn, vintage)
    computed = compute(store)

    run_id = db.start_run(conn, "derive")
    total = 0
    for spec in catalog.DERIVED:
        obs = computed.get(spec["series_id"])
        if not obs:
            if verbose:
                print(f"  skip {spec['series_id']:<26} inputs unavailable")
            continue
        total += db.write_observations(conn, spec["series_id"], obs, vintage)
        if verbose:
            print(f"  ok   {spec['series_id']:<26} {len(obs):>6} obs  {obs[0][0]} .. {obs[-1][0]}")
    db.bump_vintage_count(conn, vintage)
    db.finish_run(conn, run_id, status="ok", vintage_id=vintage,
                  n_series=len(computed), n_rows=total, detail=VINTAGE_NOTE)
    if verbose:
        print(f"\nL1: {len(computed)}/{len(catalog.DERIVED)} series, {total:,} rows")
    return {"vintage": vintage, "series": len(computed), "rows": total}
