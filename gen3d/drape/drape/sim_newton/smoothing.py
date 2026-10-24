from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import scipy.sparse as sparse
import scipy.sparse.linalg as splinalg

if TYPE_CHECKING:
    from .builder import ClothData

TINY = 1.0e-12


def _cotangent(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    cross = np.linalg.norm(np.cross(a, b), axis=1)
    return np.einsum("ij,ij->i", a, b) / np.maximum(cross, TINY)


def _cotangent_laplacian(verts: np.ndarray, tris: np.ndarray) -> sparse.csc_matrix:
    n = len(verts)
    i0, i1, i2 = tris[:, 0], tris[:, 1], tris[:, 2]
    p0, p1, p2 = verts[i0], verts[i1], verts[i2]
    c0 = _cotangent(p1 - p0, p2 - p0)
    c1 = _cotangent(p2 - p1, p0 - p1)
    c2 = _cotangent(p0 - p2, p1 - p2)
    rows = np.concatenate([i1, i2, i2, i0, i0, i1])
    cols = np.concatenate([i2, i1, i0, i2, i1, i0])
    vals = 0.5 * np.concatenate([c0, c0, c1, c1, c2, c2])
    off = sparse.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    return (off - sparse.diags(np.asarray(off.sum(axis=1)).ravel())).tocsc()


def _barycentric_mass(verts: np.ndarray, tris: np.ndarray) -> sparse.csc_matrix:
    p0, p1, p2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    lumped = np.zeros(len(verts))
    np.add.at(lumped, tris.reshape(-1), np.repeat(area / 3.0, 3))
    return sparse.diags(np.maximum(lumped, TINY)).tocsc()


def implicit_laplacian_smoothing(
    verts: np.ndarray, tris: np.ndarray, step: float, iterations: int
) -> list[np.ndarray]:
    current = np.ascontiguousarray(verts, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    sequence = [current.copy()]
    steps = int(iterations)
    if steps <= 0:
        return sequence
    laplacian = _cotangent_laplacian(current, faces)  # §3.7: built once, from the original mesh
    for _ in range(steps):
        mass = _barycentric_mass(current, faces)
        solve = splinalg.factorized((mass - float(step) * laplacian).tocsc())
        rhs = mass @ current
        current = np.column_stack([solve(np.ascontiguousarray(rhs[:, k])) for k in range(3)])
        sequence.append(current)
    return sequence


class BodySmoother:
    def __init__(self, config, cloth: ClothData) -> None:
        verts = np.ascontiguousarray(cloth.body_verts, dtype=np.float64).reshape(-1, 3)
        start = int(config.smoothing_recover_start_frame)
        gap = int(config.smoothing_frame_gap_between_steps)
        steps = max(min(int(config.smoothing_num_steps), int(config.max_sim_steps) - start), 0)
        self.enabled = bool(config.enable_body_smoothing) and steps > 0
        self._start = start
        self._gap = gap
        self._steps = steps
        if not self.enabled:
            self._sequence = [verts]
            self._frames: list[int] = []
            self._by_frame: dict[int, np.ndarray] = {}
            return
        step_size = float(config.smoothing_total_smoothing_factor) / steps
        self._sequence = implicit_laplacian_smoothing(verts, cloth.body_faces, step_size, steps)
        # the last frame is dropped: its shape is the one the sim starts from
        self._frames = [start + n * gap for n in range(steps)]
        self._by_frame = {f: self._sequence[steps - 1 - n] for n, f in enumerate(self._frames)}

    @property
    def frames(self) -> list[int]:
        return list(self._frames)

    @property
    def start_verts(self) -> np.ndarray:
        return self._sequence[-1]

    def verts_for_frame(self, frame: int) -> np.ndarray | None:
        return self._by_frame.get(int(frame))

    def min_sim_steps(self) -> int:
        return self._start + self._steps if self.enabled else 0
