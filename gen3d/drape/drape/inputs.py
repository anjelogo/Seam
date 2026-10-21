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
MAX_PHOTOS = 8
BOTTOMS = ("pants", "cargo", "jeans")
TEXTURE_ROLES = {
    "track": 2, "pinstripe": 1, "legging": 1, "widejeans": 1, "stripetee": 2, "plaid": 1,
    "graphictee": 1, "camo": 1, "hoodie": 1, "tee": 1,
}
SETS = {"poc": "runs/inputs", "texture": "runs/inputs_texture"}


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


def _text(it: "Item") -> str:
    t = it.tags
    return " ".join([it.listing.title or "", it.listing.description or "", *t.style_tags, t.pattern or ""])


def _hit(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _texture_rules() -> dict[str, tuple[tuple[str, ...], Callable[["Item"], int | None]]]:
    """Eval-set roles for texture v2: each stresses one way front projection breaks."""

    def flat(it: "Item") -> int:
        imgs, i = it.listing.images, it.tags.best_view_index
        view = imgs[i].view.value if 0 <= i < len(imgs) else "unknown"
        return {"flat_lay": 2, "hanger": 1}.get(view, 0)

    def pattern_is(it: "Item", *names: str) -> bool:
        return (it.tags.pattern or "").lower().replace(" ", "_") in names

    def track(it: "Item") -> int | None:
        text = _text(it)
        if not _hit(r"track|stripe", text) or _hit(r"pin.?stripe|camo", text):
            return None
        return (5 * _hit(r"stripe", text) + 3 * pattern_is(it, "striped", "stripes") + 2 * _hit(r"track", it.listing.title)
                + flat(it))

    def pinstripe(it: "Item") -> int | None:
        if not _hit(r"pin.?stripe", _text(it)):
            return None
        return (3 * pattern_is(it, "pinstripe", "pinstripes") + 2 * (it.tags.category.value == "pants") + flat(it)
                - 3 * _hit(r"capri|crop|short", it.listing.title))

    def legging(it: "Item") -> int | None:
        text = _text(it)
        if not _hit(r"legging|jogger|tapered|skinny", text) or _hit(r"baggy|wide|flare|open.?leg", it.listing.title):
            return None
        return (3 * _hit(r"legging|tapered|skinny", it.listing.title) + {"slim": 2, "regular": 1}.get(it.tags.fit.value, 0)
                + flat(it))

    def widejeans(it: "Item") -> int | None:
        if not _hit(r"wide|baggy|flare", it.listing.title):
            return None
        return 3 * _hit(r"wide", it.listing.title) + 2 * _hit(r"baggy", it.listing.title) + flat(it)

    def stripetee(it: "Item") -> int | None:
        text = _text(it)
        if not _hit(r"stripe", text) or _hit(r"crop|off.the.shoulder|pin.?stripe", text):
            return None
        return (3 * _hit(r"horizontal", text) + 2 * pattern_is(it, "striped", "stripes") + flat(it)
                + (it.tags.category.value == "tee"))

    def plaid(it: "Item") -> int | None:
        text = _text(it)
        if not (_hit(r"plaid|flannel|tartan", text) and pattern_is(it, "plaid", "checkered")):
            return None
        return 3 * (it.tags.category.value in ("button_up", "longsleeve")) + 2 * _hit(r"flannel", text) + flat(it)

    def graphictee(it: "Item") -> int | None:
        if not (pattern_is(it, "graphic", "graphic_print") and _hit(r"graphic", _text(it))):
            return None
        return 2 * (it.tags.fit.value in ("regular", "oversized")) - 3 * _hit(r"crop", _text(it)) + flat(it)

    def camo(it: "Item") -> int | None:
        if not (_hit(r"camo", _text(it)) or pattern_is(it, "camo", "camouflage")):
            return None
        return 3 * (it.tags.category.value == "cargo") + flat(it) - 2 * _hit(r"stripe", _text(it))

    def solid(it: "Item") -> int | None:
        text = _text(it)
        if not pattern_is(it, "solid", "plain") or _hit(r"camo|print|logo|graphic|zip|crop|design", text):
            return None
        return 2 * _hit(r"blank|plain|solid|basic|minimal", text) + flat(it)

    return {
        "track": (BOTTOMS, track),
        "pinstripe": (BOTTOMS, pinstripe),
        "legging": (BOTTOMS, legging),
        "widejeans": (("jeans",), widejeans),
        "stripetee": (("tee", "longsleeve"), stripetee),
        "plaid": (("button_up", "longsleeve"), plaid),
        "graphictee": (("tee",), graphictee),
        "camo": (("cargo", "pants"), camo),
        "hoodie": (("hoodie",), solid),
        "tee": (("tee",), solid),
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


def _write(out: Path, item: "Item", role: str, cutout: Image.Image, photo: Image.Image,
           photos: list[tuple[int, Image.Image]] | None = None) -> dict:
    safe = item.id.replace(":", "_")
    d = out / safe
    d.mkdir(parents=True, exist_ok=True)
    (d / "item.json").write_text(item.model_dump_json(indent=2))
    cutout.save(d / "cutout.png")
    photo.save(d / "photo.jpg", quality=92)
    if photos:
        (d / "photos").mkdir(exist_ok=True)
        for i, im in photos:
            im.save(d / "photos" / f"{i:02d}.jpg", quality=92)
    t = item.tags
    return {
        "id": item.id, "safe": safe, "role": role, "category": t.category.value, "fit": t.fit.value,
        "material": t.material, "size_normalized": t.size_normalized, "title": item.listing.title,
        "_dims": {"cutout": list(cutout.size), "photo": list(photo.size), "photos": len(photos or [])},
    }


def _export(out: Path, item: "Item", role: str, client: httpx.Client, static_base: str) -> dict:
    cutout = Image.open(io.BytesIO(_fetch(client, item.tags.clean_image.url, static_base))).convert("RGBA")
    if cutout.getextrema()[3][1] == 0:
        raise RuntimeError("cutout is fully transparent")
    imgs = item.listing.images
    if not imgs:
        raise RuntimeError("listing has no images")
    best = item.tags.best_view_index if 0 <= item.tags.best_view_index < len(imgs) else 0
    photos = []
    for i, ref in enumerate(imgs[:MAX_PHOTOS]):
        try:
            photos.append((i, Image.open(io.BytesIO(_fetch(client, ref.url, static_base))).convert("RGB")))
        except Exception as e:
            if i == best:
                raise
            print(f"  {item.id}: photo {i} skipped ({e})")
    photo = dict(photos).get(best) or Image.open(io.BytesIO(_fetch(client, imgs[best].url, static_base))).convert("RGB")
    return _write(out, item, role, cutout, photo, photos)


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


def _verify(out: Path, entries: list[dict], roles: tuple[str, ...]) -> None:
    for e in entries:
        d = out / e["safe"]
        for name in ("item.json", "cutout.png", "photo.jpg"):
            f = d / name
            if not f.is_file() or f.stat().st_size == 0:
                raise SystemExit(f"verify failed: {f} missing or empty")
        with Image.open(d / "cutout.png") as im:
            if im.mode != "RGBA" or im.getextrema()[3][1] == 0:
                raise SystemExit(f"verify failed: {d / 'cutout.png'} has no visible alpha")
    missing = [r for r in roles if r not in {e["role"] for e in entries}]
    if missing:
        raise SystemExit(f"verify failed: roles missing from manifest: {', '.join(missing)}")


def main() -> None:
    from drape._repo import bootstrap

    bootstrap()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--set", default="poc", choices=tuple(SETS),
                   help="poc: the 4 drape PoC roles; texture: the ~12-item texture v2 eval set")
    p.add_argument("--out", default=None, help="output directory (default: runs/inputs, runs/inputs_texture for --set texture)")
    p.add_argument("--static-base", default=STATIC_BASE, help=f"base for /static/ urls (default: {STATIC_BASE})")
    p.add_argument("--manual", action="append", default=[], metavar="ITEM_JSON:IMAGE[:ROLE]",
                   help="no-DB path: validate ITEM_JSON as a seam_shared Item and use IMAGE for both cutout.png "
                        "and photo.jpg. Repeatable; roles default to sweats, hoodie, jeans, tee in order.")
    a = p.parse_args()

    out = Path(a.out or SETS[a.set])
    out.mkdir(parents=True, exist_ok=True)
    rules = _texture_rules() if a.set == "texture" else _rules()
    counts = TEXTURE_ROLES if a.set == "texture" else dict.fromkeys(ROLES, 1)

    if a.manual:
        entries = _manual(out, a.manual)
    else:
        from seam_shared import db

        entries, used = [], set()
        with db.pool().connection() as conn, httpx.Client(timeout=30.0) as client:
            for role, (cats, score) in rules.items():
                pool = [it for it in _candidates(conn, cats, score) if it.id not in used]
                if not pool:
                    raise SystemExit(f"no candidate found for role {role}")
                taken = 0
                for it in pool:
                    try:
                        entries.append(_export(out, it, role, client, a.static_base))
                    except Exception as e:
                        print(f"skip {it.id} for {role}: {e}")
                        continue
                    used.add(it.id)
                    taken += 1
                    if taken == counts[role]:
                        break
                if not taken:
                    raise SystemExit(f"every candidate failed to export for role {role}")

    manifest = {"items": [{k: v for k, v in e.items() if k != "_dims"} for e in entries]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _verify(out, entries, tuple(counts) if not a.manual else ROLES)

    for e in entries:
        c, ph = e["_dims"]["cutout"], e["_dims"]["photo"]
        print(f"{e['id']} | {e['role']} | {e['size_normalized']} | {e['fit']} | cutout {c[0]}x{c[1]} | photo {ph[0]}x{ph[1]}"
              f" | {e['_dims'].get('photos', 0)} photos | {e['title'][:60]}")
    print(f"ok: {len(entries)} items -> {out}/ (manifest.json roles complete)")


if __name__ == "__main__":
    main()
