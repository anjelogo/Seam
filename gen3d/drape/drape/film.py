"""Shoulder-region filmstrips and frame-0 placement gaps for the tee-slide diagnosis (read-only)."""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import trimesh
import yaml
from PIL import Image, ImageDraw, ImageFont

from drape._repo import RUNS
from drape.collar import SIDES, body_shoulders, to_cm

BODIES = RUNS / "bodies"
SEG_FILE = "ggg_body_segmentation.json"
N_CAP = 6  # mannequin arm-cap rings, gen3d/app/mannequin/generator.py:9
WINDOW = (-25.0, 15.0)  # 40 cm crop around the body acromion height
PANEL = 220
SUPER = 2
BODY_RGB = (90, 110, 150)
CLOTH_RGB = (230, 120, 40)
LIGHT = np.array([0.4, 0.75, 0.5])


def arm_root_ring(verts: np.ndarray, seg: dict, side: str) -> np.ndarray:
    """The arm-cap ring where the cap meets the trunk: cap ring N_CAP-1, past the exported cap pole."""
    pts = verts[np.asarray(seg[f"{side}_arm"], int)]
    centred = pts - pts.mean(0)
    axis = np.linalg.svd(centred, full_matrices=False)[2][0]
    axis = axis if (axis[0] > 0) == (side == "left") else -axis
    proj = centred @ axis
    rings = [pts[np.abs(proj - t) < 1e-3] for t in np.unique(np.round(proj, 3))]
    rings = [r for r in rings if len(r) > 3]  # drop the single-vertex cap pole
    radii = [float(np.linalg.norm(r - r.mean(0), axis=1).mean()) for r in rings[: N_CAP + 1]]
    if radii[N_CAP - 1] < max(radii[:N_CAP]) - 1e-6:
        raise SystemExit(f"film: {side} cap ring {N_CAP - 1} is not the radius plateau: {radii}")
    return rings[N_CAP - 1]


def body_landmarks(wearer: str) -> dict:
    obj = BODIES / f"{wearer}.obj"
    mesh = trimesh.load(obj, process=False, maintain_order=True)
    verts = to_cm(np.asarray(mesh.vertices), obj.name)
    seg = json.loads((BODIES / SEG_FILE).read_text())
    out = {"verts": verts, "faces": np.asarray(mesh.faces), "acromion": body_shoulders(obj)}
    out["arm_root"] = {s: arm_root_ring(verts, seg, s) for s in SIDES}
    return out


def seam_groups(spec: dict) -> dict[str, list[int]]:
    """Shoulder seam and armhole stitch ids per side, read off the panel/edge graph in the spec."""
    stitches = spec["pattern"]["stitches"]
    out = {}
    for side in SIDES:
        sleeve, torso = f"{side}_sleeve", (f"{side}_ftorso", f"{side}_btorso")
        arm, shoulder = [], []
        for i, stitch in enumerate(stitches):
            names = [e["panel"] for e in stitch]
            if any(n.startswith(sleeve) for n in names) and any(n in torso for n in names):
                arm.append(i)
            elif sorted(names) == sorted([f"{side}_ftorso", f"{side}_btorso"]):
                shoulder.append(i)
        out[f"{side}_armhole"] = arm
        out[f"{side}_shoulder"] = shoulder
    return out


def stitch_verts(seg_lines: list[str], ids: list[int]) -> np.ndarray:
    want = {f"stitch_{i}" for i in ids}
    return np.array([i for i, line in enumerate(seg_lines) if want & set(line.split(","))], int)


def shoulder_seam_verts(seg_lines: list[str], ids: list[int], verts: np.ndarray, collar: np.ndarray) -> np.ndarray:
    """Of the two front-to-back torso seams, the shoulder one: the seam running off the collar edge."""
    best, best_d = None, None
    for i in ids:
        idx = stitch_verts(seg_lines, [i])
        if len(idx) < 3:
            continue
        d = float(np.linalg.norm(verts[idx][:, None] - verts[collar][None], axis=2).min())
        if best_d is None or d < best_d:
            best, best_d = idx, d
    if best is None:
        raise SystemExit("film: no front-to-back torso seam found")
    return best


