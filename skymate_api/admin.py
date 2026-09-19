"""Command-line administration: py -m skymate_api.admin <command>"""
import argparse
import json
import logging
from datetime import datetime, timezone

from . import auth, db, forecast, geo, ingest


def main():
    p = argparse.ArgumentParser(prog="py -m skymate_api.admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-key", help="Create an API key for a customer")
    c.add_argument("name")
    c.add_argument("--plan", default="free", choices=list(auth.PLANS))
    sub.add_parser("list-keys")
    r = sub.add_parser("revoke", help="Revoke a key by id")
    r.add_argument("key_id", type=int)
    pl = sub.add_parser("set-plan")
    pl.add_argument("key_id", type=int)
    pl.add_argument("plan", choices=list(auth.PLANS))
    u = sub.add_parser("usage")
    u.add_argument("--days", type=int, default=30)
    sub.add_parser("status", help="Stored data freshness")
    i = sub.add_parser("ingest", help="Download the newest model run now")
    i.add_argument("model", choices=list(ingest.MODELS))
    i.add_argument("--run", help="YYYYMMDDHH (default: newest available)")
    sub.add_parser("backfill-history")
    a = p.parse_args()

    logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
    db.init()
    if a.cmd == "create-key":
        key = auth.create_key(a.name, a.plan)
        print(f"API key for {a.name} ({a.plan}):\n\n  {key}\n\nStore it now; it cannot be shown again.")
    elif a.cmd == "list-keys":
        for k in auth.list_keys():
            print(f"{k['id']:>4}  {k['key_prefix']}…  {k['plan']:<9} {'active' if k['active'] else 'REVOKED':<8} "
                  f"{k['created_at']}  {k['name']}")
    elif a.cmd == "revoke":
        auth.set_active(a.key_id, False)
        print(f"Key {a.key_id} revoked.")
    elif a.cmd == "set-plan":
        auth.set_plan(a.key_id, a.plan)
        print(f"Key {a.key_id} moved to {a.plan}.")
    elif a.cmd == "usage":
        for row in auth.usage(a.days):
            print(f"{row['day']}  {row['requests']:>8}  {row['plan']:<9} {row['name']}")
    elif a.cmd == "status":
        print(json.dumps(forecast.status(), indent=2))
    elif a.cmd == "ingest":
        geo.ensure_loaded()
        if a.run:
            run = datetime.strptime(a.run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            ingest.ingest_run(a.model, run, ingest.MODELS[a.model].available(run))
        else:
            ingest.ingest_latest(a.model)
    elif a.cmd == "backfill-history":
        ingest.backfill_history(7)


if __name__ == "__main__":
    main()
