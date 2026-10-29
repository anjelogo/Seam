from typing import TYPE_CHECKING

import gstaichi as ti

if TYPE_CHECKING:
    from .solver import Sim


@ti.func
def _atomic_add_vec(field, index, value):
    for axis in ti.static(range(3)):
        ti.atomic_add(field[index][axis], value[axis])


@ti.data_oriented
class Attachments:
    def __init__(self, sim: "Sim") -> None:
        self.sim = sim
        self.active = bool(sim.scene.sim["attachment_enabled"] and sim.n_attachments)
        self.release_frame = int(sim.scene.sim["attachment_frames"])

    def release(self, frame: int) -> None:
        if self.active and frame >= self.release_frame:
            self.active = False

    @ti.func
    def _solve_attachment(self, attachment, dt):
        sim = self.sim
        p = sim.att_particle[attachment]
        ke = sim.att_ke[attachment]
        kd = sim.att_kd[attachment]
        weight = sim.inv_mass[p]
        if weight > 0.0 and ke > 0.0 and kd >= 0.0:
            xp = sim.x_out[p]
            target = sim.att_point[attachment]
            direction = sim.att_normal[attachment]
            valid = True
            if direction.norm_sqr() == 0.0:
                offset = target - xp
                length = offset.norm()
                if length == 0.0:
                    valid = False
                else:
                    direction = offset / length
            constraint = (xp - target).dot(direction)
            if valid and constraint < 0.0:
                alpha = 1.0 / (ke * dt * dt)
                gamma = kd / (ke * dt)
                grad_dot_v = dt * direction.dot(sim.v_out[p])
                multiplier = -(constraint + alpha * sim.att_lambda[attachment] + gamma * grad_dot_v) / (
                    (1.0 + gamma) * weight + alpha
                )
                _atomic_add_vec(sim.delta, p, weight * multiplier * direction)

    @ti.kernel
    def _solve(self, dt: ti.f32):
        for attachment in range(self.sim.n_attachments):
            self._solve_attachment(attachment, dt)

    def solve(self, dt: float) -> None:
        if not self.active:
            return
        self._solve(float(dt))