def dumps(sim_dir: Path) -> tuple[np.ndarray, dict[int, Path]]:
    where = next((d for d in (sim_dir, sim_dir.parent) if (d / "dump_faces.npy").exists()), None)
    if where is None:
        raise SystemExit(f"film: no dump_faces.npy in {sim_dir} or its parent")
    faces_file = where / "dump_faces.npy"
    found = {}
    for path in where.glob("dump_f*.npy"):
        if path != faces_file:
            found[int(re.sub(r"\D", "", path.stem) or 0)] = path
    return np.load(faces_file), found


def shade(normals: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    lam = 0.35 + 0.65 * np.abs(normals @ (LIGHT / np.linalg.norm(LIGHT)))
    return np.clip(np.asarray(rgb) * lam[:, None], 0, 255).astype(np.uint8)


def render(tris: np.ndarray, colours: np.ndarray, view: str, box: tuple) -> Image.Image:
    """Flat-shaded orthographic painter's-algorithm fill; box is (h_lo, h_hi, v_lo, v_hi) in cm."""
    size = PANEL * SUPER
    img = Image.new("RGB", (size, size), (248, 248, 248))
    draw = ImageDraw.Draw(img)
    if view == "front":  # facing the body's front, so its own left falls on the right of frame
        horiz, vert, depth = tris[:, :, 0], tris[:, :, 1], tris[:, :, 2].mean(1)
    else:  # top-down, body front at the bottom of frame, its own left still on the right
        horiz, vert, depth = tris[:, :, 0], -tris[:, :, 2], tris[:, :, 1].mean(1)
    h_lo, h_hi, v_lo, v_hi = box
    scale = (size - 8) / max(h_hi - h_lo, v_hi - v_lo)
    px = (horiz - h_lo) * scale + 4
    py = (size - 4) - (vert - v_lo) * scale
    for i in np.argsort(depth):
        draw.polygon([(px[i, 0], py[i, 0]), (px[i, 1], py[i, 1]), (px[i, 2], py[i, 2])],
                     fill=tuple(int(c) for c in colours[i]))
    return img.resize((PANEL, PANEL), Image.LANCZOS)


def panel(body: dict, cloth: np.ndarray, faces: np.ndarray, view: str, box3: tuple) -> Image.Image:
    y_lo, y_hi, h_lo, h_hi, v_lo, v_hi = box3
    tris, cols = [], []
    for verts, face, rgb in ((body["verts"], body["faces"], BODY_RGB), (cloth, faces, CLOTH_RGB)):
        tri = verts[face]
        keep = (tri[:, :, 1].max(1) > y_lo) & (tri[:, :, 1].min(1) < y_hi)
        tri = tri[keep]
        normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        norm = np.linalg.norm(normal, axis=1, keepdims=True)
        tris.append(tri)
        cols.append(shade(normal / np.where(norm == 0, 1, norm), rgb))
    return render(np.concatenate(tris), np.concatenate(cols), view, (h_lo, h_hi, v_lo, v_hi))


def strip(panels: list[tuple[int, Image.Image]], title: str, path: Path) -> None:
    font = ImageFont.load_default()
    bar = 16
    img = Image.new("RGB", (PANEL * len(panels), PANEL + bar + 14), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((4, 3), title, fill=(0, 0, 0), font=font)
    for i, (frame, cell) in enumerate(panels):
        img.paste(cell, (i * PANEL, bar))
        draw.text((i * PANEL + 4, PANEL + bar + 1), f"f{frame}", fill=(0, 0, 0), font=font)
        draw.text((i * PANEL + 4, bar + 2), "R", fill=(0, 0, 0), font=font)
        draw.text((i * PANEL + PANEL - 10, bar + 2), "L", fill=(0, 0, 0), font=font)
        draw.line([(i * PANEL, bar), (i * PANEL, PANEL + bar)], fill=(200, 200, 200))
    for quality in (80, 70, 55, 40):
        img.save(path, "JPEG", quality=quality, optimize=True)
        if path.stat().st_size <= 400_000:
            break
    print(f"{path} {path.stat().st_size // 1024} KB  {img.size[0]}x{img.size[1]} q{quality}")


def sim_dirs(run: Path) -> list[tuple[str, Path]]:
    return [(spec.parent.parent.parent.name, spec.parent)
            for spec in sorted(run.glob("*/sim/*/*_specification.json"))]


def load_sim(sim: Path) -> dict:
    spec = json.loads((sim / f"{sim.name}_specification.json").read_text())
    seg_lines = [l.strip() for l in (sim / f"{sim.name}_sim_segmentation.txt").read_text().splitlines()]
    labels = yaml.safe_load((sim / f"{sim.name}_vertex_labels.yaml").read_text())
    faces, found = dumps(sim)
    return {"spec": spec, "seg": seg_lines, "labels": labels, "faces": faces, "dumps": found,
            "groups": seam_groups(spec)}


def cmd_strips(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    body = body_landmarks(args.wearer)
    for run in [Path(r) for r in args.runs]:
        for safe, sim in sim_dirs(run):
            faces, found = dumps(sim)
            frames = sorted({f for f in found if f % args.stride == 0} | {max(found)})
            acro = np.stack([body["acromion"][s] for s in SIDES])
            y_lo, y_hi = acro[:, 1].mean() + WINDOW[0], acro[:, 1].mean() + WINDOW[1]
            box = {"front": (y_lo, y_hi, -32.0, 32.0, y_lo, y_hi),
                   "top": (y_lo, y_hi, -32.0, 32.0, -32.0, 32.0)}
            for view in ("front", "top"):
                cells = [(f, panel(body, to_cm(np.load(found[f]), found[f].name), faces, view, box[view]))
                         for f in frames]
                name = f"{run.name}__{safe}__{view}.jpg"
                strip(cells, f"{run.name} {safe} {view} (orange=garment, blue=body)", out / name)


def gap_rows(run: Path, body: dict) -> list[dict]:
    rows = []
    for safe, sim in sim_dirs(run):
        info = load_sim(sim)
        frame0 = to_cm(np.load(info["dumps"][min(info["dumps"])]), "dump_f0")
        for side in SIDES:
            collar = np.asarray(info["labels"][f"{side}_collar"], int)
            seam = shoulder_seam_verts(info["seg"], info["groups"][f"{side}_shoulder"], frame0, collar)
            arm = stitch_verts(info["seg"], info["groups"][f"{side}_armhole"])
            label_arm = np.asarray(info["labels"][f"{side}_armhole"], int)
            acro = body["acromion"][side]
            d = np.linalg.norm(frame0[seam] - acro, axis=1)
            near = frame0[seam][d.argmin()]
            root = body["arm_root"][side].mean(0)
            rows.append({
                "run": run.name, "item": safe, "side": side,
                "seam_n": len(seam), "armhole_n": len(arm), "label_armhole_n": len(label_arm),
                "seam_acr_3d": float(d.min()), "seam_acr_dy": float(near[1] - acro[1]),
                "seam_top_dy": float(frame0[seam][:, 1].max() - acro[1]),
                "arm_ctr": frame0[arm].mean(0), "arm_root": root,
                "arm_3d": float(np.linalg.norm(frame0[arm].mean(0) - root)),
                "arm_dy": float(frame0[arm].mean(0)[1] - root[1]),
                "label_arm_3d": float(np.linalg.norm(frame0[label_arm].mean(0) - root)),
            })
    return rows


def overhead(verts: np.ndarray, faces: np.ndarray, point: np.ndarray) -> float | None:
    """Height of the lowest garment sheet lying directly over the point, or None when nothing covers it."""
    tri = verts[faces][:, :, [0, 2]]
    p, a, b, c = point[[0, 2]], tri[:, 0], tri[:, 1], tri[:, 2]
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(d) > 1e-12
    u = np.where(ok, ((b[:, 1] - c[:, 1]) * (p[0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (p[1] - c[:, 1])) / np.where(ok, d, 1), -1)
    v = np.where(ok, ((c[:, 1] - a[:, 1]) * (p[0] - c[:, 0]) + (a[:, 0] - c[:, 0]) * (p[1] - c[:, 1])) / np.where(ok, d, 1), -1)
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1)
    if not hit.any():
        return None
    ys = verts[faces][hit]
    y = u[hit] * ys[:, 0, 1] + v[hit] * ys[:, 1, 1] + (1 - u[hit] - v[hit]) * ys[:, 2, 1]
    above = y[y > point[1]]
    return float(above.min()) if len(above) else None


def cmd_slide(args) -> None:
    """Cross-check for the by-eye annotation: per frame, is there fabric over the shoulder cap, and
    has the sleeve top dropped under the arm-root ring."""
    body = body_landmarks(args.wearer)
    print("| run | item | side | first bare | bare for good | sleeve under root | f0 cap dy | last cap dy |")
    print("|" + "---|" * 8)
    for run in [Path(r) for r in args.runs]:
        for safe, sim in sim_dirs(run):
            info = load_sim(sim)
            frames = sorted(info["dumps"])
            seg = info["seg"]
            for side in SIDES:
                acro = body["acromion"][side]
                root_top = float(body["arm_root"][side][:, 1].max())
                sleeve = np.array([i for i, l in enumerate(seg)
                                   if l.split(",")[0].startswith(f"{side}_sleeve")], int)
                under, caps = None, []
                for f in frames:
                    v = to_cm(np.load(info["dumps"][f]), "d")
                    caps.append(overhead(v, info["faces"], acro))
                    if under is None and float(v[sleeve][:, 1].max()) < root_top:
                        under = f
                first = next((f for f, c in zip(frames, caps) if c is None), None)
                last_covered = max((i for i, c in enumerate(caps) if c is not None), default=None)
                settles = "covered at end" if last_covered == len(caps) - 1 else \
                    f"f{frames[last_covered + 1]}" if last_covered is not None else "f0 (never covered)"
                ends = [f"{c - acro[1]:+.2f}" if c is not None else "bare" for c in (caps[0], caps[-1])]
                print(f"| {run.name} | {safe} | {side} | {'f' + str(first) if first is not None else 'never'} |"
                      f" {settles} | {'f' + str(under) if under is not None else 'never'} |"
                      f" {ends[0]} | {ends[1]} |")


def cmd_gaps(args) -> None:
    body = body_landmarks(args.wearer)
    rows = [r for run in args.runs for r in gap_rows(Path(run), body)]
    hdr = ("| run | item | side | seam->acromion 3D | vert | seam top vs acr | armhole ctr->arm root 3D | vert |"
           " dx | dz |")
    print(hdr)
    print("|" + "---|" * 10)
    for r in rows:
        dx, dz = r["arm_ctr"][0] - r["arm_root"][0], r["arm_ctr"][2] - r["arm_root"][2]
        print(f"| {r['run']} | {r['item']} | {r['side']} | {r['seam_acr_3d']:.2f} | {r['seam_acr_dy']:+.2f} |"
              f" {r['seam_top_dy']:+.2f} | {r['arm_3d']:.2f} | {r['arm_dy']:+.2f} | {dx:+.2f} | {dz:+.2f} |")
    Path(args.json).write_text(json.dumps(
        [{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in r.items()} for r in rows], indent=1))
    print(f"\nwrote {args.json}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["strips", "gaps", "slide"])
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="film")
    ap.add_argument("--wearer", default="wearer_masc_a45")
    ap.add_argument("--stride", type=int, default=100)
    ap.add_argument("--band", type=float, default=2.0)
    ap.add_argument("--json", default="film/frame0_gaps.json")
    args = ap.parse_args()
    {"strips": cmd_strips, "gaps": cmd_gaps, "slide": cmd_slide}[args.cmd](args)


if __name__ == "__main__":
    main()
