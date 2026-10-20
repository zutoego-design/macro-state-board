"""L1b: panel aggregates.

Two numbers that no single provider publishes for us: a trimmed-mean PCE
inflation rate and a diffusion measure of how broad the price pressure is.
Both are computed from the 31-line BEA PCE price table in one request, and
both are the honest answer to "how is inflation really doing" — which is why
they are inputs to the inflation composite instead of yet another row of
index levels.
"""

from __future__ import annotations

import math
import statistics

from .. import catalog, db
from ..providers import dbnomics_panel

# Detail lines of BEA table 2.8.4. Aggregates (total PCE, goods, services,
# core, market-based) are deliberately excluded so components are not
# double-counted.
COMPONENTS = [
    "DCLORG-M",   # clothing and footwear
    "DFDHRG-M",   # furnishings and durable household equipment
    "DFSARG-M",   # food services and accommodations
    "DFXARG-M",   # food and beverages off-premises
    "DGOERG-M",   # gasoline and other energy goods
    "DHCERG-M",   # health care
    "DHLCRG-M",   # housing
    "DHUTRG-M",   # housing and utilities
    "DIFSRG-M",   # financial services and insurance
    "DMOTRG-M",   # motor vehicles and parts
    "DODGRG-M",   # other durable goods
    "DONGRG-M",   # other nondurable goods
    "DOTSRG-M",   # other services
    "DRCARG-M",   # recreation services
    "DREQRG-M",   # recreational goods and vehicles
    "DTRSRG-M",   # transportation services
]

TRIM = 0.30          # drop 30% from each tail


def _annualised_3m(pairs: list[tuple[str, float]]) -> dict[str, float]:
    out = {}
    for i in range(3, len(pairs)):
        a, b = pairs[i][1], pairs[i - 3][1]
        if a > 0 and b > 0:
            out[pairs[i][0]] = 400.0 * math.log(a / b)
    return out


def compute(*, verbose: bool = True) -> dict[str, list[tuple[str, float]]]:
    panel = dbnomics_panel("BEA", "NIPA-T20804")
    have = [c for c in COMPONENTS if c in panel]
    missing = [c for c in COMPONENTS if c not in panel]
    if verbose and missing:
        print(f"  breadth: {len(missing)} components missing ({missing[:4]}...)")
    if len(have) < 8:
        raise RuntimeError(f"breadth: only {len(have)} components available")

    rates = {c: _annualised_3m(panel[c]) for c in have}
    months = sorted(set().union(*[set(r) for r in rates.values()]))
    trimmed, diffusion = [], []
    for m in months:
        vals = [rates[c][m] for c in have if m in rates[c]]
        if len(vals) < 8:
            continue
        vals.sort()
        k = int(len(vals) * TRIM)
        core = vals[k:len(vals) - k] or vals
        trimmed.append((m, statistics.fmean(core)))
        diffusion.append((m, 100.0 * sum(1 for v in vals if v > 0) / len(vals)))

    return {"us.infl.trimmed_3m": trimmed, "us.infl.pce_diffusion": diffusion}


def run(conn=None, *, vintage: int | None = None, verbose: bool = True) -> dict:
    conn = conn or db.connect()
    vintage = vintage or db.latest_vintage(conn)
    if not vintage:
        raise RuntimeError("no snapshot vintage")
    db.upsert_series(conn, catalog.BREADTH)

    run_id = db.start_run(conn, "breadth")
    produced = compute(verbose=verbose)
    total = 0
    for sid, obs in produced.items():
        total += db.write_observations(conn, sid, obs, vintage)
        if verbose:
            print(f"  ok   {sid:<26} {len(obs):>6} obs  {obs[0][0]} .. {obs[-1][0]}  "
                  f"last={obs[-1][1]:.3f}")
    db.bump_vintage_count(conn, vintage)
    db.finish_run(conn, run_id, status="ok", vintage_id=vintage,
                  n_series=len(produced), n_rows=total,
                  detail="panel aggregates from BEA NIPA-T20804")
    if verbose:
        print(f"\nL1b: {len(produced)} panel aggregates, {total:,} rows")
    return {"vintage": vintage, "rows": total}
