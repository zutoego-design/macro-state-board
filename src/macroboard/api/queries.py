"""Read model: turns the vintage-correct database into API payloads.

Everything the board shows comes from here, and everything here is derived
from L2 composites first. L0/L1 series are exposed for drill-down, never as
the headline.
"""

from __future__ import annotations

import datetime as dt
import statistics

from .. import catalog, db
from ..pipeline import percentile_map, to_monthly

# NBER peak/trough months — public knowledge, hard-coded, not fetched.
RECESSIONS = [
    ("1960-04", "1961-02"), ("1969-12", "1970-11"), ("1973-11", "1975-03"),
    ("1980-01", "1980-07"), ("1981-07", "1982-11"), ("1990-07", "1991-03"),
    ("2001-03", "2001-11"), ("2007-12", "2009-06"), ("2020-02", "2020-04"),
]

AGGREGATES = ["us.agg.growth", "us.agg.inflation", "us.agg.financial",
              "us.agg.policy", "us.agg.risk"]

# the four that fill the top row: risk is the one a reader wants most
HERO = ["us.agg.growth", "us.agg.inflation", "us.agg.financial", "us.agg.risk"]

KEY_INPUTS = ["us.curve.10y2y", "us.curve.10y3m", "us.rates.real10y",
              "us.rates.real_policy", "us.infl.pce_core_yoy", "us.infl.pce_core_3m",
              "us.infl.trimmed_3m", "us.infl.pce_diffusion", "us.labor.unrate",
              "us.labor.unrate_chg12", "us.growth.ip_yoy", "us.growth.cli_6m",
              "us.market.spx_dd", "us.market.vix"]


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def to_iso(period: str) -> str:
    p = str(period)
    if "-Q" in p.upper():                 # 2026-Q2 -> 2026-04-01 (quarter start)
        y, q = p.upper().split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    if len(p) == 10:
        return p
    if len(p) == 7:                       # 2026-09 -> 2026-09-01
        return p + "-01"
    if len(p) == 4:
        return p + "-01-01"
    return p


def points(rows: list[tuple[str, float]], limit: int | None = None) -> list[dict]:
    if limit:
        rows = rows[-limit:]
    return [{"p": p, "t": to_iso(p), "v": round(v, 4)} for p, v in rows]


def yr_cut(rows: list[tuple[str, float]], years: float) -> list[tuple[str, float]]:
    if not years or not rows:
        return rows
    last = dt.date.fromisoformat(to_iso(rows[-1][0]))
    cut = (last - dt.timedelta(days=int(365.25 * years))).isoformat()
    return [(p, v) for p, v in rows if to_iso(p) >= cut]


def _monthly(rows: list[tuple[str, float]], freq: str) -> list[tuple[str, float]]:
    return to_monthly(rows, freq or "M")


def pct_rank(rows: list[tuple[str, float]], freq: str = "M", window: int = 120) -> float | None:
    """Share of the trailing 120 MONTHS at or below the latest reading.

    Aggregating to months first matters: 120 daily observations is four
    months, 120 quarterly observations is thirty years, and neither is the
    ten-year window the board claims.
    """
    vals = [v for _, v in _monthly(rows, freq)[-window:]]
    if len(vals) < 12:
        return None
    x = vals[-1]
    return 100.0 * sum(1 for v in vals if v <= x) / len(vals)


def zscore(rows: list[tuple[str, float]], freq: str = "M", window: int = 120) -> float | None:
    vals = [v for _, v in _monthly(rows, freq)[-window:]]
    if len(vals) < 12:
        return None
    mu = statistics.fmean(vals)
    sd = statistics.pstdev(vals)
    return (vals[-1] - mu) / sd if sd > 1e-12 else 0.0


def change(rows: list[tuple[str, float]], steps: int = 3) -> float | None:
    if len(rows) <= steps:
        return None
    return rows[-1][1] - rows[-1 - steps][1]


def last_value(rows, default=None):
    return rows[-1][1] if rows else default


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------

