"""Contact sheets for a drape run: every top in both poses from five fixed cameras, beside the bare-body cap-coverage heat map."""

import argparse
import json
from pathlib import Path
from typing import NoReturn

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from drape.collar import BODIES, SIDES, obj_mesh
from drape.coverage import ARM_TAG, INPUT_DIRS, body_parts, cap_metrics, item_meta, landmarks

TILE = 280
LABEL = 26
BG = (208, 208, 208)
INK = (24, 24, 24)
BODY_RGB = (198, 198, 202)
GARMENT_RGB = (0, 148, 150)
COVERED_RGB = (58, 186, 78)
BARE_RGB = (222, 48, 42)
LIGHT = np.array([-0.35, 0.50, 0.79])
AMBIENT = 0.3
FULL = {"front": (0.0, 8.0), "back": (180.0, 8.0), "side": (90.0, 8.0), "3/4": (40.0, 14.0)}
SHOULDER = (0.0, 62.0)
FULL_BOX = (np.array([0.0, 127.0, 0.0]), 58.0)  # every top is framed the same, so rows compare straight across
CAP_BOX = (np.array([0.0, 138.0, 0.0]), 33.0)
MAX_KB = 400


def die(msg: str) -> NoReturn:
    raise SystemExit(f"sheet: {msg}")


def basis(az: float, el: float) -> np.ndarray:
    a, e = np.radians(az), np.radians(el)
    fwd = np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])
    right = np.cross([0.0, 1.0, 0.0], fwd)
    right /= np.linalg.norm(right)
    return np.stack([right, np.cross(fwd, right), fwd])


def render(layers: list[tuple[np.ndarray, np.ndarray, np.ndarray]], box: tuple, az: float, el: float) -> Image.Image:
    """Painter's algorithm over both meshes at once: back faces culled, the rest drawn far to near."""
    img = Image.new("RGB", (TILE, TILE), BG)
    draw = ImageDraw.Draw(img)
    centre, half = box
    rot, scale = basis(az, el), TILE / (2 * half)
    poly, shade, depth = [], [], []
    for verts, faces, colour in layers:
        cam = (verts - centre) @ rot.T
        screen = np.stack([TILE / 2 + cam[:, 0] * scale, TILE / 2 - cam[:, 1] * scale], 1)
        tri = cam[faces]
        normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
        pix = screen[faces]
        keep = ((normal[:, 2] > 0)
                & (pix[:, :, 0].max(1) >= 0) & (pix[:, :, 0].min(1) < TILE)
                & (pix[:, :, 1].max(1) >= 0) & (pix[:, :, 1].min(1) < TILE))
        if not keep.any():
            continue
        lit = AMBIENT + (1 - AMBIENT) * np.clip(normal[keep] @ LIGHT, 0.0, 1.0)
        rgb = np.broadcast_to(np.asarray(colour, float), (len(faces), 3))[keep]
        poly.append(pix[keep])
        shade.append(np.clip(rgb * lit[:, None], 0, 255).astype(np.uint8))
        depth.append(tri[keep][:, :, 2].mean(1))
    if not poly:
        return img
    poly, shade = np.concatenate(poly), np.concatenate(shade)
    for i in np.concatenate(depth).argsort():
        draw.polygon([tuple(p) for p in poly[i]], fill=tuple(int(c) for c in shade[i]))
    return img


def body_layers(parts: dict, colour: np.ndarray | None) -> list[tuple]:
    out = []
    for mesh, idx in parts.values():
        verts, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
        face_rgb = BODY_RGB if colour is None else colour[idx][faces].mean(1)
        out.append((verts, faces, face_rgb))
    return out


def heat_colour(mark: dict, covered: dict[str, np.ndarray]) -> np.ndarray:
    colour = np.broadcast_to(np.asarray(BODY_RGB, float), (len(mark["verts"]), 3)).copy()
    for side in SIDES:
        cap = mark["sides"][side]["cap"]
        colour[cap] = np.where(covered[side][:, None], np.asarray(COVERED_RGB, float), np.asarray(BARE_RGB, float))
    return colour


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def strip(text: str, width: int) -> Image.Image:
    img = Image.new("RGB", (width, LABEL), BG)
    ImageDraw.Draw(img).text((6, 5), text, fill=INK, font=font(16))
    return img


def tag(img: Image.Image, text: str) -> Image.Image:
    ImageDraw.Draw(img).text((5, 4), text, fill=INK, font=font(14))
    return img


