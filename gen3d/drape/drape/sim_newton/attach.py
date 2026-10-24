from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Union

import numpy as np
import warp as wp

if TYPE_CHECKING:
    from .builder import Ctx

Vec3 = Union[Sequence[float], np.ndarray]

__all__ = ["Attachments"]


@wp.kernel
def solve_attachments(
    x: wp.array(dtype=wp.vec3),
    v: wp.array(dtype=wp.vec3),
    invmass: wp.array(dtype=float),
    att_particle: wp.array(dtype=wp.int32),
    att_point: wp.array(dtype=wp.vec3),
    att_normal: wp.array(dtype=wp.vec3),
    att_stiffness: wp.array(dtype=float),
    att_damping: wp.array(dtype=float),
    att_lambda: wp.array(dtype=float),
    dt: float,
    delta: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()

    p = att_particle[tid]
    ke = att_stiffness[tid]
    kd = att_damping[tid]
    w = invmass[p]

    # zero damping is valid, non-positive stiffness disables the entry
    if w <= 0.0 or ke <= 0.0 or kd < 0.0:
        return

    xp = x[p]
    target = att_point[tid]
    n = att_normal[tid]

    if wp.length_sq(n) == 0.0:
        # equality: the normal becomes the particle-to-target direction, so c <= 0 always
        d = target - xp
        l = wp.length(d)
        if l == 0.0:
            return
        n = d / l

    c = wp.dot(xp - target, n)
    if c >= 0.0:
        return

    alpha = 1.0 / (ke * dt * dt)
    gamma = kd / (ke * dt)

    grad_c_dot_v = dt * wp.dot(n, v[p])
    dlambda = -1.0 * (c + alpha * att_lambda[tid] + gamma * grad_c_dot_v) / ((1.0 + gamma) * w + alpha)

    # SIM_SPEC 3.6: the multiplier is deliberately not accumulated back into att_lambda
    wp.atomic_add(delta, p, w * dlambda * n)


class Attachments:
    def __init__(self) -> None:
        self._particles: list[int] = []
        self._points: list[tuple[float, float, float]] = []
        self._normals: list[tuple[float, float, float]] = []
        self._stiffness: list[float] = []
        self._damping: list[float] = []
        self._ctx: Ctx | None = None

    def add(
        self,
        particles: Sequence[int],
        point: Vec3 | Sequence[Vec3],
        normal: Vec3 | None = None,
        *,
        stiffness: float,
        damping: float,
    ) -> None:
        idx = [int(p) for p in particles]
        if not idx:
            return
        self._particles.extend(idx)
        self._points.extend(_broadcast(point, len(idx), "point"))
        self._normals.extend(
            [(0.0, 0.0, 0.0)] * len(idx) if normal is None else _unit(_broadcast(normal, len(idx), "normal"))
        )
        self._stiffness.extend([float(stiffness)] * len(idx))
        self._damping.extend([float(damping)] * len(idx))

    def finalize(self, ctx: Ctx) -> int:
        self._ctx = ctx
        n = len(self._particles)
        device = ctx.delta.device
        _upload(ctx, "att_particle", np.asarray(self._particles, np.int32).reshape(n), wp.int32, device)
        _upload(ctx, "att_point", np.asarray(self._points, np.float32).reshape(n, 3), wp.vec3, device)
        _upload(ctx, "att_normal", np.asarray(self._normals, np.float32).reshape(n, 3), wp.vec3, device)
        _upload(ctx, "att_stiffness", np.asarray(self._stiffness, np.float32).reshape(n), float, device)
        _upload(ctx, "att_damping", np.asarray(self._damping, np.float32).reshape(n), float, device)
        _upload(ctx, "att_lambda", np.zeros(n, np.float32), float, device)
        return n

    def zero_lambdas(self) -> None:
        if self._ctx is not None and self.count:
            self._ctx.att_lambda.zero_()

    def solve(self, dt: float) -> None:
        ctx = self._ctx
        if ctx is None or not self.count:
            return
        wp.launch(
            solve_attachments,
            dim=self.count,
            inputs=[
                ctx.state_out.particle_q,
                ctx.state_out.particle_qd,
                ctx.model.particle_inv_mass,
                ctx.att_particle,
                ctx.att_point,
                ctx.att_normal,
                ctx.att_stiffness,
                ctx.att_damping,
                ctx.att_lambda,
                dt,
            ],
            outputs=[ctx.delta],
            device=ctx.delta.device,
        )

    @property
    def count(self) -> int:
        return len(self._particles)


def _broadcast(value: Vec3 | Sequence[Vec3], n: int, what: str) -> list[tuple[float, float, float]]:
    a = np.asarray(value, dtype=np.float64)
    if a.shape == (3,):
        return [tuple(a)] * n
    if a.shape == (n, 3):
        return [tuple(row) for row in a]
    raise ValueError(f"attachment {what} must be one vec3 or {n} vec3s, got shape {a.shape}")


def _unit(normals: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    out = []
    for v in normals:
        l = float(np.linalg.norm(v))
        out.append((0.0, 0.0, 0.0) if l == 0.0 else tuple(float(c) / l for c in v))
    return out


def _upload(ctx: Ctx, name: str, values: np.ndarray, dtype, device) -> None:
    existing = getattr(ctx, name, None)
    if existing is not None and len(existing) == len(values):
        existing.assign(values)
        return
    setattr(ctx, name, wp.array(values, dtype=dtype, device=device))