def meta(conn) -> dict:
    v = db.vintage_meta(conn)
    cat = {r["series_id"]: r for r in db.catalog(conn)}
    snap = db.snapshot(conn, v.get("vintage_id"))
    last_by_layer: dict[str, str] = {}
    for sid, rows in snap.items():
        layer = cat.get(sid, {}).get("layer", "raw")
        stamp = to_iso(rows[-1][0]) if rows else ""
        if stamp > last_by_layer.get(layer, ""):
            last_by_layer[layer] = stamp
    as_of = max([s for s in last_by_layer.values() if s], default=None)
    return {
        "as_of": as_of,
        "vintage": v.get("vintage_id"),
        "vintage_as_of": v.get("as_of"),
        "n_vintages": v.get("n_vintages", 0),
        "layers": {
            "raw": sum(1 for r in cat.values() if r["layer"] == "raw"),
            "derived": sum(1 for r in cat.values() if r["layer"] == "derived"),
            "composite": sum(1 for r in cat.values() if r["layer"] == "composite"),
        },
        "last_by_layer": last_by_layer,
        "recent_runs": db.recent_runs(conn, 6),
        "tracker": trackers(conn),
    }


def catalog_payload(conn) -> list[dict]:
    snap = db.snapshot(conn)
    out = []
    for r in db.catalog(conn):
        rows = snap.get(r["series_id"], [])
        out.append({
            "id": r["series_id"], "title": r["title"], "short": r["short_title"],
            "layer": r["layer"], "group": r["group_id"], "unit": r["unit"],
            "freq": r["frequency"], "source": f"{r['source']} · {r['provider']} · {r['series_code']}",
            "method": r["method_note"], "question": r["question"],
            "coverage": r["coverage"],
            "last": rows[-1][0] if rows else None,
            "n_obs": len(rows),
        })
    return out


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------

def series_payload(conn, series_id: str, *, years: float = 0, limit: int | None = None) -> dict | None:
    cat = {r["series_id"]: r for r in db.catalog(conn)}
    row = cat.get(series_id)
    if not row:
        return None
    snap = db.snapshot(conn)
    rows = snap.get(series_id, [])
    if not rows and row["layer"] == "raw":
        rows = db.tracker_history(conn, series_id)
    rows = yr_cut(rows, years) if years else rows
    payload = {
        "id": series_id, "title": row["title"], "short": row["short_title"],
        "layer": row["layer"], "group": row["group_id"], "unit": row["unit"],
        "freq": row["frequency"], "method": row["method_note"],
        "question": row["question"], "coverage": row["coverage"],
        "points": points(rows, limit),
        "last": rows[-1][1] if rows else None,
        "last_period": rows[-1][0] if rows else None,
        "n_obs": len(rows),
        "z": round(zscore(rows, row["frequency"]) or 0, 2) if rows else None,
        "pct_rank": round(pct_rank(rows, row["frequency"])) if rows else None,
    }
    if row["layer"] == "composite":
        meta = db.composite_meta(conn, series_id, rows[-1][0] if rows else None)
        if meta:
            payload["inputs_as_of"] = {
                "oldest": meta["oldest_input"], "newest": meta["newest_input"],
                "n_inputs": meta["n_inputs"],
                "weight_covered": round(meta["weight_covered"], 2),
            }
        inputs = db.composite_inputs(conn, series_id)
        payload["inputs"] = [
            {"id": i["input_id"], "weight": i["weight"], "sign": i["sign"],
             "transform": i["transform"],
             "title": cat.get(i["input_id"], {}).get("short_title") or i["input_id"],
             "last": (snap.get(i["input_id"], [])[-1][1]
                      if snap.get(i["input_id"]) else None)}
            for i in inputs
        ]
    return payload


def batch(conn, ids: list[str], *, years: float = 0) -> dict:
    return {sid: series_payload(conn, sid, years=years) for sid in ids}


# ---------------------------------------------------------------------------
# overview: what the board's first screen needs
# ---------------------------------------------------------------------------

def _as_of(conn, composite_id: str, period: str) -> dict | None:
    meta = db.composite_meta(conn, composite_id, period)
    if not meta:
        return None
    return {"oldest": meta["oldest_input"], "newest": meta["newest_input"],
            "n_inputs": meta["n_inputs"],
            "weight_covered": round(meta["weight_covered"], 2)}


