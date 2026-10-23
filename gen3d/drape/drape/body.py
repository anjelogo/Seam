"""Export the procedural mannequin as a GarmentCode body: collision obj + measurement yaml + segmentation."""

from drape._repo import bootstrap

bootstrap()

import argparse
import json
from contextlib import contextmanager

import numpy as np
import trimesh
import yaml
from app.mannequin import generator
from app.mannequin.generator import (
    ARM, LAYOUT, N_TRUNK, TRUNK, body_mesh, leg_ring_at, split, trunk_section,
)
from app.mannequin.params import SLIDERS, STATIONS, body_params

from drape._repo import RUNS

BODIES = RUNS / "bodies"
SEG_FILE = "ggg_body_segmentation.json"
M = 100.0
A_POSE_DEG = 45.0  # arms from vertical, GarmentCode's A-pose; the web pose is params.ARM_ANGLE (20)

# body faces +z and the generator's unmirrored side is +x, which is the body's own left
SEG_PARTS = {
    "body": ("trunk",),
    "left_arm": ("arm_l",),
    "right_arm": ("arm_r",),
    "left_leg": ("leg_l", "foot_l"),
    "right_leg": ("leg_r", "foot_r"),
    "face_internal": (),
}
KEYS = (
    "arm_length", "arm_pose_angle", "armscye_depth", "back_width", "bum_points", "bust",
    "bust_line", "bust_points", "crotch_hip_diff", "head_l", "height", "hip_back_width",
    "hip_inclination", "hips", "hips_line", "leg_circ", "neck_w", "shoulder_incl", "shoulder_w",
    "underbust", "vert_bust_line", "waist", "waist_back_width", "waist_line",
    "waist_over_bust_line", "wrist",
)


def ranges() -> dict[str, tuple[int, int]]:
    out, i = {}, 0
    for name, rings, n in LAYOUT:
        out[name] = (i, i + rings * n + 2)
        i = out[name][1]
    return out


def _length(poly: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(poly, axis=0), axis=1).sum())


def _loop(poly: np.ndarray) -> np.ndarray:
    return poly[:-1] if np.allclose(poly[0], poly[-1]) else poly


def _girth(poly: np.ndarray) -> float:
    p = _loop(poly)
    return _length(np.vstack([p, p[:1]]))


def _outline(mesh: trimesh.Trimesh, y: float) -> np.ndarray:
    sec = mesh.section(plane_origin=(0.0, y, 0.0), plane_normal=(0.0, 1.0, 0.0))
    if sec is None:
        raise ValueError(f"no cross-section at y={y:.4f}")
    return _loop(max(sec.discrete, key=lambda q: np.hypot(q[:, 0], q[:, 2]).max()))


def _back_arc(poly: np.ndarray) -> float:
    n, a, b = len(poly), int(poly[:, 0].argmax()), int(poly[:, 0].argmin())
    cw = poly[[(a + t) % n for t in range((b - a) % n + 1)]]
    ccw = poly[[(a - t) % n for t in range((a - b) % n + 1)]]
    return _length(cw if cw[:, 2].mean() < ccw[:, 2].mean() else ccw)


def _rear_span(poly: np.ndarray, frac: float = 0.9) -> float:
    """Span between the two rearmost prominences of a cross-section."""
    z_side = poly[[int(poly[:, 0].argmax()), int(poly[:, 0].argmin())], 2].mean()
    ring = np.vstack([poly, poly[:1]])
    depth = z_side - ring[:, 2]
    level = frac * depth.max()
    spans = [abs(float(x)) for x in ring[depth >= level, 0]]
    for i in range(len(ring) - 1):
        if (depth[i] - level) * (depth[i + 1] - level) < 0:
            t = (level - depth[i]) / (depth[i + 1] - depth[i])
            spans.append(abs(float(ring[i, 0] + t * (ring[i + 1, 0] - ring[i, 0]))))
    return 2 * max(spans)


def _arc_down(col: np.ndarray, i_bottom: int, y_top: float) -> float:
    """Surface length along a vertex column, from ring i_bottom up to height y_top."""
    i = int(np.clip(np.searchsorted(col[:, 1], y_top) - 1, i_bottom, len(col) - 2))
    t = (y_top - col[i, 1]) / (col[i + 1, 1] - col[i, 1])
    return _length(np.vstack([col[i_bottom : i + 1], col[i] + t * (col[i + 1] - col[i])]))


