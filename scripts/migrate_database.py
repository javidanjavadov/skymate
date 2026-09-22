"""Copy SkyMate's account data (bot users, payments, API keys, audit log) to another Postgres database.

    python scripts/migrate_database.py --to "<target url>" --from "<source url>"
    python scripts/migrate_database.py --to "<target url>" --from-render <postgres-id>   # through the Render CLI

The source is only read, so the service keeps running during the copy; switch DATABASE_URL over once the check
passes. Tables in the target are replaced, so the copy can be repeated safely.
"""
import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Parents before the tables that reference them.
TABLES = ["users", "user_settings", "user_favorites", "user_subscriptions", "premium", "payments", "app_keys",
          "alert_sent", "api_keys", "usage", "admin_audit", "place_names"]
RENDER_CLI = Path(os.environ.get("USERPROFILE", "")) / ".render-cli" / "render.exe"


def create_schema(url: str):
    """Creates the tables exactly as the service does, in the target database."""
    os.environ["DATABASE_URL"] = url
    from skymate_api import places, security, store
    store.init("bot")
    store.init("api")
    security.init_audit()
    places.init()


def render_export(postgres_id: str, table: str, columns: str) -> bytes:
    cmd = [str(RENDER_CLI), "psql", postgres_id, "--confirm", "-o", "text",
           "--command", f"COPY (SELECT {columns} FROM {table}) TO STDOUT (FORMAT csv)"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return out.replace(b"\r\n", b"\n")


def columns_of(conn, table) -> list[str]:
    rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                        "AND table_name=%s ORDER BY ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", dest="target", required=True)
    ap.add_argument("--from", dest="source")
    ap.add_argument("--from-render", dest="render_id", help="Render Postgres id, exported through the Render CLI")
    args = ap.parse_args()
    if not (args.source or args.render_id):
        raise SystemExit("Give --from <url> or --from-render <postgres-id>")

    create_schema(args.target)
    src = psycopg.connect(args.source, connect_timeout=30) if args.source else None
    report = []
    with psycopg.connect(args.target, connect_timeout=30) as dst:
        for table in TABLES:
            cols = columns_of(dst, table)
            quoted = ", ".join(f'"{c}"' for c in cols)
            if src:
                buf = io.BytesIO()
                with src.cursor().copy(f"COPY (SELECT {quoted} FROM {table}) TO STDOUT (FORMAT csv)") as out:
                    for block in out:
                        buf.write(block)
                data = buf.getvalue()
                n_src = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            else:
                data = render_export(args.render_id, table, quoted)
                n_src = len([line for line in data.split(b"\n") if line.strip()])
            dst.execute(f"TRUNCATE {table}")
            with dst.cursor().copy(f"COPY {table} ({quoted}) FROM STDIN (FORMAT csv)") as cp:
                cp.write(data)
            dst.commit()
            n_dst = dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            status = "ok" if n_src == n_dst else "MISMATCH"
            report.append((table, n_src, n_dst, status))
            print(f"{table:<20} {n_src:>7} -> {n_dst:>7}  {status}")
    if src:
        src.close()
    bad = [r[0] for r in report if r[3] != "ok"]
    print("\nALL TABLES COPIED" if not bad else f"\nPROBLEM WITH: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