def _signal_for(cid: str, value: float | None, pct: float | None) -> dict:
    if value is None:
        return {"text": "no data", "level": ""}
    if cid == "us.agg.risk":
        if value >= 70:
            return {"text": "late cycle", "level": "neg"}
        if value >= 45:
            return {"text": "watch", "level": "warn"}
        return {"text": "benign", "level": "pos"}
    if cid == "us.agg.growth":
        if value <= -0.5:
            return {"text": "contracting", "level": "neg"}
        if value < 0:
            return {"text": "fading", "level": "warn"}
        return {"text": "expanding", "level": "pos"}
    if cid == "us.agg.inflation":
        if value >= 1.0:
            return {"text": "hot", "level": "neg"}
        if value >= -0.2:
            return {"text": "sticky", "level": "warn"}
        return {"text": "cooling", "level": "pos"}
    if cid == "us.agg.financial":
        if value >= 1.0:
            return {"text": "tight", "level": "neg"}
        if value >= -0.3:
            return {"text": "neutral", "level": "warn"}
        return {"text": "loose", "level": "pos"}
    if cid == "us.agg.policy":
        return {"text": "restrictive" if value > 0.3 else "neutral",
                "level": "warn" if value > 0.3 else "pos"}
    return {"text": "", "level": ""}


def decompose(conn, snap, composite_id: str) -> list[dict]:
    """Contribution of each input to the composite's latest reading.

    contribution = weight * sign * z(input) / sum(|weight|)

    The contributions sum to the composite value, which is what makes the
    aggregate arguable: you can see which input moved it.
    """
    inputs = db.composite_inputs(conn, composite_id)
    if not inputs:
        return []
    cat = {r["series_id"]: r for r in db.catalog(conn)}
    total = sum(abs(i["weight"]) for i in inputs) or 1.0
    out = []
    for i in inputs:
        rows = snap.get(i["input_id"], [])
        z = zscore(rows, cat.get(i["input_id"], {}).get("frequency", "M")) if rows else None
        contrib = (i["weight"] * i["sign"] * z / total) if z is not None else None
        out.append({
            "id": i["input_id"],
            "title": cat.get(i["input_id"], {}).get("short_title") or i["input_id"],
            "layer": cat.get(i["input_id"], {}).get("layer", "raw"),
            "weight": i["weight"],
            "sign": i["sign"],
            "z": round(z, 2) if z is not None else None,
            "contribution": round(contrib, 3) if contrib is not None else None,
        })
    out.sort(key=lambda d: abs(d["contribution"] or 0), reverse=True)
    return out


def overview(conn) -> dict:
    snap = db.snapshot(conn)
    cat = {r["series_id"]: r for r in db.catalog(conn)}

    hero = []
    for cid in HERO:
        rows = snap.get(cid, [])
        if not rows:
            continue
        val = rows[-1][1]
        pct = pct_rank(rows, cat[cid]["frequency"])
        chg = change(rows, 3)
        hero.append({
            "id": cid,
            "label": cat[cid]["short_title"],
            "title": cat[cid]["title"],
            "unit": cat[cid]["unit"],
            "value": round(val, 2),
            "pct_rank": round(pct) if pct is not None else None,
            "chg_3m": round(chg, 2) if chg is not None else None,
            "signal": _signal_for(cid, val, pct),
            "spark": points(rows[-36:]),
            "method": cat[cid]["method_note"],
"decomposition": decompose(conn, snap, cid),
            "inputs_as_of": _as_of(conn, cid, rows[-1][0]),
        })

    regime_rows = []
    growth = dict(snap.get("us.agg.growth", []))
    infl = dict(snap.get("us.agg.inflation", []))
    for m in sorted(set(growth) & set(infl))[-84:]:
        regime_rows.append({"p": m, "g": round(growth[m], 3), "i": round(infl[m], 3)})

    cur = regime_rows[-1] if regime_rows else None
    if cur:
        g, i = cur["g"], cur["i"]
        if g > 0 and i > 0:
            quad, desc = "REFLATION", "growth positive, inflation still running hot"
        elif g > 0 and i < 0:
            quad, desc = "EXPANSION", "growth positive, price pressure cooling"
        elif g < 0 and i > 0:
            quad, desc = "STAGFLATION", "growth impulse negative while inflation stays elevated"
        else:
            quad, desc = "SLOWDOWN", "growth negative, inflation falling"
    else:
        quad, desc = "NO DATA", ""

    return {
        "hero": hero,
        "recessions": RECESSIONS,
        "regime": {
            "points": regime_rows,
            "current": {"quadrant": quad, "desc": desc},
            "axes": {"x": "growth composite (sigma)", "y": "inflation composite (sigma)"},
        },
        "checklist": checklist(conn, snap),
        "state": state(conn, snap, cat),
    }