def _pit_y(p: dict, arm: np.ndarray, sc: np.ndarray) -> float:
    """Bottom of the underarm pit: the lowest arm vertex still inside the trunk surface."""
    v = arm.reshape(-1, 3) / sc
    v = v[v[:, 1] > p["torso"][3, 0]]
    ys = []
    for x, y, z in v:
        a, bf, bb, zc, ex = trunk_section(p, y)
        if abs(x / a) ** ex + abs((z - zc) / (bf if z >= zc else bb)) ** ex < 1.0:
            ys.append(y)
    return min(ys) * sc[1]


def measure(base: str, sliders: dict | None = None) -> dict[str, float]:
    verts, faces = body_mesh(base, sliders)
    p = body_params(base, sliders)
    sc, parts, rng = p["scale"], split(verts), ranges()
    trunk, arm = parts["trunk"][0], parts["arm_l"][0]
    lo, hi = rng["trunk"]
    keep = (faces >= lo).all(1) & (faces < hi).all(1)
    torso = trimesh.Trimesh(verts[lo:hi], faces[keep] - lo, process=False)

    height = float(verts[:, 1].max() - verts[:, 1].min())
    ys = trunk[:, 0, 1]
    at = {n: float(p["torso"][i, 0] * sc[1]) for i, n in enumerate(STATIONS)}
    i_bust = int(np.abs(ys - p["lobe"][1] * sc[1]).argmin())
    y_bust = float(ys[i_bust])

    # GarmentCode measures off the acromion and the nape; the arm cap's apex moves with the pose
    ring_sh = trunk[TRUNK["shoulder"]]
    sh_x, sh_y = float(ring_sh[:, 0].max()), float(ring_sh[0, 1])
    neck = trunk[TRUNK["neckbase"]]
    neck_pt = neck[int(neck[:, 0].argmax())]
    nape_y = float(neck[0, 1])
    pit_y = _pit_y(p, arm, sc)

    cut = {n: _outline(torso, at[n]) for n in ("hip", "waist", "underbust")}
    cut["bust"] = _outline(torso, y_bust)
    n_ring = trunk.shape[1]
    # bust landmarks ride the lobe apex, which sits between two ring vertices
    frac, k = np.modf(p["lobe"][4] / (2 * np.pi) * n_ring)
    k = int(k) % n_ring
    apex = trunk[:, k] + frac * (trunk[:, (k + 1) % n_ring] - trunk[:, k])
    wrist = arm[ARM["wrist"]]
    reach = wrist.mean(0) - p["shoulder_joint"] * sc

    m = {
        "arm_length": float(np.linalg.norm(reach)) * M,
        "arm_pose_angle": float(np.degrees(np.arctan2(abs(reach[1]), abs(reach[0])))),
        "armscye_depth": (sh_y - pit_y) * M,
        "back_width": _back_arc(cut["bust"]) * M,
        "bum_points": _rear_span(cut["hip"]) * M,
        "bust": _girth(cut["bust"]) * M,
        "bust_line": _arc_down(apex, i_bust, sh_y) * M,
        "bust_points": 2 * abs(float(apex[i_bust, 0])) * M,
        "crotch_hip_diff": (at["hip"] - float(p["crotch"] * sc[1])) * M,
        "head_l": (height - nape_y) * M,
        "height": height * M,
        "hip_back_width": _back_arc(cut["hip"]) * M,
        "hip_inclination": float(np.degrees(np.arctan2(
            cut["hip"][:, 0].max() - cut["waist"][:, 0].max(), at["waist"] - at["hip"]))),
        "hips": _girth(cut["hip"]) * M,
        "hips_line": (at["waist"] - at["hip"]) * M,
        "leg_circ": _girth(leg_ring_at(p, p["crotch"]) * sc) * M,
        "neck_w": 2 * float(neck[:, 0].max()) * M,
        "shoulder_incl": float(np.degrees(np.arctan2(neck_pt[1] - sh_y, sh_x - neck_pt[0]))),
        "shoulder_w": 2 * sh_x * M,
        "underbust": _girth(cut["underbust"]) * M,
        "vert_bust_line": (nape_y - y_bust) * M,
        "waist": _girth(cut["waist"]) * M,
        "waist_back_width": _back_arc(cut["waist"]) * M,
        "waist_line": _arc_down(trunk[:, N_TRUNK // 2], TRUNK["waist"], nape_y) * M,
        # a vertical tape from the nape, so it leaves the surface above the shoulder
        "waist_over_bust_line": (_arc_down(apex, TRUNK["waist"], sh_y) + nape_y - sh_y) * M,
        "wrist": _girth(wrist) * M,
    }
    return {k: round(float(m[k]), 4) for k in KEYS}


def segmentation() -> dict[str, list[int]]:
    rng = ranges()
    return {k: [i for part in ps for i in range(*rng[part])] for k, ps in SEG_PARTS.items()}


def export(base: str, sliders: dict | None, name: str) -> dict[str, float]:
    verts, faces = body_mesh(base, sliders)
    BODIES.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(verts, faces, process=False).export(BODIES / f"{name}.obj")
    body = measure(base, sliders)
    (BODIES / f"{name}.yaml").write_text(yaml.safe_dump({"body": body}, sort_keys=True))
    (BODIES / SEG_FILE).write_text(json.dumps(segmentation()))
    return body


@contextmanager
def arm_pose(deg: float):
    """Re-pose the arms: generator.arm_dir reads ARM_ANGLE at call time."""
    old = generator.ARM_ANGLE
    generator.ARM_ANGLE = np.radians(deg)
    try:
        yield
    finally:
        generator.ARM_ANGLE = old


def export_pose(base: str, sliders: dict | None, wearer: str, deg: float, name: str) -> dict:
    """The wearer in a different arm pose: posed mesh, its own measurements bar the arm angle."""
    with arm_pose(deg):
        verts, faces = body_mesh(base, sliders)
    BODIES.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(verts, faces, process=False).export(BODIES / f"{name}.obj")
    body = yaml.safe_load((BODIES / f"{wearer}.yaml").read_text())["body"]
    height = float(verts[:, 1].max() - verts[:, 1].min()) * M
    if abs(height - body["height"]) > 0.5:
        print(f"WARNING: {name} mesh is {height:.1f} cm but {wearer}.yaml says {body['height']:.1f} cm "
              f"(pass the wearer's --base/--sliders)")
    body["arm_pose_angle"] = round(90.0 - deg, 4)
    (BODIES / f"{name}.yaml").write_text(yaml.safe_dump({"body": body}, sort_keys=True))
    (BODIES / SEG_FILE).write_text(json.dumps(segmentation()))
    return body


def parse_sliders(arg: str | None) -> dict[str, float]:
    out = {k: 0.5 for k in SLIDERS}
    for item in (arg or "").split(","):
        if not item.strip():
            continue
        key, _, val = item.partition("=")
        if (key := key.strip()) not in SLIDERS:
            raise SystemExit(f"unknown slider {key!r}; expected one of {', '.join(SLIDERS)}")
        out[key] = float(val)
    return out


def solve_height(base: str, sliders: dict, target_cm: float) -> float:
    verts = body_mesh(base, dict(sliders, height=0.5))[0]
    mid_cm = float(verts[:, 1].max() - verts[:, 1].min()) * M
    want = 0.5 + (target_cm / mid_cm - 1.0) / 0.18
    if not 0.0 <= want <= 1.0:
        print(f"height slider {want:.3f} outside [0, 1], clamping")
    return float(np.clip(want, 0.0, 1.0))


def main() -> None:
    ap = argparse.ArgumentParser(description="export a mannequin as a GarmentCode body")
    ap.add_argument("--base", default="masc", choices=("masc", "fem"))
    ap.add_argument("--name", default=None)
    ap.add_argument("--sliders", default=None, help="key=val,... (defaults 0.5)")
    ap.add_argument("--target-height-cm", type=float, default=None)
    ap.add_argument("--pose", type=float, default=None, help="arm degrees from vertical; measurements come from the unposed wearer")
    args = ap.parse_args()

    sliders = parse_sliders(args.sliders)
    if args.target_height_cm:
        sliders["height"] = solve_height(args.base, sliders, args.target_height_cm)
        print(f"height slider -> {sliders['height']:.4f}")
    wearer = f"wearer_{args.base}"
    if args.pose is None:
        name = args.name or wearer
        body = export(args.base, sliders, name)
    else:
        name = args.name or f"{wearer}_a{round(args.pose)}"
        body = export_pose(args.base, sliders, wearer, args.pose, name)
    print(f"wrote {BODIES}/{name}.obj, {name}.yaml, {SEG_FILE}")
    for key, val in body.items():
        print(f"  {key:22s} {val:8.2f}")


if __name__ == "__main__":
    main()
