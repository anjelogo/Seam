import argparse
import asyncio
import logging
import os
from datetime import timezone

from seam_shared import db

from app.sources import ADAPTERS
from app.worker import app, tasks

log = logging.getLogger("seam.worker")


async def ensure_schema():
    async with db.apool().connection() as conn:
        row = await (await conn.execute("SELECT to_regclass('procrastinate_jobs') AS t")).fetchone()
    if row["t"] is None:
        log.info("applying procrastinate schema")
        await app.schema_manager.apply_schema_async()


async def pending(queues: list[str]) -> int:
    async with db.apool().connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM procrastinate_jobs WHERE status IN ('todo', 'doing') AND queue_name = ANY(%s)", (queues,)
        )
        return (await cur.fetchone())["n"]


def infra_line() -> str:
    on = {k: bool((os.getenv(k) or "").strip()) for k in ("SCRAPE_PROXY", "FLARESOLVERR_URL", "GLUETUN_CONTROL_URL")}
    on["GLUETUN_ROTATE"] = on["GLUETUN_CONTROL_URL"] and (os.getenv("GLUETUN_ROTATE") or "").strip().lower() == "true"
    return "scrape infra: " + " ".join(f"{k.lower()}={'on' if v else 'off'}" for k, v in on.items())


async def work(queues: list[str], once: bool):
    cv = int(os.getenv("CV_CONCURRENCY") or 1)
    concurrency = max(1, (3 * len(ADAPTERS) if "scrape" in queues else 0) + (cv if "cv" in queues else 0))
    log.info(infra_line())
    log.info("worker on %s, concurrency %d", ",".join(queues), concurrency)
    if not once:
        await app.run_worker_async(queues=queues, concurrency=concurrency)
        return
    # wait=False stops at the first empty fetch, so repeat for jobs deferred by running jobs
    while await pending(queues):
        await app.run_worker_async(queues=queues, concurrency=concurrency, wait=False)
    log.info("queues drained")


async def main(args):
    await db.apool().open()
    async with app.open_async():
        await ensure_schema()
        if args.command == "enqueue-all":
            await tasks.scrape_all.defer_async()
            log.info("deferred scrape_all")
        else:
            await work([q.strip() for q in args.queues.split(",") if q.strip()], args.once)


def status():
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 20").fetchall()
    print(f"{'id':>5} {'source':9} {'query':12} {'slot':7} {'started (utc)':19} {'secs':>5} {'fetch':>5} {'add':>4} {'upd':>4} {'err':>4}  last_error")
    for r in rows:
        secs = f"{(r['finished_at'] - r['started_at']).total_seconds():.0f}" if r["finished_at"] else "-"
        started = r["started_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{r['id']:>5} {r['source']:9} {r['query'][:12]:12} {r['slot'] or '-':7} {started:19} {secs:>5} "
            f"{r['fetched'] if r['fetched'] is not None else '-':>5} {r['added'] or 0:>4} {r['updated'] or 0:>4} {r['errors'] or 0:>4}  "
            f"{(r['last_error'] or '')[:80]}"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="python -m app.worker")
    p.add_argument("command", nargs="?", choices=["enqueue-all", "status"])
    p.add_argument("--queues", default="scrape,default,cv")
    p.add_argument("--once", action="store_true", help="exit once the queues are drained")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "status":
        status()
    else:
        asyncio.run(main(args))