def checklist(conn, snap) -> dict:
    """Six binary thresholds, each reading either a composite or one input."""
    def v(sid):
        rows = snap.get(sid) or []
        return rows[-1][1] if rows else None

    items = [
        {"label": "Curve inverted", "value": v("us.curve.10y2y"), "unit": "bp",
         "detail": "10Y minus 2Y", "flag": (v("us.curve.10y2y") or 0) < 0},
        {"label": "Policy restrictive", "value": v("us.rates.real_policy"), "unit": "pct",
         "detail": "real policy rate > 1%", "flag": (v("us.rates.real_policy") or 0) > 1.0},
        {"label": "Inflation above target", "value": v("us.infl.pce_core_3m"), "unit": "pct",
         "detail": "core PCE 3M annualised > 2.5%", "flag": (v("us.infl.pce_core_3m") or 0) > 2.5},
        {"label": "Growth below trend", "value": v("us.agg.growth"), "unit": "z",
         "detail": "growth composite < 0", "flag": (v("us.agg.growth") or 0) < 0},
        {"label": "Equity drawdown > 10%", "value": v("us.market.spx_dd"), "unit": "pct",
         "detail": "S&P from 1Y high", "flag": (v("us.market.spx_dd") or 0) < -10},
        {"label": "Financial stress", "value": v("us.agg.financial"), "unit": "z",
         "detail": "FCI composite > 1 sigma", "flag": (v("us.agg.financial") or 0) > 1.0},
    ]
    flags = sum(1 for it in items if it["flag"])
    return {"items": items, "flags": flags, "total": len(items)}


def state(conn, snap, cat) -> list[dict]:
    order = AGGREGATES + KEY_INPUTS
    out = []
    for sid in order:
        rows = snap.get(sid)
        if not rows:
            continue
        c = cat[sid]
        val = rows[-1][1]
        out.append({
            "id": sid,
            "label": c["short_title"] or c["title"],
            "layer": c["layer"],
            "group": c["group_id"],
            "unit": c["unit"],
            "value": round(val, 3),
            "period": rows[-1][0],
            "chg_3m": (round(change(rows, 3), 3) if change(rows, 3) is not None else None),
            "z": (round(zscore(rows, c["frequency"]), 2) if zscore(rows, c["frequency"]) is not None else None),
            "pct_rank": (round(pct_rank(rows, c["frequency"])) if pct_rank(rows, c["frequency"]) is not None else None),
            "spark": points(rows[-36:]),
            "signal": _signal_for(sid, val, pct_rank(rows, c["frequency"])) if sid in AGGREGATES else None,
        })
    return out


# ---------------------------------------------------------------------------
# daily panel — one row per business day, one column per series
# ---------------------------------------------------------------------------

def daily_meta(conn) -> dict:
    row = conn.execute(
        "SELECT MIN(date) AS a, MAX(date) AS b, COUNT(*) AS n FROM daily_wide"
    ).fetchone()
    if not row or not row["n"]:
        return {"start": None, "end": None, "rows": 0, "columns": []}
    cols = [dict(r) for r in conn.execute(
        "SELECT * FROM daily_column ORDER BY layer DESC, series_id")]
    return {"start": row["a"], "end": row["b"], "rows": row["n"], "columns": cols}


def _titles(conn) -> dict[str, str]:
    return {r["series_id"]: (r["short_title"] or r["title"]) for r in db.catalog(conn)}


def daily_tape(conn, date: str | None = None) -> dict:
    """The panel's most recent business day, with the age of every cell."""
    meta = daily_meta(conn)
    if not meta["rows"]:
        return {"date": None, "items": []}
    d = date or meta["end"]
    row = conn.execute("SELECT * FROM daily_wide WHERE date=?", (d,)).fetchone()
    age = conn.execute("SELECT * FROM daily_age WHERE date=?", (d,)).fetchone()
    if row is None:
        return {"date": d, "items": []}
    titles = _titles(conn)
    items = []
    for c in meta["columns"]:
        v = row[c["col"]] if c["col"] in row.keys() else None
        items.append({
            "id": c["series_id"],
            "title": titles.get(c["series_id"], c["series_id"]),
            "col": c["col"],
            "layer": c["layer"], "freq": c["freq"], "unit": c["unit"],
            "value": (round(v, 4) if v is not None else None),
            "age_days": (age[c["col"]] if age is not None and c["col"] in age.keys() else None),
        })
    items.sort(key=lambda x: (x["age_days"] if x["age_days"] is not None else 10**6, x["id"]))
    fresh = sum(1 for i in items if i["age_days"] == 0)
    return {"date": d, "items": items, "fresh": fresh, "total": len(items)}


