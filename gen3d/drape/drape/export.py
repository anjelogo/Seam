"""Assemble draped garment GLBs (meters, Y-up, feet at origin) from the sim mesh + its texture/ maps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from drape._repo import DRAPE, bootstrap

bootstrap()

import trimesh  # noqa: E402

from drape.texture import CM, find_mesh, item_dirs, load_obj  # noqa: E402

MAPS = ("basecolor.png", "normal.png", "roughness.png")
BBOX_XZ = 1.0
BBOX_Y = (0.0, 2.0)


def corner_mesh(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One vertex per unique (position, uv) corner; cm -> m, no other transform."""
    verts, uvs, faces_v, faces_vt = load_obj(path)
    if not len(uvs):
        raise SystemExit(f"{path.name} has no vt uvs")
    pairs = np.stack([faces_v.ravel(), faces_vt.ravel()], 1)
    uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
    return verts[uniq[:, 0]] / CM, inv.reshape(-1, 3), uvs[uniq[:, 1]]


def build(mesh_path: Path, tex_dir: Path, out_path: Path, name: str) -> Path:
    for m in MAPS:
        if not (tex_dir / m).is_file():
            raise SystemExit(f"{tex_dir / m} missing - run drape.texture first")
    verts, faces, uv = corner_mesh(mesh_path)
    material = trimesh.visual.material.PBRMaterial(
        name=name,
        baseColorTexture=Image.open(tex_dir / "basecolor.png").convert("RGB"),
        normalTexture=Image.open(tex_dir / "normal.png").convert("RGB"),
        metallicRoughnessTexture=Image.open(tex_dir / "roughness.png").convert("RGB"),
        baseColorFactor=[255, 255, 255, 255],
        metallicFactor=1.0,
        roughnessFactor=1.0,
        doubleSided=True,
        alphaMode="OPAQUE",
    )
    mesh = trimesh.Trimesh(
        vertices=verts, faces=faces, process=False,
        visual=trimesh.visual.TextureVisuals(uv=uv, material=material),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene({name: mesh}), include_normals=True))
    return out_path


def verify(glb: Path) -> dict:
    scene = trimesh.load(glb, process=False)
    geoms = list(scene.geometry.values()) if isinstance(scene, trimesh.Scene) else [scene]
    mesh = geoms[0]
    mat = getattr(mesh.visual, "material", None)
    lo, hi = mesh.bounds
    return {
        "file": glb.name,
        "verts": len(mesh.vertices),
        "faces": len(mesh.faces),
        "uv": getattr(mesh.visual, "uv", None) is not None and len(mesh.visual.uv) == len(mesh.vertices),
        "basecolor": getattr(mat, "baseColorTexture", None) is not None,
        "normal": getattr(mat, "normalTexture", None) is not None,
        "roughness": getattr(mat, "metallicRoughnessTexture", None) is not None,
        "double_sided": bool(getattr(mat, "doubleSided", False)),
        "bbox": [[round(float(v), 3) for v in lo], [round(float(v), 3) for v in hi]],
        "in_bounds": bool(
            abs(lo[0]) <= BBOX_XZ and abs(hi[0]) <= BBOX_XZ
            and abs(lo[2]) <= BBOX_XZ and abs(hi[2]) <= BBOX_XZ
            and BBOX_Y[0] <= lo[1] and hi[1] <= BBOX_Y[1]
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    a = ap.parse_args()

    entries = item_dirs(a.inputs, a.only)
    if not entries:
        raise SystemExit(f"no items with item.json under {a.inputs}")
    report, bad = [], []
    for e in entries:
        safe = e["safe"]
        mesh_path = find_mesh(a.out, safe)
        if mesh_path is None:
            raise SystemExit(f"{safe}: no *_sim.obj or *_boxmesh.obj under {a.out / safe}")
        glb = build(mesh_path, a.out / safe / "texture", a.out / safe / "glb" / f"{safe}_draped.glb", safe)
        info = verify(glb) | {"safe": safe, "mesh": mesh_path.name}
        report.append(info)
        maps = " ".join(k for k in ("basecolor", "normal", "roughness") if info[k])
        print(f"{safe} | {glb.relative_to(a.out)} | {info['verts']}v {info['faces']}f | {maps}"
              f"{' uv' if info['uv'] else ' NO-UV'} | doubleSided {info['double_sided']} | "
              f"bbox {info['bbox'][0]} -> {info['bbox'][1]} m | {'in bounds' if info['in_bounds'] else 'OUT OF BOUNDS'}")
        if not (info["uv"] and info["basecolor"] and info["in_bounds"]):
            bad.append(safe)
    (a.out / "glb_report.json").write_text(json.dumps(report, indent=2))
    if bad:
        raise SystemExit(f"verify failed: {', '.join(bad)}")
    print(f"ok: {len(report)} glbs verified")


if __name__ == "__main__":
    main()
