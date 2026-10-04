"""CLI for long indexing runs:  python -m app.cli index | status | search "query" """
import argparse
import time

from . import db, search as search_mod
from .indexer import indexer


def cmd_index(args):
    db.init()
    indexer.start(retry_failed=args.retry_failed)
    try:
        while indexer.is_running():
            s = indexer.state
            print(f"\r[{s['phase']}] scanned={s['scanned']} queued={s['queued']} done={s['done']} "
                  f"dup={s['duplicates']} failed={s['failed']} cur={str(s['current'] or '')[:50]:<50}",
                  end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping after current file... (progress is saved, re-run to resume)")
        indexer.stop()
        indexer.join()
    s = indexer.state
    print(f"\nfinished: phase={s['phase']} done={s['done']} duplicates={s['duplicates']} "
          f"failed={s['failed']} unchanged={s['unchanged']} unsupported={s['unsupported']} "
          f"removed={s['removed']} error={s['error']}")


def cmd_status(_):
    db.init()
    for r in db.conn().execute("SELECT status, COUNT(*) n FROM assets GROUP BY status"):
        print(f"{r['status']:12} {r['n']}")


def cmd_search(args):
    db.init()
    res = search_mod.search(args.query, type=args.type, limit=args.limit)
    print(f"{res['total']} results in {res['took_ms']} ms (type hint: {res['detected_type']})")
    for r in res["results"]:
        print(f"{r['score']:.2f}  {r['type']:5}  {r['rel_path']}  {r['match']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("index"); p.add_argument("--retry-failed", action="store_true"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("status"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--type")
    p.add_argument("--limit", type=int, default=10); p.set_defaults(fn=cmd_search)
    a = ap.parse_args()
    a.fn(a)
