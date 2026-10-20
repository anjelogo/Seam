"""Bind a draped garment to the procedural mannequin and re-export it with the avatar's body morphs."""

from drape._repo import bootstrap

bootstrap()

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from app.glb import read_glb
from app.mannequin.export import blend, morph_normals, morphs, write_morph_glb
from app.mannequin.generator import body_mesh, vertex_normals
from app.mannequin.params import SLIDERS

from drape._repo import DRAPE

M = 100.0
GARMENT_MATERIAL = {
    "name": "garment",
    "doubleSided": True,
    "pbrMetallicRoughness": {"baseColorFactor": [0.82, 0.80, 0.78, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8},
}
OBJ_ORDER = ("sim/**/*_sim.obj", "**/*_sim.obj", "sim/**/*_boxmesh.obj", "**/*_boxmesh.obj")


def _kv(arg: str | None) -> dict[str, float]:
    out = {}
    for part in (arg or "").split(","):
        if not part.strip():
            continue
        key, _, val = part.partition("=")
        if (key := key.strip()) not in SLIDERS:
            raise SystemExit(f"unknown slider {key!r}; expected one of {', '.join(SLIDERS)}")
        out[key] = float(val)
    return out


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def garment_obj(out: Path, safe: str) -> Path | None:
    for pattern in OBJ_ORDER:
        hits = sorted((out / safe).glob(pattern))
        if hits:
            return hits[0]
    return None


def load_garment(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    mesh = trimesh.load(path, process=False)
    uv = getattr(mesh.visual, "uv", None)
    return np.asarray(mesh.vertices, float) / M, np.asarray(mesh.faces, np.int64), None if uv is None else np.asarray(uv, float)


def nearest_surface(verts: np.ndarray, faces: np.ndarray, pts: np.ndarray, k: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Exact nearest point on the surface: candidate triangles by centroid, refined, then bound-verified."""
    tri = verts[faces]
    centroid = tri.mean(1)
    tree = cKDTree(centroid)
    reach = float(np.linalg.norm(tri - centroid[:, None], axis=2).max())
    close, ids, todo = np.zeros_like(pts), np.zeros(len(pts), np.int64), np.arange(len(pts))
    while len(todo):
        k = min(k, len(faces))
        far, cand = tree.query(pts[todo], k=k, workers=-1)
        best = np.empty(len(todo))
        step = max(1, 2_000_000 // k)
        for s in range(0, len(todo), step):
            sl, c = slice(s, s + step), cand[s : s + step]
            pt = np.repeat(pts[todo[sl]], k, axis=0)
            cp = trimesh.triangles.closest_point(tri[c.ravel()], pt)
            d = np.linalg.norm(cp - pt, axis=1).reshape(c.shape)
            j, r = d.argmin(1), np.arange(len(c))
            best[sl], close[todo[sl]], ids[todo[sl]] = d[r, j], cp.reshape(*c.shape, 3)[r, j], c[r, j]
        todo = todo[~((far[:, -1] >= best + reach) | (k >= len(faces)))]
        k *= 4
    return close, ids


def _frame(verts: np.ndarray, faces: np.ndarray, tri: np.ndarray, bary: np.ndarray) -> tuple[np.ndarray, ...]:
    """Point and orthonormal frame carried by a triangle: in-plane tangents plus the interpolated normal."""
    corners = faces[tri]
    corner_v = verts[corners]
    pts = (bary[:, :, None] * corner_v).sum(1)
    n = _unit((bary[:, :, None] * vertex_normals(verts, faces)[corners]).sum(1))
    edge = corner_v[:, 1] - corner_v[:, 0]
    t1 = _unit(edge - (edge * n).sum(1, keepdims=True) * n)
    return pts, t1, np.cross(n, t1), n


def signed_distance(verts: np.ndarray, faces: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Negative inside. Pseudonormal test on the interpolated normal at the closest surface point."""
    close, tri = nearest_surface(verts, faces, pts)
    bary = trimesh.triangles.points_to_barycentric(verts[faces[tri]], close)
    normal = _frame(verts, faces, tri, bary)[3]
    delta = pts - close
    return np.copysign(np.linalg.norm(delta, axis=1), (delta * normal).sum(1))


def bind(garment: np.ndarray, verts: np.ndarray, faces: np.ndarray) -> dict[str, np.ndarray]:
    pts, tri = nearest_surface(verts, faces, garment)
    bary = trimesh.triangles.points_to_barycentric(verts[faces[tri]], pts)
    _, t1, t2, n = _frame(verts, faces, tri, bary)
    d = garment - pts
    local = np.stack([(d * t1).sum(1), (d * t2).sum(1), (d * n).sum(1)], 1)
    return {"tri": tri.astype(np.int64), "bary": bary, "local": local, "offset": local[:, 2]}


def reconstruct(b: dict, verts: np.ndarray, faces: np.ndarray, frame: bool = True) -> np.ndarray:
    pts, t1, t2, n = _frame(verts, faces, b["tri"], b["bary"])
    if not frame:
        return pts + b["offset"][:, None] * n
    local = b["local"]
    return pts + local[:, :1] * t1 + local[:, 1:2] * t2 + local[:, 2:3] * n


def garment_morphs(b: dict, base: str) -> tuple[np.ndarray, np.ndarray]:
    b0, faces, body_targets = morphs(lambda s: body_mesh(base, s))
    g0 = reconstruct(b, b0, faces)
    return g0, np.stack([reconstruct(b, b0 + t, faces) - g0 for t in body_targets])


def _dist(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    d = np.linalg.norm(a - b, axis=1) * M
    return {"mean_cm": round(float(d.mean()), 4), "max_cm": round(float(d.max()), 4), "p95_cm": round(float(np.percentile(d, 95)), 4)}


def _penetration(verts: np.ndarray, faces: np.ndarray, pts: np.ndarray) -> dict:
    sd = signed_distance(verts, faces, pts)
    inside = sd < 0
    return {"method": "pseudonormal", "count": int(inside.sum()), "pct": round(100.0 * inside.mean(), 3),
            "deepest_cm": round(float(-sd.min() * M) if inside.any() else 0.0, 3)}


def compare_obj(path: Path, recon: np.ndarray) -> dict:
    other = np.asarray(trimesh.load(path, process=False).vertices, float) / M
    if len(other) == len(recon):
        return {"mode": "per_vertex", "n": len(other), **_dist(recon, other)}
    d = cKDTree(other).query(recon)[0] * M
    return {"mode": "nearest_point", "n_recon": len(recon), "n_other": len(other),
            "mean_cm": round(float(d.mean()), 4), "max_cm": round(float(d.max()), 4)}


def verify_glb(path: Path, n_verts: int, n_faces: int) -> dict:
    gltf, blob = read_glb(path)
    mesh = gltf["meshes"][0]
    prim = mesh["primitives"][0]
    names = mesh["extras"]["targetNames"]
    pos = gltf["accessors"][prim["attributes"]["POSITION"]]["count"]
    idx = gltf["accessors"][prim["indices"]]["count"]
    assert len(prim["targets"]) == 8, f"{len(prim['targets'])} morph targets, expected 8"
    assert tuple(names) == SLIDERS, f"targetNames {names} != {list(SLIDERS)}"
    assert pos == n_verts, f"POSITION count {pos} != {n_verts}"
    assert idx == n_faces * 3, f"index count {idx} != {n_faces * 3}"
    return {"targets": len(prim["targets"]), "targetNames": names, "position_count": pos, "index_count": idx,
            "weights": mesh["weights"], "has_uv": "TEXCOORD_0" in prim["attributes"],
            "has_texture": "images" in gltf, "kb": round(path.stat().st_size / 1024, 1)}


def apply_texture(out: Path, safe: str, glb: Path) -> bool:
    png = out / safe / "texture" / "basecolor.png"
    if not png.exists():
        return False
    from PIL import Image

    from app.pipeline.bake import inject_texture

    inject_texture(glb, Image.open(png).convert("RGB"), glb)
    return True


def run(safe: str, inputs: Path, out: Path, base: str, sliders: dict, push: dict | None, compare: Path | None) -> dict:
    obj = garment_obj(out, safe)
    if obj is None:
        print(f"SKIP {safe}: no garment obj under {out / safe}")
        return {}
    gverts, gfaces, uv = load_garment(obj)
    body, bfaces = body_mesh(base, sliders)
    b = bind(gverts, body, bfaces)

    glb_dir = out / safe / "glb"
    glb_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(glb_dir / "binding.npz", base=base, sliders=np.array([sliders[k] for k in SLIDERS]),
                        faces=gfaces, uv=np.zeros((0, 2)) if uv is None else uv, **b)

    recon = reconstruct(b, body, bfaces)
    report = {
        "safe": safe, "obj": str(obj.relative_to(out)), "base": base,
        "sliders": sliders, "n_verts": len(gverts), "n_faces": len(gfaces),
        "obj_v_lines": sum(1 for ln in obj.read_text().splitlines() if ln.startswith("v ")),
        "offset_cm": {"mean": round(float(np.abs(b["offset"]).mean() * M), 3), "max": round(float(np.abs(b["offset"]).max() * M), 3)},
        "a_reconstruction": _dist(recon, gverts),
        "a_reconstruction_normal_only": _dist(reconstruct(b, body, bfaces, frame=False), gverts),
    }

    g0, targets = garment_morphs(b, base)
    normals, target_normals = morph_normals(g0, gfaces, targets)
    weights = [sliders[k] for k in SLIDERS]
    report["identity"] = {"blend_vs_original": _dist(blend(g0, targets, weights), gverts),
                          "blend_vs_reconstruction": _dist(blend(g0, targets, weights), recon)}

    glb = glb_dir / f"{safe}_bound.glb"
    # glTF samples textures from the top, OBJ from the bottom
    uv_glb = None if uv is None else np.c_[uv[:, 0], 1.0 - uv[:, 1]]
    write_morph_glb(glb, f"{safe}_bound", g0, normals, targets, target_normals, gfaces, dict(GARMENT_MATERIAL),
                    uv=uv_glb, names=SLIDERS)
    report["textured"] = apply_texture(out, safe, glb)

    if push:
        pverts, pfaces = body_mesh(base, push)
        pushed = reconstruct(b, pverts, pfaces)
        report["b_push"] = {"sliders": push, "displacement": _dist(pushed, recon),
                            "penetration": _penetration(pverts, pfaces, pushed),
                            "penetration_at_bind": _penetration(body, bfaces, gverts),
                            "morph_vs_reconstruction": _dist(blend(g0, targets, [push[k] for k in SLIDERS]), pushed)}
    if compare:
        target_body = body_mesh(base, push)[0] if push else body
        report["c_compare"] = {"obj": str(compare), **compare_obj(compare, reconstruct(b, target_body, bfaces))}
    report["d_glb"] = verify_glb(glb, len(gverts), len(gfaces))

    (glb_dir / "bind_report.json").write_text(json.dumps(report, indent=2))
    return report


def show(r: dict) -> None:
    print(f"\n{r['safe']}  {r['n_verts']} verts / {r['n_faces']} faces  <- {r['obj']}")
    print(f"  offset        mean {r['offset_cm']['mean']:6.2f} cm  max {r['offset_cm']['max']:6.2f} cm")
    a, na = r["a_reconstruction"], r["a_reconstruction_normal_only"]
    print(f"  (a) recon     mean {a['mean_cm']:6.3f} cm  max {a['max_cm']:6.3f} cm  "
          f"(normal-offset only: mean {na['mean_cm']:.3f} / max {na['max_cm']:.3f} cm)")
    i = r["identity"]["blend_vs_original"]
    print(f"      identity  mean {i['mean_cm']:6.3f} cm  max {i['max_cm']:6.3f} cm  (morph blend vs original)")
    if "b_push" in r:
        p = r["b_push"]
        print(f"  (b) push      mean {p['displacement']['mean_cm']:6.3f} cm  max {p['displacement']['max_cm']:6.3f} cm  "
              f"penetration {p['penetration']['count']} ({p['penetration']['pct']}%, deepest "
              f"{p['penetration']['deepest_cm']} cm), at bind {p['penetration_at_bind']['count']} "
              f"({p['penetration_at_bind']['pct']}%)")
    if "c_compare" in r:
        c = r["c_compare"]
        print(f"  (c) redrape   mean {c['mean_cm']:6.3f} cm  max {c['max_cm']:6.3f} cm  [{c['mode']}]")
    d = r["d_glb"]
    print(f"  (d) glb       {d['targets']} targets, names ok, POSITION {d['position_count']}, uv {d['has_uv']}, "
          f"texture {d['has_texture']}, {d['kb']} kB")


def main() -> None:
    ap = argparse.ArgumentParser(description="bind a draped garment to the mannequin and export body morphs")
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    ap.add_argument("--base", default="masc", choices=("masc", "fem"))
    ap.add_argument("--sliders", default=None, help="key=val,... the body the garment was draped on (defaults 0.5)")
    ap.add_argument("--push", default=None, help="key=val,... body to stress the binding against")
    ap.add_argument("--compare", type=Path, default=None, help="re-draped obj for the pushed body")
    args = ap.parse_args()

    sliders = {**dict.fromkeys(SLIDERS, 0.5), **_kv(args.sliders)}
    push = {**sliders, **_kv(args.push)} if args.push else None
    reports = []
    for d in sorted(args.inputs.iterdir()):
        if not (d / "item.json").exists() or (args.only and d.name != args.only):
            continue
        r = run(d.name, args.inputs, args.out, args.base, sliders, push, args.compare)
        if r:
            show(r)
            reports.append(r)
    if not reports:
        raise SystemExit("no items bound")
    print(f"\nbound {len(reports)} items -> {args.out}/<safe>/glb/")


if __name__ == "__main__":
    main()
