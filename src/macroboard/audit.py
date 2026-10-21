"""Audit: what is in the database, and are the dates aligned?

Answers three questions with evidence rather than assertion:

  1. What exists — per series: layer, frequency, coverage, observation count,
     and the gap between the last observation and the moment we pulled it.
  2. Publication vs valuation date — every period is the date the number
     refers to; every vintage is when we saw it. The difference is the
     publication lag, and it is not the same across series.
  3. Is anything misaligned — a composite is stamped with a month, but its
     inputs may be older. This prints, for each composite's latest month, the
     actual age of every input it was built from.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import catalog, db


def _months_between(a: str, b: str) -> int:
    """Month distance between two period labels, handling quarters."""
    def to_month(p: str) -> tuple[int, int]:
        p = str(p)
        if "-Q" in p.upper():
            y, q = p.upper().split("-Q")
            return int(y), int(q) * 3
        return int(p[:4]), int(p[5:7] or 1)

    (ya, ma), (yb, mb) = to_month(a), to_month(b)
    return (yb - ya) * 12 + (mb - ma)


def _period_end(period: str) -> str:
    p = str(period)
    if "-Q" in p.upper():
        y, q = p.upper().split("-Q")
        y, q = int(y), int(q)
        m = q * 3
        day = 31 if m in (1, 3, 5, 7, 8, 10, 12) else 30
        return f"{y}-{m:02d}-{day}"
    if len(p) == 7:
        y, m = int(p[:4]), int(p[5:7])
        nxt = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        return (nxt - dt.timedelta(days=1)).isoformat()
    return p[:10]


def audit() -> dict:
    conn = db.connect()
    db.init(conn)
    vint = db.vintage_meta(conn)
    snap = db.snapshot(conn)
    cat = {r["series_id"]: r for r in db.catalog(conn)}
    pulled = (vint.get("as_of") or "")[:10]

    rows = []
    for sid, meta in cat.items():
        obs = snap.get(sid) or []
        if not obs:
            rows.append({"id": sid, "layer": meta["layer"], "freq": meta["frequency"],
                         "n": 0, "first": None, "last": None, "lag_days": None})
            continue
        first, last = obs[0][0], obs[-1][0]
        lag = None
        if pulled and last:
            try:
                lag = (dt.date.fromisoformat(pulled) - dt.date.fromisoformat(_period_end(last))).days
            except ValueError:
                lag = None
        rows.append({
            "id": sid, "title": meta["title"], "layer": meta["layer"],
            "group": meta["group_id"], "freq": meta["frequency"],
            "n": len(obs), "first": first, "last": last, "lag_days": lag,
            "source": f"{meta['source']}/{meta['provider']}",
        })

    # per-frequency freshness
    by_freq = defaultdict(list)
    for r in rows:
        if r["n"]:
            by_freq[r["freq"]].append(r)

    # composite alignment: latest month vs the newest month of each input
    alignment = []
    for comp in catalog.COMPOSITES:
        cid = comp["series_id"]
        obs = snap.get(cid) or []
        if not obs:
            continue
        month = obs[-1][0]
        inputs = []
        for i in db.composite_inputs(conn, cid):
            src = snap.get(i["input_id"]) or []
            last = src[-1][0] if src else None
            age = _months_between(last[:7], month) if last and len(month) == 7 else None
            inputs.append({
                "id": i["input_id"],
                "short": cat.get(i["input_id"], {}).get("short_title") or i["input_id"],
                "last": last,
                "stale_months": age,
                "weight": i["weight"],
            })
        inputs.sort(key=lambda d: -(d["stale_months"] or 0))
        alignment.append({
            "composite": cid,
            "month": month,
            "max_stale_months": max((d["stale_months"] or 0) for d in inputs),
            "inputs": inputs,
        })

    runs = db.recent_runs(conn, 8)
    return {
        "pulled": pulled,
        "vintage": vint.get("vintage_id"),
        "vintages": vint.get("n_vintages"),
        "rows": rows,
        "by_freq": {k: len(v) for k, v in by_freq.items()},
        "alignment": alignment,
        "runs": runs,
        "tracker": db.tracker_states(conn),
    }


def render(res: dict) -> str:
    out = []
    w = out.append
    w(f"vintage {res['vintage']} · pulled {res['pulled']} · {res['vintages']} vintage(s) stored")
    w(f"frequencies: {res['by_freq']}")
    w("")
    w(f"{'series':<26}{'layer':<10}{'f':<3}{'n':>7}  {'first':<10}{'last':<10}{'lag':>6}")
    w("-" * 76)
    for r in [x for x in res["rows"] if x["n"]]:
        if r["lag_days"] is None:
            lag = "—"
        elif r["lag_days"] < 0:
            lag = "partial"
        else:
            lag = f"{r['lag_days']}d"
        w(f"{r['id']:<26}{r['layer']:<10}{r['freq']:<3}{r['n']:>7}  "
          f"{r['first']:<10}{r['last']:<10}{lag:>6}")
    empty = [x for x in res["rows"] if not x["n"]]
    if empty:
        w(f"  ({len(empty)} declared but empty)")
    w("")
    w("composite alignment — latest month vs its inputs")
    w("-" * 76)
    for a in res["alignment"]:
        w(f"{a['composite']:<20} latest {a['month']}  worst input gap {a['max_stale_months']} months")
        for i in a["inputs"]:
            w(f"    {i['short']:<26}{str(i['last']):<12}"
              f"{'stale ' + str(i['stale_months']) + 'm' if i['stale_months'] else 'fresh'}")
    w("")
    w("recent runs")
    w("-" * 76)
    for r in res["runs"]:
        w(f"  {r['started_at']}  {r['task']:<10} {r['status']:<8} "
          f"{r['n_series'] or 0:>3} series {r['n_rows'] or 0:>7} rows  {r['detail'] or ''}"[:120])
    return "\n".join(out)
