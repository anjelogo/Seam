import argparse
import asyncio
import logging
import os
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import Connection
from seam_shared import db
from seam_shared.models import Asset3D, ImageView, ItemTags

from app import dedup
from app.dedup import Pair, PhotoMeta
from app.settings import DATA_DIR

log = logging.getLogger("seam.backfill")

CHUNK = 200
THREADS = 4
MAX_PHOTOS = 4
VARIANTS = ("", "_fem", "_open", "_open_fem", "_voxel")
VIEWS = {v.value for v in ImageView} - {ImageView.unknown.value}
IMAGES = """
SELECT l.id, (e.i - 1)::int AS idx, e.im->>'url' AS url, e.im->>'view' AS view
FROM listings l, jsonb_array_elements(l.listing->'images') WITH ORDINALITY e(im, i)
WHERE l.id = ANY(%s) AND e.i <= {max} AND e.im->>'url' LIKE '/static/%%'
ORDER BY l.first_seen, l.id, e.i
""".format(max=MAX_PHOTOS)
GARMENT_FACTS = """
SELECT g.id, g.tags IS NOT NULL AS tagged, coalesce(g.usable_3d, false) AS usable_3d, g.created_at,
    coalesce(a.json->>'status' = 'ready', false) AS ready
FROM garments g LEFT JOIN assets a ON a.garment_id = g.id
WHERE g.id = ANY(%s)
"""
REQUEUE = """
SELECT g.id FROM garments g JOIN photos p ON p.id = g.best_photo_id
WHERE g.tags IS NOT NULL AND p.exif_rotated AND p.state IS NULL ORDER BY g.id
"""


@dataclass
class Stats:
    listings: int = 0
    active: int = 0
    photos_new: int = 0
    photos_existing: int = 0
    photos_missing: int = 0
    photos_failed: int = 0
    photos_rotated: int = 0
    garments_created: int = 0
    garments_total: int = 0
    merges: Counter = field(default_factory=Counter)
    stock_pairs: int = 0
    vetoed: Counter = field(default_factory=Counter)
    requeue: int = 0
    deferred: int = 0
    untagged: int = 0
    no_condition: int = 0
    assets_rekeyed: int = 0
    assets_orphans: int = 0
    assets_waiting: int = 0
    assets_linked: int = 0
    assets_dropped: int = 0
    assets_key: str = ""


def _commit(conn: Connection, dry: bool) -> None:
    if not dry:
        conn.commit()


def _scope(conn: Connection, limit: int | None) -> list[str]:
    sql = "SELECT id FROM listings ORDER BY first_seen, id" + (" LIMIT %s" if limit else "")
    return [r["id"] for r in conn.execute(sql, (limit,) if limit else ())]


def columns(conn: Connection, st: Stats, dry: bool) -> None:
    rows = conn.execute("SELECT id, listing->>'seller' AS seller FROM listings WHERE seller IS NULL").fetchall()
    sellers = [(norm, r["id"]) for r in rows if (norm := db.norm_seller(r["seller"]))]
    with conn.cursor() as cur:
        cur.executemany("UPDATE listings SET seller = %s WHERE id = %s", sellers)
    brands = conn.execute("UPDATE listings SET brand_raw = brand WHERE brand_raw IS NULL AND brand IS NOT NULL").rowcount
    conditions = conn.execute(
        "UPDATE listings SET stated_condition = condition WHERE stated_condition IS NULL AND condition IS NOT NULL"
    ).rowcount
    _commit(conn, dry)
    log.info("columns: seller=%d brand_raw=%d stated_condition=%d", len(sellers), brands, conditions)


def _meta(path: Path, dry: bool) -> PhotoMeta | None:
    try:
        if not dry:
            return dedup.store_photo(path)
        img, rotated = dedup.upright(path.read_bytes())
        return PhotoMeta(str(path.relative_to(DATA_DIR)), img.width, img.height, dedup.phash(img), rotated)
    except Exception:
        log.exception("photo %s", path)
        return None


