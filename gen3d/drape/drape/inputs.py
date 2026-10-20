"""Export the PoC input items (item.json + cutout.png + photo.jpg) from prod into runs/inputs/."""

from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import httpx
from PIL import Image

if TYPE_CHECKING:
    from seam_shared.models import Item

ROLES = ("sweats", "hoodie", "jeans", "tee")
STATIC_BASE = "http://10.10.10.101:8080"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
RE_SWEAT = re.compile(r"sweat|jogger", re.I)
RE_BAGGY = re.compile(r"baggy", re.I)


def _rules() -> dict[str, tuple[tuple[str, ...], Callable[["Item"], int | None]]]:
    """role -> (categories to query, score fn returning None when the item does not qualify)."""
    loose = {"oversized": 3, "relaxed": 2}

    def sweats(it: "Item") -> int | None:
        cat = it.tags.category.value
        if cat not in ("pants", "cargo", "jeans"):
            return None
        if not (RE_SWEAT.search(it.listing.title or "") or any(RE_SWEAT.search(t) for t in it.tags.style_tags)):
            return None
        return 10 + loose.get(it.tags.fit.value, 0) + (1 if cat == "pants" else 0)

    def hoodie(it: "Item") -> int | None:
        cat = it.tags.category.value
        if cat not in ("hoodie", "sweatshirt"):
            return None
        return loose.get(it.tags.fit.value, 0) + (2 if cat == "hoodie" else 0)

    def jeans(it: "Item") -> int | None:
        if it.tags.category.value != "jeans":
            return None
        return loose.get(it.tags.fit.value, 0) + (2 if RE_BAGGY.search(it.listing.title or "") else 0)

    def tee(it: "Item") -> int | None:
        if it.tags.category.value != "tee":
            return None
        return loose.get(it.tags.fit.value, 0)

    return {
        "sweats": (("pants", "cargo", "jeans"), sweats),
        "hoodie": (("hoodie", "sweatshirt"), hoodie),
        "jeans": (("jeans",), jeans),
        "tee": (("tee",), tee),
    }


def _candidates(conn, categories: tuple[str, ...], score) -> list["Item"]:
    from seam_shared import db

    scored = []
    for cat in categories:
        items, _ = db.get_items(conn, category=cat, usable_3d=True, status="active", order="id", limit=500)
        for it in items:
            if not (it.tags and it.tags.clean_image and it.tags.clean_image.url):
                continue
            s = score(it)
            if s is not None:
                scored.append((s, it))
    scored.sort(key=lambda p: (-p[0], p[1].id))
    return [it for _, it in scored]