def daily_slice(conn, *, start: str | None = None, end: str | None = None,
                ids: list[str] | None = None, limit: int = 5000) -> dict:
    """Wide slice as arrays: cheap to transfer, easy to pivot client-side."""
    import pandas as pd

    meta = daily_meta(conn)
    if not meta["rows"]:
        return {"date": [], "columns": [], "rows": []}
    cols = meta["columns"]
    if ids:
        wanted = {column_of(s) for s in ids} | set(ids)
        cols = [c for c in cols if c["col"] in wanted or c["series_id"] in ids]
    selected = ["date"] + [c["col"] for c in cols]
    start = start or "1900-01-01"
    end = end or meta["end"]
    sql = (f"SELECT {','.join('\"' + c + '\"' for c in selected)} FROM daily_wide "
           f"WHERE date BETWEEN ? AND ? ORDER BY date DESC LIMIT ?")
    frame = pd.read_sql_query(sql, conn, params=(start, end, limit))
    frame = frame.iloc[::-1].reset_index(drop=True)
    return {
        "columns": [{k: c[k] for k in ("col", "series_id", "layer", "freq", "unit")} for c in cols],
        "dates": frame["date"].tolist(),
        "rows": frame.drop(columns=["date"]).values.tolist(),
    }


def column_of(series_id: str) -> str:
    return series_id.replace(".", "_").replace("-", "_")


def provenance(conn) -> list[dict]:
    out = []
    for r in db.catalog(conn):
        if r["layer"] == "composite":
            continue
        out.append({
            "id": r["series_id"], "title": r["title"], "layer": r["layer"],
            "source": r["source"], "dataset": r["dataset"], "code": r["series_code"],
            "coverage": r["coverage"], "freq": r["frequency"],
            "method": r["method_note"],
        })
    return out


def trackers(conn) -> dict:
    """Latest-print log: what the wire said today, and what moved."""
    states = db.tracker_states(conn)
    if not states:
        return {"date": None, "recorded": 0, "changed": 0, "items": []}
    last_run = max((s.get("last_run") or "") for s in states)[:10]
    cat = {r["series_id"]: r for r in db.catalog(conn)}
    items = []
    for s in states:
        sid = s["series_id"]
        hist = db.tracker_history(conn, sid)
        if not hist:
            continue
        prev = hist[-2][1] if len(hist) > 1 else None
        items.append({
            "id": sid,
            "title": cat.get(sid, {}).get("short_title") or sid,
            "layer": cat.get(sid, {}).get("layer", "raw"),
            "value": hist[-1][1],
            "prev": prev,
            "delta": (hist[-1][1] - prev) if prev is not None else None,
            "period": s.get("last_run"),
            "n_points": len(hist),
        })
    changed = sum(1 for i in items if i["delta"] not in (None, 0))
    items.sort(key=lambda d: abs(d["delta"] or 0), reverse=True)
    return {"date": last_run, "recorded": len(items), "changed": changed, "items": items}

def notes(conn, snap) -> list[str]:
    meta_ = meta(conn)
    return [
        "<b>What this is.</b> A point-in-time macro database with one dependent question: "
        "<i>where in the cycle are we, and what does that imply for the next twelve months?</i> "
        "The board shows aggregates; every aggregate can be decomposed into the inputs it was "
        "built from.",
        "<b>Bottom-up, not top-down.</b> L0 raw series come from providers untouched. L1 turns "
        "them into comparable transforms, and includes panel aggregates (trimmed-mean PCE, "
        "component diffusion) that no provider publishes for us. L2 combines them into five "
        "composites, each declared in the database with explicit weights and signs — you can "
        "rebuild any of them by hand.",
        f"<b>Vintage discipline.</b> {meta_['layers']['raw']} raw + {meta_['layers']['derived']} "
        f"derived + {meta_['layers']['composite']} composite series, "
        f"{meta_['n_vintages']} vintage(s) stored. Every ingest appends a vintage; nothing is "
        "overwritten, so any past view can be replayed.",
        "<b>Known gaps.</b> The BLS direct API and FRED refuse this host, so the labour series "
        "here is OECD's harmonised measure and CPI is OECD's series rather than the BLS print. "
        "Series that exist only as a current value (GDPNow) are collected by our own tracker, "
        "which means their history starts the day collection started — that is stated, not hidden.",
    ]