def photos(conn: Connection, st: Stats, ids: list[str], dry: bool) -> None:
    have = {(r["listing_id"], r["idx"]) for r in conn.execute("SELECT listing_id, idx FROM photos")}
    todo = []
    for r in conn.execute(IMAGES, (ids,)):
        if (r["id"], r["idx"]) in have:
            st.photos_existing += 1
            continue
        path = DATA_DIR / r["url"].removeprefix("/static/")
        if not path.is_file():
            st.photos_missing += 1
            continue
        todo.append((r["id"], r["idx"], path, r["view"]))
    views: list[tuple[str, int]] = []
    total = len({t[0] for t in todo})
    seen, last = 0, None
    with ThreadPoolExecutor(THREADS) as pool:
        for (listing_id, idx, _, view), meta in zip(todo, pool.map(lambda t: _meta(t[2], dry), todo)):
            if listing_id != last:
                seen, last = seen + 1, listing_id
                if seen % CHUNK == 0:
                    _flush_views(conn, views, dry)
                    log.info("photos: %d/%d listings, %d hashed", seen, total, st.photos_new)
            if meta is None:
                st.photos_failed += 1
                continue
            photo_id = db.upsert_photo(
                conn, listing_id, idx, path=meta.path, width=meta.width, height=meta.height, phash=meta.phash,
                exif_rotated=meta.exif_rotated,
            )
            st.photos_new += 1
            if meta.exif_rotated:
                st.photos_rotated += 1
            if view in VIEWS:
                views.append((view, photo_id))
    _flush_views(conn, views, dry)


def _flush_views(conn: Connection, views: list[tuple[str, int]], dry: bool) -> None:
    with conn.cursor() as cur:
        cur.executemany("UPDATE photos SET view = %s WHERE id = %s", views)
    views.clear()
    _commit(conn, dry)


def garments(conn: Connection, st: Stats, ids: list[str], dry: bool) -> None:
    rows = conn.execute(
        "SELECT id, coalesce(brand_raw, brand) AS brand, first_seen, tagged_at, tags FROM listings "
        "WHERE garment_id IS NULL AND id = ANY(%s) ORDER BY first_seen, id",
        (ids,),
    ).fetchall()
    photo_ids = {
        (r["listing_id"], r["idx"]): r["id"]
        for r in conn.execute("SELECT id, listing_id, idx FROM photos WHERE listing_id = ANY(%s)", (ids,))
    }
    stamps: list[tuple] = []
    tagged: list[tuple] = []
    for n, r in enumerate(rows, 1):
        garment_id = db.create_garment(conn, brand=r["brand"])
        db.assign_listing(conn, r["id"], garment_id, "first")
        stamps.append((r["first_seen"], garment_id))
        st.garments_created += 1
        if r["tags"]:
            tags = ItemTags.model_validate(r["tags"])
            db.save_garment_tags(conn, garment_id, tags, None, photo_ids.get((r["id"], tags.best_view_index)))
            tagged.append((r["tagged_at"], garment_id))
        if n % CHUNK == 0:
            _flush_stamps(conn, stamps, tagged, dry)
            log.info("garments: %d/%d", n, len(rows))
    _flush_stamps(conn, stamps, tagged, dry)


def _flush_stamps(conn: Connection, stamps: list[tuple], tagged: list[tuple], dry: bool) -> None:
    with conn.cursor() as cur:
        cur.executemany("UPDATE garments SET created_at = %s WHERE id = %s", stamps)
        cur.executemany("UPDATE garments SET tagged_at = %s WHERE id = %s", tagged)
    stamps.clear()
    tagged.clear()
    _commit(conn, dry)


def _link_file(src: Path, dst: Path, st: Stats, dry: bool) -> None:
    if not src.is_file() or dst.exists():
        return
    st.assets_linked += 1
    if dry:
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _renamed(url: str, stem: str, garment_id: str) -> str:
    name = url.rsplit("/", 1)[-1]
    return url[: len(url) - len(name)] + (garment_id + name[len(stem):] if name.startswith(stem) else name)


def _rekey(conn: Connection, item_id: str, payload: dict, garment_id: str, st: Stats, dry: bool) -> None:
    stem = item_id.replace(":", "_")
    for suffix in VARIANTS:
        _link_file(DATA_DIR / "glb" / f"{stem}{suffix}.glb", DATA_DIR / "glb" / f"{garment_id}{suffix}.glb", st, dry)
    asset = Asset3D.model_validate(payload)
    urls = {k: _renamed(u, stem, garment_id) for k in ("glb_url", "voxel_glb_url") if (u := getattr(asset, k))}
    asset = asset.model_copy(update={"item_id": garment_id, **urls})
    conn.execute(
        "UPDATE assets SET item_id = %s, garment_id = %s, json = %s::jsonb WHERE item_id = %s",
        (garment_id, garment_id, asset.model_dump_json(), item_id),
    )


