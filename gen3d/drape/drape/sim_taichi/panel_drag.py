from __future__ import annotations

from typing import Final

import gstaichi as ti
import numpy as np


UNBOUNDED: Final = 1.0e6
SEARCH_RADIUS: Final = 1.0e3
FLAG_CLOTH_CLOTH: Final = 1
FLAG_INSIDE_BODY: Final = 2
_ACTIVE: Final = 1


@ti.data_oriented
class PanelDrag:
    def __init__(self, sim, body) -> None:
        self.sim = sim
        self.bvh = body.bvh
        self.margin = float(np.float32(sim.scene.sim["cloth_reference_margin"]))
        axes = np.ascontiguousarray(sim.scene.sim["ray_axes"], dtype=np.float32).reshape(-1, 3)
        self.axes = ti.Vector.field(3, dtype=ti.f32, shape=len(axes))
        self.axes.from_numpy(axes)

    @ti.func
    def _inside_whole_body(self, point):
        votes = 0
        for axis in ti.static(range(3)):
            hit, _, _, _, _, sign = self.bvh.query_ray(0, point, self.axes[axis], UNBOUNDED)
            if hit and sign < 0.0:
                votes += 1
        return votes == 3

    @ti.func
    def _solve_particle(self, particle):
        flag = self.sim.flag_drag[particle]
        label = self.sim.ref_label[particle]
        if flag != 0 and self.sim.flags[particle] & _ACTIVE and label >= 0:
            mesh = 0
            if flag == FLAG_CLOTH_CLOTH:
                mesh = label + 1
            hit, face, u, v = self.bvh.query_point_no_sign(
                mesh,
                self.sim.x_in[particle],
                SEARCH_RADIUS,
            )
            if hit:
                point = self.sim.x_in[particle]
                target = self.bvh.eval_position(mesh, face, u, v)
                gap = target - point
                error = gap.norm()
                if self._inside_whole_body(point):
                    error = -error
                apply = False
                if flag == FLAG_CLOTH_CLOTH:
                    apply = error > self.margin + self.sim.radius[particle]
                elif flag == FLAG_INSIDE_BODY:
                    apply = error < 0.0
                if apply:
                    for axis in ti.static(range(3)):
                        ti.atomic_add(self.sim.delta[particle][axis], gap[axis])

    @ti.kernel
    def _solve(self):
        for particle in range(self.sim.n):
            self._solve_particle(particle)

    def solve(self) -> None:
        self._solve()
