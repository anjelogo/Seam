"""Texture eval: orthographic front/side/back renders of legacy vs v2 drapes, a multi-pass Claude rubric with
per-criterion means, and LPIPS against the cutout kept in the CSV."""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import functools
import io
import json
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from drape._repo import DRAPE, ROOT, bootstrap

bootstrap()

MODEL = "claude-sonnet-5-5"
PRICE_IN, PRICE_OUT = 3.0 / 1e6, 15.0 / 1e6
VIEWS = {"front": 0, "side": 90, "back": 180}
TEXTURES = ("legacy", "v2")
SHOT = (600, 800)
GREY = (128, 128, 128)
LPIPS_SIZE = 256
CRITERIA = {
    "stripes_present": "every stripe, pinstripe, side stripe or plaid line visible in the listing photos is on the 3D garment",
    "parallel_to_grain": "lines follow the cloth: pinstripes stay parallel to the leg/body length, horizontal stripes stay level, on tapered or flared parts too",
    "continuous_across_seams": "lines and bands meet where panels are sewn together instead of breaking or jumping at side seams, outseams, the centre front",
    "count_spacing": "number, width and spacing of stripes and bands match the photos",
    "side_stripe_side_back": "a side stripe on the outseam is visible from the side and continues correctly toward the back view",
    "print_not_mirrored": "graphics and text are readable, on the correct side, and not mirrored or smeared onto the back",
    "wrinkles_not_doubled": "the texture does not carry photographed wrinkles/shadows on top of the 3D folds",
}
SIDE_CRITERION = "matches_side_photo"
SIDE_DESC = ("the last image is the listing's own {view} photo of this garment: the {view} render shows the same "
             "pattern there - same lines, same bands, in the same places")


def _serve(root: Path) -> tuple[ThreadingHTTPServer, int]:
    handler = functools.partial(type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


async def _shoot(port: int, out_rel: str, jobs: list[tuple], dest: Path) -> list[dict]:
    from playwright.async_api import async_playwright

    done = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, args=["--ignore-gpu-blocklist"])
        page = await browser.new_page(viewport={"width": SHOT[0], "height": SHOT[1]})
        await page.goto(f"http://127.0.0.1:{port}/gen3d/drape/viewer/index.html?eval=1&out={out_rel}", wait_until="networkidle")
        await page.wait_for_function("window.__poc && window.__poc.ready", timeout=60000)
        for safe, tex, view, avatar in jobs:
            res = await page.evaluate("([i, t, a, b]) => window.__poc.shot(i, t, a, b)", [safe, tex, VIEWS[view], avatar])
            path = dest / safe / "eval" / f"{tex}_{view}{'_avatar' if avatar else ''}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            if res.get("ok"):
                await page.screenshot(path=str(path), omit_background=True)
            done.append({"safe": safe, "tex": tex, "view": view, "avatar": avatar, "ok": bool(res.get("ok")), "path": str(path)})
        await browser.close()
    return done


def _crop(rgba: Image.Image) -> Image.Image:
    box = rgba.getchannel("A").point(lambda a: 255 if a > 127 else 0).getbbox()
    return rgba.crop(box) if box else rgba


