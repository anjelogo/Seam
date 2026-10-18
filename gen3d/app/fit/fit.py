import json
from functools import cache
from pathlib import Path

import numpy as np
import trimesh
from seam_shared.models import BodyBase, Slot, Transform

from app import settings

OUTER_GROWTH = 1.03
MIN_EXTENT = 1e-6


@cache
def _anchors() -> dict:
    return json.loads((settings.ASSETS_DIR / "anchors.json").read_text())


def fit_mesh(glb_path: Path, slot: Slot, base: BodyBase) -> Transform:
    anchor = _anchors()[base.value].get(slot.value)
    if anchor is None:
        return Transform()
    bounds = trimesh.load_scene(glb_path, skip_materials=True).bounds
    if bounds is None:
        raise ValueError(f"{glb_path.name} has no geometry to fit")
    extent, center = bounds[1] - bounds[0], bounds.mean(0)
    # width sets the scale unless that would overflow the anchor height
    ratios = [want / have for want, have in zip(anchor["size"][:2], extent[:2]) if have > MIN_EXTENT]
    if not ratios:
        raise ValueError(f"{glb_path.name} has no width or height to fit")
    k = min(ratios) * (OUTER_GROWTH if slot == Slot.outer else 1.0)
    return Transform(position=(np.asarray(anchor["center"]) - k * center).tolist(), scale=(k, k, k))