def row(out: Path, safe: str, inputs: Path | None, marks: dict) -> Image.Image:
    report_file = out / safe / "glb" / "bind_report.json"
    if not report_file.exists():
        die(f"{safe}: {report_file} missing")
    report = json.loads(report_file.read_text())
    sim_specs = sorted((out / safe / "sim").glob("*/*_specification.json"))
    if not sim_specs:
        die(f"{safe}: no sim spec under {out / safe / 'sim'}")
    sim_dir = sim_specs[0].parent
    tagged = ARM_TAG.search(sim_dir.name)
    deg = float(tagged.group(1)) if tagged else 0.0
    base = report.get("base") or "masc"
    poses = {"sim": (sim_dir / f"{sim_dir.name}_sim.obj",
                     BODIES / (f"wearer_{base}_a{deg:g}.obj" if deg else f"wearer_{base}.obj")),
             "web": (out / ((report.get("posed") or {}).get("obj") or ""), BODIES / f"wearer_{base}.obj")}

    meta = item_meta(safe, inputs)
    tiles, note = [], []
    for pose, (path, body) in poses.items():
        if not path.exists():
            die(f"{safe}: {pose} mesh {path} missing")
        if body.name not in marks:
            marks[body.name] = (landmarks(body), body_parts(body)[1])
        mark, parts = marks[body.name]
        mesh = obj_mesh(path)
        gverts, gfaces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
        covered, pct = {}, {}
        for side in SIDES:
            metrics = cap_metrics(mark, side, gverts, gfaces)
            covered[side] = np.asarray(metrics["covered"], bool)
            pct[side] = 100.0 * metrics["coverage"]
        dressed = body_layers(parts, None) + [(gverts, gfaces, GARMENT_RGB)]
        heat = body_layers(parts, heat_colour(mark, covered))
        line = [tag(render(dressed, FULL_BOX, *FULL[v]), f"{pose} {v}") for v in FULL]
        line.append(tag(render(dressed, CAP_BOX, *SHOULDER), f"{pose} shoulder"))
        line += [tag(render(heat, FULL_BOX, *FULL[v]), f"cap {v}") for v in ("front", "back")]
        line.append(tag(render(heat, CAP_BOX, *SHOULDER), "cap top-down"))
        tiles.append(line)
        note.append(f"{pose} L {pct['left']:.0f}% R {pct['right']:.0f}%")

    cols = max(len(t) for t in tiles)
    img = Image.new("RGB", (cols * TILE, LABEL + len(tiles) * TILE), BG)
    img.paste(strip(f"{safe}  {meta['category']} {meta['size']}   cap coverage  " + "   ".join(note),
                    cols * TILE), (0, 0))
    for r, line in enumerate(tiles):
        for c, tile in enumerate(line):
            img.paste(tile, (c * TILE, LABEL + r * TILE))
    return img


def save(img: Image.Image, path: Path) -> int:
    """Quality first, then scale, until the jpeg fits the sheet budget."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for scale in (1.0, 0.75, 0.55, 0.4, 0.3):
        shrunk = img if scale == 1.0 else img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        for quality in (88, 78, 68, 55, 42):
            shrunk.save(path, "JPEG", quality=quality, optimize=True)
            if path.stat().st_size <= MAX_KB * 1024:
                return path.stat().st_size
    kb = path.stat().st_size / 1024
    raise AssertionError(f"{path} is {kb:.0f}KB, over the {MAX_KB}KB sheet budget")


def main() -> None:
    ap = argparse.ArgumentParser(description="contact sheets for the tops in a drape run")
    ap.add_argument("--out", type=Path, required=True, help="a drape run directory, e.g. runs/out_tee_collar")
    ap.add_argument("--inputs", type=Path, default=None,
                    help=f"item.json directory (default: the first of {', '.join(d.name for d in INPUT_DIRS)} that has it)")
    ap.add_argument("--sheet-out", type=Path, default=None, help="sheet directory (default: <out>/sheets)")
    args = ap.parse_args()

    if not args.out.is_dir():
        die(f"{args.out} is not a directory")
    safes = [p.parent.name for p in sorted(args.out.glob("*/panels.json"))
             if json.loads(p.read_text()).get("garment") == "upper"]
    if not safes:
        die(f"no tops in {args.out}")

    where = args.sheet_out or args.out / "sheets"
    marks: dict[str, tuple] = {}
    rows = []
    for safe in safes:
        img = row(args.out, safe, args.inputs, marks)
        size = save(img, where / f"{safe}.jpg")
        print(f"{safe:18s} {img.width}x{img.height} -> {where / f'{safe}.jpg'} ({size / 1024:.0f}KB)")
        rows.append(img)

    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), BG)
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    size = save(sheet, where / "sheet.jpg")
    print(f"\n{len(rows)} top{'s' if len(rows) != 1 else ''} -> {where / 'sheet.jpg'} ({size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