def _flat(rgba: Image.Image, size: int | None = None) -> Image.Image:
    rgba = _crop(rgba.convert("RGBA"))
    if size:
        rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), GREY + (255,))
        canvas.alpha_composite(rgba, ((size - rgba.width) // 2, (size - rgba.height) // 2))
        return canvas.convert("RGB")
    bg = Image.new("RGBA", rgba.size, GREY + (255,))
    bg.alpha_composite(rgba)
    return bg.convert("RGB")


@functools.cache
def _lpips_net():
    import lpips

    return lpips.LPIPS(net="alex", verbose=False)


def lpips_distance(a: Image.Image, b: Image.Image) -> float:
    import torch

    def tensor(im: Image.Image):
        x = np.asarray(_flat(im, LPIPS_SIZE), np.float32) / 127.5 - 1.0
        return torch.from_numpy(x).permute(2, 0, 1)[None]

    with torch.no_grad():
        return float(_lpips_net()(tensor(a), tensor(b)).item())


def _jpeg(im: Image.Image, side: int = 768) -> dict:
    im = im.copy()
    im.thumbnail((side, side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


def _rubric_schema(keys: list[str]) -> dict:
    score = {"type": ["integer", "null"], "enum": [0, 1, 2, None]}
    props = {k: score for k in keys} | {"notes": {"type": "string"}}
    return {"type": "object", "properties": props, "required": [*keys, "notes"]}


def side_photo(item: dict, meta: dict, item_dir: Path) -> dict | None:
    """The listing's own side or back photo, and which render viewpoint answers it."""
    photos = (meta or {}).get("photos") or []
    for i, im in enumerate(item.get("listing", {}).get("images", [])):
        view = (im.get("view") or "").lower()
        hit = next((v for v in VIEWS if v != "front" and v in view), None)
        if hit and i < len(photos) and (item_dir / "photos" / photos[i]).exists():
            return {"view": hit, "photo": photos[i], "path": item_dir / "photos" / photos[i]}
    return None


def rubric(item: dict, cutout: Image.Image, photo: Image.Image, renders: dict[str, Image.Image],
           side: dict | None = None) -> dict:
    import anthropic

    keys = [*CRITERIA] + ([SIDE_CRITERION] if side else [])
    lines = [f"- {k}: {v}" for k, v in CRITERIA.items()]
    if side:
        lines.append(f"- {SIDE_CRITERION}: " + SIDE_DESC.format(view=side["view"].upper()))
    text = (
        f"Listing: {item['listing']['title']}\n"
        "Images: 1 = background-removed listing photo, 2 = original listing photo, then the 3D garment rendered "
        "orthographically from the FRONT, the wearer's LEFT SIDE and the BACK.\n"
        + (f"The last image is the listing's own {side['view'].upper()} photo of this garment.\n" if side else "")
        + "Score how faithfully the 3D garment's fabric pattern reproduces the real garment, 0 (wrong or missing), "
        "1 (partly right), 2 (right). Use null when a criterion cannot apply (e.g. stripe criteria on a solid garment, "
        "print criteria when there is no print). Judge the texture, not the 3D shape.\n" + "\n".join(lines)
    )
    content = [_jpeg(_flat(cutout)), _jpeg(photo.convert("RGB"))] + [_jpeg(_flat(renders[v])) for v in VIEWS] \
        + ([_jpeg(Image.open(side["path"]).convert("RGB"))] if side else []) + [{"type": "text", "text": text}]
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    msg = client.messages.create(
        model=MODEL, max_tokens=1024, messages=[{"role": "user", "content": content}],
        tools=[{"name": "score_texture", "description": "Record the rubric scores.",
                "input_schema": _rubric_schema(keys)}],
        tool_choice={"type": "tool", "name": "score_texture"},
    )
    block = next(b for b in msg.content if b.type == "tool_use")
    u = msg.usage
    tokens_in = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
    scores = {k: (block.input.get(k) if block.input.get(k) in (0, 1, 2) else None) for k in keys}
    return {"scores": scores, "notes": str(block.input.get("notes", ""))[:400], "seconds": round(time.perf_counter() - t0, 1),
            "cost": tokens_in * PRICE_IN + u.output_tokens * PRICE_OUT}


def mean_score(scores: dict) -> float | None:
    vals = [v for v in scores.values() if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def mean_n(vals: list) -> dict:
    """A criterion's mean over the judge passes that scored it, with the count that mean rests on."""
    kept = [v for v in vals if v is not None]
    return {"mean": round(sum(kept) / len(kept), 2) if kept else None, "n": len(kept)}


def pass_spread(runs: list[dict], keys: list[str]) -> float | None:
    """How far the judge moved between passes: max minus min of the per-pass item mean."""
    means = [m for m in (mean_score({k: r["scores"].get(k) for k in keys}) for r in runs) if m is not None]
    return round(max(means) - min(means), 2) if means else None


def sheet(safe: str, out: Path, dest: Path) -> Path:
    rows = []
    for tex in TEXTURES:
        tiles = [_flat(Image.open(out / safe / "eval" / f"{tex}_{v}_avatar.png")) for v in VIEWS]
        h = 520
        tiles = [t.resize((round(t.width * h / t.height), h), Image.Resampling.LANCZOS) for t in tiles]
        row = Image.new("RGB", (sum(t.width for t in tiles), h), GREY)
        x = 0
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width
        rows.append(row)
    img = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), GREY)
    y = 0
    for r in rows:
        img.paste(r, (0, y))
        y += r.height
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{safe}_texture.jpg"
    img.save(path, quality=85)
    return path


def criterion_means(results: list[dict], names: dict[str, str]) -> dict:
    """Per criterion, per texture: the mean over the items that scored it and how many did."""
    out: dict = {}
    for key in [*CRITERIA, SIDE_CRITERION]:
        row = {}
        for name in names.values():
            vals = [r[name]["scores"][key]["mean"] for r in results
                    if name in r and key in r[name].get("scores", {})]
            row[name] = mean_n(vals)
        if any(v["n"] for v in row.values()):
            out[key] = row
    return out


def write_csv(path: Path, results: list[dict], names: dict[str, str]) -> None:
    keys = [*CRITERIA, SIDE_CRITERION]
    head = ["safe", "role", "texture", "lpips_front", "mean", "spread", "side_view", "side_photo"]
    head += [f"{k}" for k in keys] + [f"{k}_n" for k in keys]
    rows = []
    for r in results:
        side = r["side_check"]
        for name in names.values():
            t = r.get(name)
            if t is None:
                continue
            sc = t.get("scores", {})
            rows.append([r["safe"], r.get("role") or "", name, t.get("lpips_front"), t.get("mean"), t.get("spread"),
                         "" if side == "n/a" else side["view"], "" if side == "n/a" else side["photo"]]
                        + [sc.get(k, {}).get("mean", "") for k in keys]
                        + [sc.get(k, {}).get("n", "") for k in keys])
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        w.writerows(rows)


def headline(means: dict, names: dict[str, str]) -> None:
    cols = list(names.values())
    print("\nmean over items that scored each criterion (n = those items; each item's own score is the "
          "mean of its judge passes)")
    print(f"{'criterion':<26}" + "".join(f"{c:>18}" for c in cols))
    for key, row in means.items():
        cells = "".join(f"{str(row[c]['mean']) + ' (n=' + str(row[c]['n']) + ')':>18}" for c in cols)
        print(f"{key:<26}{cells}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs_texture")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out_texture")
    ap.add_argument("--only")
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--shots", type=Path, default=DRAPE / "runs/out/shots/texture", help="where the legacy|v2 sheets go")
    ap.add_argument("--passes", type=int, default=3, help="judge runs per variant, averaged per criterion")
    ap.add_argument("--label", default="v2", help="what to call the non-legacy texture in the report; "
                                                  "the shot files and GLB paths keep their own names")
    a = ap.parse_args()
    names = {"legacy": "legacy", "v2": a.label}

    out = a.out.resolve()
    subprocess.run([sys.executable, str(DRAPE / "viewer/build_manifest.py"), "--inputs", str(a.inputs), "--out", str(out)],
                   check=True, capture_output=True)
    manifest = json.loads((out / "viewer_manifest.json").read_text())["items"]
    entries = [e for e in manifest if (not a.only or e["safe"] == a.only) and e.get("draped") and e.get("draped_legacy")]
    if not entries:
        raise SystemExit(f"no item under {out} has both a legacy and a v2 draped GLB - run drape.texture + drape.export")
    jobs = [(e["safe"], t, v, av) for e in entries for t in TEXTURES for v in VIEWS for av in (False, True)]
    server, port = _serve(ROOT)
    try:
        shots = asyncio.run(_shoot(port, str(out.relative_to(DRAPE)), jobs, out))
    finally:
        server.shutdown()
    failed = [s for s in shots if not s["ok"]]
    if failed:
        raise SystemExit(f"{len(failed)} renders failed, e.g. {failed[0]}")

    results, cost = [], 0.0
    for e in entries:
        safe = e["safe"]
        item_dir = a.inputs / safe
        item = json.loads((item_dir / "item.json").read_text())
        meta_path = item_dir / "spec_meta.json"
        side = side_photo(item, json.loads(meta_path.read_text()) if meta_path.exists() else {}, item_dir)
        cutout = Image.open(item_dir / "cutout.png")
        photo = Image.open(item_dir / "photo.jpg")
        row = {"safe": safe, "role": e.get("role"), "title": e.get("title"),
               "side_check": {"view": side["view"], "photo": side["photo"]} if side else "n/a"}
        keys = [*CRITERIA] + ([SIDE_CRITERION] if side else [])
        for tex in TEXTURES:
            renders = {v: Image.open(out / safe / "eval" / f"{tex}_{v}.png") for v in VIEWS}
            name = names[tex]
            row[name] = {"lpips_front": round(lpips_distance(renders["front"], cutout), 4)}
            if not a.no_claude:
                runs = [rubric(item, cutout, photo, renders, side) for _ in range(a.passes)]
                cost += sum(r.pop("cost") for r in runs)
                scores = {k: mean_n([r["scores"].get(k) for r in runs]) for k in keys}
                row[name] |= {"scores": scores, "passes": [r["scores"] for r in runs], "notes": runs[0]["notes"],
                              "seconds": round(sum(r["seconds"] for r in runs), 1),
                              "mean": mean_score({k: v["mean"] for k, v in scores.items()}),
                              "spread": pass_spread(runs, keys)}
                if side:
                    row["side_check"] |= {name: scores[SIDE_CRITERION]}
        row["sheet"] = str(sheet(safe, out, a.shots).relative_to(DRAPE))
        results.append(row)
        sc = row["side_check"]
        print(f"{safe} | {row['role']} | rubric " + " ".join(
            f"{names[t]} {row[names[t]].get('mean')} (spread {row[names[t]].get('spread')})" for t in TEXTURES)
            + f" | side {sc if sc == 'n/a' else sc['view'] + ' ' + sc['photo']}")

    report = {"model": MODEL, "label": a.label, "passes": a.passes, "criteria": CRITERIA,
              "side_criterion": {SIDE_CRITERION: SIDE_DESC}, "items": results,
              "criterion_means": criterion_means(results, names), "cost_usd": round(cost, 4)}
    (out / "eval.json").write_text(json.dumps(report, indent=2, default=str))
    write_csv(out / "eval.csv", results, names)
    headline(report["criterion_means"], names)
    print(f"ok: {len(results)} items -> {out / 'eval.json'}, {out / 'eval.csv'} | ${cost:.3f}")


if __name__ == "__main__":
    main()