def _fetch(client: httpx.Client, url: str, static_base: str) -> bytes:
    full = static_base.rstrip("/") + url if url.startswith("/static/") else url
    err: Exception | None = None
    for _ in range(3):
        try:
            r = client.get(full, headers={"User-Agent": UA}, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except Exception as e:
            err = e
    raise RuntimeError(f"fetch failed: {full} ({err})")


def _write(out: Path, item: "Item", role: str, cutout: Image.Image, photo: Image.Image) -> dict:
    safe = item.id.replace(":", "_")
    d = out / safe
    d.mkdir(parents=True, exist_ok=True)
    (d / "item.json").write_text(item.model_dump_json(indent=2))
    cutout.save(d / "cutout.png")
    photo.save(d / "photo.jpg", quality=92)
    t = item.tags
    return {
        "id": item.id, "safe": safe, "role": role, "category": t.category.value, "fit": t.fit.value,
        "material": t.material, "size_normalized": t.size_normalized, "title": item.listing.title,
        "_dims": {"cutout": list(cutout.size), "photo": list(photo.size)},
    }


def _export(out: Path, item: "Item", role: str, client: httpx.Client, static_base: str) -> dict:
    cutout = Image.open(io.BytesIO(_fetch(client, item.tags.clean_image.url, static_base))).convert("RGBA")
    if cutout.getextrema()[3][1] == 0:
        raise RuntimeError("cutout is fully transparent")
    imgs = item.listing.images
    if not imgs:
        raise RuntimeError("listing has no images")
    i = item.tags.best_view_index
    ref = imgs[i] if 0 <= i < len(imgs) else imgs[0]
    photo = Image.open(io.BytesIO(_fetch(client, ref.url, static_base))).convert("RGB")
    return _write(out, item, role, cutout, photo)


def _manual(out: Path, specs: list[str]) -> list[dict]:
    from seam_shared.models import Item

    entries, free = [], [r for r in ROLES]
    for spec in specs:
        parts = spec.split(":")
        role = None
        if len(parts) >= 3 and parts[-1] in ROLES:
            role, parts = parts[-1], parts[:-1]
        if len(parts) != 2:
            raise SystemExit(f"--manual wants ITEM_JSON_PATH:IMAGE_PATH[:ROLE], got {spec!r}")
        item = Item.model_validate_json(Path(parts[0]).read_text())
        if item.tags is None:
            raise SystemExit(f"--manual item {item.id} has no tags")
        role = role or (free[0] if free else "extra")
        if role in free:
            free.remove(role)
        src = Image.open(parts[1])
        entries.append(_write(out, item, role, src.convert("RGBA"), src.convert("RGB")))
    if free:
        print(f"warning: no manual entry for roles {', '.join(free)}")
    return entries


def _verify(out: Path, entries: list[dict]) -> None:
    for e in entries:
        d = out / e["safe"]
        for name in ("item.json", "cutout.png", "photo.jpg"):
            f = d / name
            if not f.is_file() or f.stat().st_size == 0:
                raise SystemExit(f"verify failed: {f} missing or empty")
        with Image.open(d / "cutout.png") as im:
            if im.mode != "RGBA" or im.getextrema()[3][1] == 0:
                raise SystemExit(f"verify failed: {d / 'cutout.png'} has no visible alpha")
    missing = [r for r in ROLES if r not in {e["role"] for e in entries}]
    if missing:
        raise SystemExit(f"verify failed: roles missing from manifest: {', '.join(missing)}")


def main() -> None:
    from drape._repo import bootstrap

    bootstrap()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="runs/inputs", help="output directory (default: runs/inputs)")
    p.add_argument("--static-base", default=STATIC_BASE, help=f"base for /static/ urls (default: {STATIC_BASE})")
    p.add_argument("--manual", action="append", default=[], metavar="ITEM_JSON:IMAGE[:ROLE]",
                   help="no-DB path: validate ITEM_JSON as a seam_shared Item and use IMAGE for both cutout.png "
                        "and photo.jpg. Repeatable; roles default to sweats, hoodie, jeans, tee in order.")
    a = p.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.manual:
        entries = _manual(out, a.manual)
    else:
        from seam_shared import db

        entries, used = [], set()
        with db.pool().connection() as conn, httpx.Client(timeout=30.0) as client:
            for role, (cats, score) in _rules().items():
                pool = [it for it in _candidates(conn, cats, score) if it.id not in used]
                if not pool:
                    raise SystemExit(f"no candidate found for role {role}")
                for it in pool:
                    try:
                        entries.append(_export(out, it, role, client, a.static_base))
                    except Exception as e:
                        print(f"skip {it.id} for {role}: {e}")
                        continue
                    used.add(it.id)
                    break
                else:
                    raise SystemExit(f"every candidate failed to export for role {role}")

    manifest = {"items": [{k: v for k, v in e.items() if k != "_dims"} for e in entries]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _verify(out, entries)

    for e in entries:
        c, ph = e["_dims"]["cutout"], e["_dims"]["photo"]
        print(f"{e['id']} | {e['role']} | {e['size_normalized']} | {e['fit']} | cutout {c[0]}x{c[1]} | photo {ph[0]}x{ph[1]}")
    print(f"ok: {len(entries)} items -> {out}/ (manifest.json roles complete)")


if __name__ == "__main__":
    main()
