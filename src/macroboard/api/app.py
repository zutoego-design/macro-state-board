"""FastAPI backend.

The frontend is a static app that talks to these endpoints only, so the two
halves can be developed, cached and replaced independently.

    GET /api/health
    GET /api/meta
    GET /api/overview            aggregates, regime, checklist, state
    GET /api/catalog
    GET /api/series?ids=a,b,c&years=10
    GET /api/series/{series_id}
    GET /api/provenance
    GET /api/trackers
    GET /api/runs
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import config, db
from . import queries

app = FastAPI(title="Macro State Board API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _conn():
    conn = db.connect()
    db.init(conn)
    return conn


@app.get("/api/health")
def health():
    try:
        conn = _conn()
        n = conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
        v = db.latest_vintage(conn)
        return {"ok": True, "observations": n, "vintage": v}
    except Exception as exc:  # pragma: no cover
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/api/meta")
def get_meta():
    return queries.meta(_conn())


@app.get("/api/overview")
def get_overview():
    conn = _conn()
    out = queries.overview(conn)
    out["notes"] = queries.notes(conn, db.snapshot(conn))
    out["meta"] = queries.meta(conn)
    return out


@app.get("/api/catalog")
def get_catalog():
    return {"series": queries.catalog_payload(_conn())}


@app.get("/api/series")
def get_series(
    ids: str = Query(..., description="comma separated series ids"),
    years: float = Query(0, description="0 = all history"),
):
    conn = _conn()
    wanted = [s.strip() for s in ids.split(",") if s.strip()]
    data = queries.batch(conn, wanted, years=years)
    missing = [k for k, v in data.items() if v is None]
    if missing and len(missing) == len(wanted):
        raise HTTPException(status_code=404, detail=f"unknown series: {missing}")
    return {"series": {k: v for k, v in data.items() if v is not None}, "missing": missing}


@app.get("/api/series/{series_id}")
def get_one(series_id: str, years: float = Query(0)):
    payload = queries.series_payload(_conn(), series_id, years=years)
    if payload is None:
        raise HTTPException(status_code=404, detail="unknown series")
    return payload


@app.get("/api/provenance")
def get_provenance():
    return {"series": queries.provenance(_conn())}


@app.get("/api/trackers")
def get_trackers():
    return {"trackers": queries.trackers(_conn())}


@app.get("/api/runs")
def get_runs(limit: int = 20):
    return {"runs": db.recent_runs(_conn(), limit)}


# ---- daily panel -----------------------------------------------------------

@app.get("/api/daily/meta")
def daily_meta():
    return queries.daily_meta(_conn())


@app.get("/api/daily/tape")
def daily_tape(date: str | None = None):
    return queries.daily_tape(_conn(), date)


@app.get("/api/daily")
def daily_panel(start: str | None = None, end: str | None = None,
                ids: str | None = None, limit: int = 5000):
    wanted = [s.strip() for s in ids.split(",")] if ids else None
    return queries.daily_slice(_conn(), start=start, end=end, ids=wanted, limit=limit)


@app.get("/api/daily.csv")
def daily_csv():
    """The whole wide panel as a CSV, regenerated on request."""
    import pandas as pd
    from fastapi.responses import FileResponse

    out_dir = config.DATA / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "daily_wide.csv"
    conn = _conn()
    if not queries.daily_meta(conn)["rows"]:
        raise HTTPException(status_code=404, detail="daily panel not built")
    pd.read_sql_query("SELECT * FROM daily_wide ORDER BY date", conn).to_csv(path, index=False)
    return FileResponse(path, media_type="text/csv", filename="daily_wide.csv")


# ---- static frontend -------------------------------------------------------
if config.WEB.exists():
    app.mount("/static", StaticFiles(directory=str(config.WEB)), name="static")


@app.get("/")
def index():
    f = config.WEB / "index.html"
    if not f.exists():
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(f, media_type="text/html")
