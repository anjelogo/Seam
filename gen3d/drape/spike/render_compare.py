"""Offscreen side-by-side render of fork vs port drape results. Spike-only.

Body and garment go into ONE Poly3DCollection so matplotlib depth-sorts them against
each other; two separate collections let the body paint over the garment.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

BODY_RGBA = (0.78, 0.78, 0.80, 1.0)
GARMENT_RGBA = (0.76, 0.27, 0.18, 1.0)


def tris(path: Path, scale: float) -> np.ndarray:
    m = trimesh.load(path, process=False, force="mesh")
    v = np.asarray(m.vertices, dtype=float) * scale
    f = np.asarray(m.faces, dtype=int)
    # world (x, y up, z) -> plot axes (x, z, y up)
    return v[:, [0, 2, 1]][f]


def panel(ax, body: Path, garment: Path | None, title: str, note: str = "") -> None:
    ax.set_title(title, fontsize=7.5, linespacing=1.35)
    ax.set_axis_off()
    polys, colors = [], []
    if body.exists():
        b = tris(body, 1.0)
        polys.append(b)
        colors.append(np.tile(BODY_RGBA, (len(b), 1)))
    if garment is not None and garment.exists():
        g = tris(garment, 0.01)  # sim objs are cm, bodies are m
        polys.append(g)
        colors.append(np.tile(GARMENT_RGBA, (len(g), 1)))
    if polys:
        col = Poly3DCollection(np.concatenate(polys), facecolors=np.concatenate(colors),
                               linewidths=0, zsort="average")
        ax.add_collection3d(col)
    if garment is None or not garment.exists():
        ax.text2D(0.5, 0.42, note or "NO RESULT", transform=ax.transAxes, ha="center", va="center",
                  fontsize=10, color="#b00020", weight="bold", linespacing=1.4)
    ax.set_box_aspect((1, 1, 2.3))
    ax.view_init(elev=6, azim=-89)
    ax.set_xlim(-0.55, 0.55)
    ax.set_ylim(-0.55, 0.55)
    ax.set_zlim(0.0, 1.85)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--fork", type=Path, required=True)
    ap.add_argument("--port", type=Path, default=None)
    ap.add_argument("--fork-label", default="fork")
    ap.add_argument("--port-label", default="port")
    ap.add_argument("--port-note", default="PORT FAILED")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    fig = plt.figure(figsize=(9, 6), dpi=150)
    fig.suptitle(args.title.replace("\\n", "\n"), fontsize=10, weight="bold")
    for i, (g, lab) in enumerate(((args.fork, args.fork_label), (args.port, args.port_label))):
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        panel(ax, args.body, g, lab.replace("\\n", "\n"), args.port_note.replace("\\n", "\n") if i else "")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