def assets(conn: Connection, st: Stats, dry: bool) -> None:
    rows = conn.execute("SELECT item_id, json FROM assets WHERE garment_id IS NULL ORDER BY item_id").fetchall()
    ids = [r["item_id"] for r in rows]
    linked = db.garments_for_listings(conn, ids)
    listed = {r["id"] for r in conn.execute("SELECT id FROM listings WHERE id = ANY(%s)", (ids,))}
    for r in rows:
        garment_id = linked.get(r["item_id"])
        if garment_id:
            _rekey(conn, r["item_id"], r["json"], garment_id, st, dry)
            st.assets_rekeyed += 1
        elif r["item_id"] in listed:
            # outside a --limit scope: no garment yet, so leave it for a later run
            st.assets_waiting += 1
        else:
            conn.execute("UPDATE assets SET garment_id = item_id WHERE item_id = %s", (r["item_id"],))
            st.assets_orphans += 1
    _commit(conn, dry)
    log.info("assets: rekeyed=%d orphans=%d waiting=%d files=%d", st.assets_rekeyed, st.assets_orphans, st.assets_waiting, st.assets_linked)


def _survivor(conn: Connection, a: str, b: str) -> tuple[str, str]:
    facts = {r["id"]: r for r in conn.execute(GARMENT_FACTS, ([a, b],))}

    def key(garment_id: str) -> tuple:
        r = facts[garment_id]
        return r["ready"], r["tagged"], r["usable_3d"], -r["created_at"].timestamp(), r["id"]

    keep = max((a, b), key=key)
    return keep, b if keep == a else a


def _move_asset(conn: Connection, loser: str, survivor: str, st: Stats, dry: bool) -> None:
    rows = {
        r["garment_id"]: r
        for r in conn.execute("SELECT garment_id, item_id, json FROM assets WHERE garment_id = ANY(%s)", ([loser, survivor],))
    }
    if loser not in rows:
        return
    if survivor in rows:
        conn.execute("DELETE FROM assets WHERE garment_id = %s", (loser,))
        st.assets_dropped += 1
    else:
        _rekey(conn, rows[loser]["item_id"], rows[loser]["json"], survivor, st, dry)


def _merge(conn: Connection, where: dict[str, str], listing_id: str, pair: Pair, st: Stats, dry: bool) -> None:
    if where[listing_id] == pair.garment_id:
        return
    survivor, loser = _survivor(conn, where[listing_id], pair.garment_id)
    for r in conn.execute("SELECT id FROM listings WHERE garment_id = %s AND id <> %s", (loser, listing_id)).fetchall():
        conn.execute("UPDATE listings SET garment_id = %s WHERE id = %s", (survivor, r["id"]))
        db.log_link(conn, r["id"], loser, survivor, "merge")
        where[r["id"]] = survivor
    db.assign_listing(conn, listing_id, survivor, pair.reason, pair.score)
    where[listing_id] = survivor
    _move_asset(conn, loser, survivor, st, dry)
    conn.execute(
        "DELETE FROM garments WHERE id = %s AND NOT EXISTS (SELECT 1 FROM listings WHERE garment_id = garments.id)", (loser,)
    )
    st.merges[pair.reason] += 1


def _fresh(logged: set, where: dict[str, str], reason: str, listing_id: str, pair: Pair) -> bool:
    key = (reason, listing_id, pair.garment_id)
    if key in logged or (reason, pair.listing_id, where.get(listing_id)) in logged:
        return False
    logged.add(key)
    return True


def linking(conn: Connection, st: Stats, ids: list[str], dry: bool) -> None:
    rows = conn.execute(
        "SELECT id FROM listings WHERE status = 'active' AND id = ANY(%s) ORDER BY first_seen, id", (ids,)
    ).fetchall()
    where = {r["id"]: r["garment_id"] for r in conn.execute("SELECT id, garment_id FROM listings WHERE garment_id IS NOT NULL")}
    logged = {
        (r["reason"], r["listing_id"], r["to_garment"])
        for r in conn.execute("SELECT reason, listing_id, to_garment FROM garment_links_log WHERE reason NOT IN ('first', 'merge')")
    }
    conn.execute("SELECT pg_advisory_lock(hashtext('seam.link'))")
    try:
        for n, r in enumerate(rows, 1):
            decision = dedup.decide(conn, r["id"], older_only=True)
            if decision.link:
                _merge(conn, where, r["id"], decision.link, st, dry)
            for pair in decision.stock:
                if _fresh(logged, where, "stock_photo", r["id"], pair):
                    conn.execute("UPDATE listings SET stock_photo = true WHERE id = ANY(%s)", ([r["id"], pair.listing_id],))
                    db.log_link(conn, r["id"], where.get(r["id"]), pair.garment_id, "stock_photo", pair.score)
                    st.stock_pairs += 1
            for pair in decision.vetoed:
                if _fresh(logged, where, pair.reason, r["id"], pair):
                    db.log_link(conn, r["id"], where.get(r["id"]), pair.garment_id, pair.reason, pair.score)
                    st.vetoed[pair.reason] += 1
            if n % CHUNK == 0:
                _commit(conn, dry)
                log.info("linking: %d/%d merges=%d stock=%d", n, len(rows), sum(st.merges.values()), st.stock_pairs)
    finally:
        _commit(conn, dry)
        conn.execute("SELECT pg_advisory_unlock(hashtext('seam.link'))")


