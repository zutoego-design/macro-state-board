"""Command line entry point.

    python -m macroboard init        create/upgrade the database
    python -m macroboard ingest      pull L0 from providers into a new vintage
    python -m macroboard derive      compute L1 transforms
    python -m macroboard breadth     compute L1 panel aggregates
    python -m macroboard composite   compute L2 composites
    python -m macroboard track       poll current-value trackers (cron this)
    python -m macroboard refresh     ingest -> breadth -> derive -> composite
    python -m macroboard serve       run the API + frontend on :8765
    python -m macroboard status      what is in the database
"""

from __future__ import annotations

import argparse
import sys

from . import config, db


def _banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 60 - len(text)))


def cmd_init(_args) -> int:
    conn = db.connect()
    db.init(conn)
    from . import catalog
    n = db.upsert_series(conn, catalog.RAW + catalog.DERIVED + catalog.BREADTH
                         + catalog.COMPOSITES + catalog.TRACKED)
    rows = []
    for spec in catalog.COMPOSITES:
        for inp in spec.get("inputs", []):
            rows.append({**inp, "composite_id": spec["series_id"]})
    m = db.upsert_composite_inputs(conn, rows)
    retired = db.sync_active(conn, [s["series_id"] for s in
                                    catalog.RAW + catalog.DERIVED + catalog.BREADTH
                                    + catalog.COMPOSITES + catalog.TRACKED])
    print(f"database ready at {config.DB_PATH}")
    print(f"catalogue: {n} series, {m} composite inputs"
          + (f", {retired} retired" if retired else ""))
    return 0


def cmd_ingest(_args) -> int:
    from .pipeline import ingest
    res = ingest.run()
    return 0 if not res["failed"] else 1


def cmd_derive(_args) -> int:
    from .pipeline import derive
    derive.run()
    return 0


def cmd_breadth(_args) -> int:
    from .pipeline import breadth
    breadth.run()
    return 0


def cmd_composite(_args) -> int:
    from .pipeline import composite
    composite.run()
    return 0


def cmd_track(_args) -> int:
    from .pipeline import track
    res = track.run()
    return 0 if res["recorded"] else 1


def cmd_refresh(_args) -> int:
    """One full rebuild. Breadth runs before derive because compute order is:
    L0 -> L1b (panel, needs provider) -> L1 -> L2."""
    from .pipeline import breadth, composite, derive, ingest

    _banner("L0 ingest")
    ing = ingest.run()
    _banner("L1b panel aggregates")
    try:
        breadth.run(vintage=ing["vintage"])
    except Exception as exc:
        print(f"  breadth failed: {exc!r}")
    _banner("L1 transforms")
    derive.run(vintage=ing["vintage"])
    _banner("L2 composites")
    composite.run(vintage=ing["vintage"])
    return 0


def cmd_status(_args) -> int:
    conn = db.connect()
    db.init(conn)
    v = db.vintage_meta(conn)
    print(f"database : {config.DB_PATH}")
    print(f"vintage  : {v.get('vintage_id')} at {v.get('as_of')} "
          f"({v.get('n_vintages', 0)} stored)")
    print(f"rows     : {conn.execute('SELECT COUNT(*) FROM observation').fetchone()[0]:,}")
    by_layer = conn.execute(
        "SELECT layer, COUNT(*) n FROM series WHERE is_active=1 GROUP BY layer ORDER BY layer"
    ).fetchall()
    for r in by_layer:
        print(f"  {r['layer']:<10} {r['n']:>3} series")
    snap = db.snapshot(conn, v.get("vintage_id"))
    print("\nlatest by series (composites first):")
    for row in db.catalog(conn):
        rows = snap.get(row["series_id"])
        if not rows:
            continue
        print(f"  {row['series_id']:<28} {row['layer']:<10} "
              f"{rows[-1][0]:<10} {rows[-1][1]:>12.4f}  ({len(rows)} obs)")
    return 0


def cmd_audit(args) -> int:
    """What is in the database, and are the dates aligned?"""
    import json

    from . import audit
    res = audit.audit()
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(audit.render(res))
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    print(f"\n  Macro State Board  ->  http://{args.host}:{args.port}\n")
    uvicorn.run("macroboard.api.app:app", host=args.host, port=args.port,
                reload=args.reload, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="macroboard", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [
        ("init", cmd_init), ("ingest", cmd_ingest), ("derive", cmd_derive),
        ("breadth", cmd_breadth), ("composite", cmd_composite), ("track", cmd_track),
        ("refresh", cmd_refresh), ("status", cmd_status),
    ]:
        sp = sub.add_parser(name)
        sp.set_defaults(func=fn)
    sp = sub.add_parser("audit")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_audit)
    sp = sub.add_parser("serve")
    sp.add_argument("--host", default=config.HOST)
    sp.add_argument("--port", type=int, default=config.PORT)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
