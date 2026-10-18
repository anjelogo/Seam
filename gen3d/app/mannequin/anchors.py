import json
from pathlib import Path

import numpy as np
from seam_shared.models import BodyBase, Slot

from app.mannequin.export import blend, morphs
from app.mannequin.generator import ARM, LEG, TRUNK, body_mesh, split


def _box(points: np.ndarray) -> dict:
    lo, hi = points.min(0), points.max(0)
    return {"center": ((lo + hi) / 2).round(4).tolist(), "size": (hi - lo).round(4).tolist()}


def body_anchors(base: str) -> dict:
    verts, _, targets = morphs(lambda s: body_mesh(base, s))
    parts = split(blend(verts, targets, 0.5))
    rings, crotch, _ = parts["trunk"]

    def trunk(i0: int, i1: int) -> np.ndarray:
        return rings[i0 : i1 + 1].reshape(-1, 3)

    def limbs(kind: str, end: int) -> np.ndarray:
        return np.vstack([np.vstack([parts[f"{kind}_{s}"][1], parts[f"{kind}_{s}"][0][: end + 1].reshape(-1, 3)]) for s in "lr"])

    sleeves, legs = limbs("arm", ARM["mid_upper"]), limbs("leg", LEG["ankle"])
    top = np.vstack([trunk(TRUNK["hip"], TRUNK["neckbase"]), sleeves])
    feet = np.vstack([np.vstack([r.reshape(-1, 3), s, e]) for r, s, e in (parts["foot_l"], parts["foot_r"])])
    return {
        Slot.top.value: _box(top),
        Slot.bottom.value: _box(np.vstack([crotch, trunk(0, TRUNK["waist"]), legs])),
        Slot.outer.value: _box(top),
        Slot.onepiece.value: _box(np.vstack([crotch, trunk(0, TRUNK["neckbase"]), sleeves, legs])),
        Slot.shoes.value: _box(feet),
    }


def write_anchors(path: Path) -> Path:
    path.write_text(json.dumps({b.value: body_anchors(b.value) for b in BodyBase}, indent=2) + "\n")
    return path