async def _defer(garment_ids: list[str]) -> int:
    from procrastinate.exceptions import AlreadyEnqueued

    from app.worker import app
    from app.worker.tasks import tag

    deferred = 0
    async with app.open_async():
        for garment_id in garment_ids:
            try:
                await tag.configure(queueing_lock=garment_id).defer_async(garment_id=garment_id, retag=True)
                deferred += 1
            except AlreadyEnqueued:
                pass
    return deferred


def recutout(conn: Connection, st: Stats, dry: bool) -> None:
    ids = [r["id"] for r in conn.execute(REQUEUE)]
    st.requeue = len(ids)
    st.untagged = conn.execute(
        "SELECT count(*) AS n FROM garments g WHERE g.tags IS NULL AND EXISTS "
        "(SELECT 1 FROM listings l WHERE l.garment_id = g.id AND l.status = 'active')"
    ).fetchone()["n"]
    st.no_condition = conn.execute("SELECT count(*) AS n FROM listings WHERE assessed_condition IS NULL").fetchone()["n"]
    if ids and not dry:
        conn.commit()
        st.deferred = asyncio.run(_defer(ids))


def assets_key(conn: Connection, st: Stats, dry: bool) -> None:
    nulls = conn.execute("SELECT count(*) AS n FROM assets WHERE garment_id IS NULL").fetchone()["n"]
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conrelid = 'assets'::regclass AND contype = 'p'"
    ).fetchone()
    current = row["def"] if row else "none"
    if nulls or current != "PRIMARY KEY (item_id)":
        st.assets_key = f"{current} (unchanged)"
        return
    conn.execute("ALTER TABLE assets DROP CONSTRAINT assets_pkey, ADD PRIMARY KEY (garment_id)")
    st.assets_key = "PRIMARY KEY (garment_id) (switched)"
    _commit(conn, dry)


def _counts(label: str, counter: Counter) -> str:
    parts = " ".join(f"{k}={v}" for k, v in sorted(counter.items()))
    return f"{label}: total={sum(counter.values())}{' ' + parts if parts else ''}"


def report(st: Stats, dry: bool) -> None:
    head = "DRY RUN" if dry else "BACKFILL"
    lines = [
        f"listings: total={st.listings} active={st.active}",
        f"photos: new={st.photos_new} existing={st.photos_existing} missing_files={st.photos_missing} "
        f"failed={st.photos_failed} exif_rewritten={st.photos_rotated}",
        f"garments: created={st.garments_created} total={st.garments_total}",
        _counts("merges", st.merges),
        f"stock_photo pairs: {st.stock_pairs}",
        _counts("vetoed pairs", st.vetoed),
        f"re-cutout queue: {st.requeue} garments (deferred {st.deferred})",
        f"untagged garments: {st.untagged}",
        f"listings missing assessed_condition: {st.no_condition}",
        f"assets: rekeyed={st.assets_rekeyed} orphans={st.assets_orphans} waiting={st.assets_waiting} "
        f"files_linked={st.assets_linked} dropped={st.assets_dropped}",
        f"assets key: {st.assets_key}",
    ]
    for line in lines:
        print(f"{head} {line}")


def run(conn: Connection, st: Stats, limit: int | None, dry: bool) -> None:
    ids = _scope(conn, limit)
    log.info("scope: %d listings, DATA_DIR=%s", len(ids), DATA_DIR)
    columns(conn, st, dry)
    photos(conn, st, ids, dry)
    garments(conn, st, ids, dry)
    assets(conn, st, dry)
    linking(conn, st, ids, dry)
    recutout(conn, st, dry)
    assets_key(conn, st, dry)
    st.listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
    st.active = conn.execute("SELECT count(*) AS n FROM listings WHERE status = 'active'").fetchone()["n"]
    st.garments_total = conn.execute("SELECT count(*) AS n FROM garments").fetchone()["n"]


def main() -> None:
    ap = argparse.ArgumentParser(prog="app.backfill", description="bring a v2 database up to the v3 garment model")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    st = Stats()
    with db.pool().connection() as conn:
        if args.dry_run:
            with conn.transaction(force_rollback=True):
                run(conn, st, args.limit, True)
        else:
            run(conn, st, args.limit, False)
    report(st, args.dry_run)


if __name__ == "__main__":
    main()
