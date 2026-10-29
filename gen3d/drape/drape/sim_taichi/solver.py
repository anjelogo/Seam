import time

import gstaichi as ti
import numpy as np

from . import constraints
from .attach import Attachments
from .integrate import integrate, snapshot
from .io import Scene, SceneFormatError
from .self_contact import MAX_THREADS


_ARCHES = {"vulkan": ti.vulkan, "metal": ti.metal, "cuda": ti.cuda, "cpu": ti.cpu}
_ACTIVE = 1


@ti.kernel
def _set_gravity(field: ti.template(), x: ti.f32, y: ti.f32, z: ti.f32):
    field[0] = ti.Vector([x, y, z])


def _size(count: int) -> int:
    return max(count, 1)


def _load(field, values: np.ndarray, dtype: np.dtype) -> None:
    if len(values):
        field.from_numpy(np.ascontiguousarray(values, dtype=dtype))


@ti.data_oriented
class Sim:
    def __init__(self, scene: Scene, arch: str) -> None:
        started = time.perf_counter()
        ti.init(
            arch=_ARCHES[arch],
            fast_math=False,
            default_fp=ti.f32,
            default_ip=ti.i32,
        )
        self.init_s = time.perf_counter() - started
        self.arch = arch
        self.scene = scene
        arrays = scene.arrays
        config = scene.sim
        self.n = len(arrays["x0"])
        self.n_faces = len(arrays["faces"])
        self.n_springs = len(arrays["springs"])
        self.n_bends = len(arrays["bend"])
        self.n_attachments = len(arrays["att_particle"])
        if int(config["iterations"]) != 1:
            raise SceneFormatError("Taichi XPBD requires exactly one iteration")
        self.substeps = int(config["substeps"])
        self.frame_dt = float(np.float32(config["frame_dt"]))
        self.sub_dt = float(np.float32(config["sub_dt"]))
        self.detect_dt = float(np.float32(config["detect_dt"]))
        self.damping = tuple(float(np.float32(value)) for value in config["damping"])
        self.damping_factor = self.damping[0]
        self.damping_effective = self.damping[1]
        self.damping_max_v = self.damping[2]
        self.particle_max_velocity = float(np.float32(config["particle_max_velocity"]))
        self.gravity_on = np.asarray(config["gravity"], dtype=np.float32)
        self.enable = config["enable"]

        self.x_in = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.v_in = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.x_out = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.v_out = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.x_frame0 = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.v_frame0 = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.delta = ti.Vector.field(3, ti.f32, shape=_size(self.n))
        self.inv_mass = ti.field(ti.f32, shape=_size(self.n))
        self.radius = ti.field(ti.f32, shape=_size(self.n))
        self.flags = ti.field(ti.i32, shape=_size(self.n))
        self.flag_pierced = ti.field(ti.i32, shape=_size(self.n))
        self.flag_drag = ti.field(ti.i32, shape=_size(self.n))
        self.ref_label = ti.field(ti.i32, shape=_size(self.n))
        self.faces = ti.Vector.field(3, ti.i32, shape=_size(self.n_faces))
        self.springs = ti.Vector.field(2, ti.i32, shape=_size(self.n_springs))
        self.gravity = ti.Vector.field(3, ti.f32, shape=1)

        self.spring_rest = ti.field(ti.f32, shape=_size(self.n_springs))
        self.spring_ke = ti.field(ti.f32, shape=_size(self.n_springs))
        self.spring_kd = ti.field(ti.f32, shape=_size(self.n_springs))
        self.spring_lambda = ti.field(ti.f32, shape=_size(self.n_springs))
        self.bend = ti.Vector.field(4, ti.i32, shape=_size(self.n_bends))
        self.bend_rest = ti.field(ti.f32, shape=_size(self.n_bends))
        self.bend_ke = ti.field(ti.f32, shape=_size(self.n_bends))
        self.bend_kd = ti.field(ti.f32, shape=_size(self.n_bends))
        self.bend_lambda = ti.field(ti.f32, shape=_size(self.n_bends))
        self.att_particle = ti.field(ti.i32, shape=_size(self.n_attachments))
        self.att_point = ti.Vector.field(3, ti.f32, shape=_size(self.n_attachments))
        self.att_normal = ti.Vector.field(3, ti.f32, shape=_size(self.n_attachments))
        self.att_ke = ti.field(ti.f32, shape=_size(self.n_attachments))
        self.att_kd = ti.field(ti.f32, shape=_size(self.n_attachments))
        self.att_lambda = ti.field(ti.f32, shape=_size(self.n_attachments))

        for field in (self.x_in, self.x_out):
            _load(field, arrays["x0"], np.dtype(np.float32))
        for field in (self.v_in, self.v_out):
            _load(field, arrays["v0"], np.dtype(np.float32))
        for field, name, dtype in (
            (self.inv_mass, "inv_mass", np.dtype(np.float32)),
            (self.radius, "radius", np.dtype(np.float32)),
            (self.flags, "flags", np.dtype(np.int32)),
            (self.faces, "faces", np.dtype(np.int32)),
            (self.springs, "springs", np.dtype(np.int32)),
            (self.ref_label, "ref_label", np.dtype(np.int32)),
            (self.spring_rest, "spring_rest", np.dtype(np.float32)),
            (self.spring_ke, "spring_ke", np.dtype(np.float32)),
            (self.spring_kd, "spring_kd", np.dtype(np.float32)),
            (self.bend, "bend", np.dtype(np.int32)),
            (self.bend_rest, "bend_rest", np.dtype(np.float32)),
            (self.bend_ke, "bend_ke", np.dtype(np.float32)),
            (self.att_particle, "att_particle", np.dtype(np.int32)),
            (self.att_point, "att_point", np.dtype(np.float32)),
            (self.att_normal, "att_normal", np.dtype(np.float32)),
            (self.att_ke, "att_ke", np.dtype(np.float32)),
            (self.att_kd, "att_kd", np.dtype(np.float32)),
        ):
            _load(field, arrays[name], dtype)

        from .body import Body
        from .panel_drag import PanelDrag
        from .self_contact import SelfContact

        self.body = Body(self)
        self.drag = PanelDrag(self, self.body)
        self.self_contact = SelfContact(self)
        self.attach = Attachments(self)
        self._overflow = {"soft_contact": 0, "point_triangle": 0, "edge_edge": 0}
        self._counters = ti.field(ti.i32, shape=4)
        self._grid_overflow = 0
        self._smooth = {
            int(frame): np.ascontiguousarray(verts, dtype=np.float32)
            for frame, verts in zip(arrays.get("smooth_frames", ()), arrays.get("smooth_verts", ()))
        }

        self.flag_drag_on = bool(self.enable["cloth_reference_drag"])
        self.flag_pt_on = bool(self.enable["triangle_particle_collisions"])
        self.flag_ee_on = bool(self.enable["edge_edge_collisions"]) and self.n_springs > 0
        self.flag_springs_on = self.n_springs > 0
        self.flag_bends_on = self.n_bends > 0
        self.flag_attach_capable = self.n_attachments > 0
        self.clear_m = max(self.n, self.n_springs, self.n_bends, self.n_attachments, 1)

    @ti.func
    def _integrate_particle(self, p, dt):
        x0 = self.x_in[p]
        if self.flags[p] & _ACTIVE:
            weight = self.inv_mass[p]
            gravity_scale = ti.cast(weight > 0.0, ti.f32)
            velocity = self.v_in[p] + self.gravity[0] * gravity_scale * dt
            speed = velocity.norm()
            if self.damping_factor > 0.0 and speed > self.damping_effective:
                velocity *= ti.exp(-self.damping_factor * speed * dt)
            if self.damping_max_v > 0.0 and speed > self.damping_max_v:
                velocity *= self.damping_max_v / speed
            self.x_out[p] = x0 + velocity * dt
            self.v_out[p] = velocity
        else:
            self.x_out[p] = x0

    @ti.func
    def _solve_spring(self, spring, dt):
        i = self.springs[spring][0]
        j = self.springs[spring][1]
        ke = self.spring_ke[spring]
        kd = self.spring_kd[spring]
        xij = self.x_out[i] - self.x_out[j]
        vij = self.v_out[i] - self.v_out[j]
        length = xij.norm()
        if length != 0.0:
            normal = xij / length
            constraint = length - self.spring_rest[spring]
            wi = self.inv_mass[i]
            wj = self.inv_mass[j]
            denominator = wi + wj
            if denominator > 0.0 and ke > 0.0 and kd >= 0.0:
                alpha = 1.0 / (ke * dt * dt)
                gamma = kd / (ke * dt)
                grad_dot_v = dt * normal.dot(vij)
                multiplier = -(constraint + alpha * self.spring_lambda[spring] + gamma * grad_dot_v) / (
                    (1.0 + gamma) * denominator + alpha
                )
                dxi = wi * multiplier * normal
                dxj = -wj * multiplier * normal
                self.spring_lambda[spring] += multiplier
                for axis in ti.static(range(3)):
                    ti.atomic_add(self.delta[i][axis], dxi[axis])
                    ti.atomic_add(self.delta[j][axis], dxj[axis])

    @ti.func
    def _solve_bend(self, bend, dt):
        i = self.bend[bend][0]
        j = self.bend[bend][1]
        k = self.bend[bend][2]
        l = self.bend[bend][3]
        if i != -1 and j != -1 and k != -1 and l != -1:
            x1, x2, x3, x4 = self.x_out[i], self.x_out[j], self.x_out[k], self.x_out[l]
            n1 = (x3 - x1).cross(x4 - x1)
            n2 = (x4 - x2).cross(x3 - x2)
            edge = x4 - x3
            n1_length = n1.norm()
            n2_length = n2.norm()
            edge_length = edge.norm()
            if n1_length >= 1.0e-6 and n2_length >= 1.0e-6 and edge_length >= 1.0e-6:
                n1_hat = n1 / n1_length
                n2_hat = n2 / n2_length
                edge_hat = edge / edge_length
                cosine = n1_hat.dot(n2_hat)
                sine = n1_hat.cross(n2_hat).dot(edge_hat)
                constraint = ti.atan2(sine, cosine) - self.bend_rest[bend]
                grad1 = -n1_hat * edge_length
                grad2 = -n2_hat * edge_length
                grad3 = -n1_hat * (x1 - x4).dot(edge_hat) - n2_hat * (x2 - x4).dot(edge_hat)
                grad4 = -n1_hat * (x3 - x1).dot(edge_hat) - n2_hat * (x3 - x2).dot(edge_hat)
                w1, w2, w3, w4 = self.inv_mass[i], self.inv_mass[j], self.inv_mass[k], self.inv_mass[l]
                denominator = (
                    w1 * grad1.norm_sqr()
                    + w2 * grad2.norm_sqr()
                    + w3 * grad3.norm_sqr()
                    + w4 * grad4.norm_sqr()
                )
                ke = self.bend_ke[bend]
                kd = self.bend_kd[bend]
                if denominator > 0.0 and ke > 0.0 and kd >= 0.0:
                    alpha = 1.0 / (ke * dt * dt)
                    gamma = kd / (ke * dt)
                    grad_dot_v = dt * (
                        grad1.dot(self.v_out[i]) + grad2.dot(self.v_out[j])
                        + grad3.dot(self.v_out[k]) + grad4.dot(self.v_out[l])
                    )
                    multiplier = -(constraint + alpha * self.bend_lambda[bend] + gamma * grad_dot_v) / (
                        (1.0 + gamma) * denominator + alpha
                    )
                    self.bend_lambda[bend] += multiplier
                    corr1 = w1 * multiplier * grad1
                    corr2 = w2 * multiplier * grad2
                    corr3 = w3 * multiplier * grad3
                    corr4 = w4 * multiplier * grad4
                    for axis in ti.static(range(3)):
                        ti.atomic_add(self.delta[i][axis], corr1[axis])
                        ti.atomic_add(self.delta[j][axis], corr2[axis])
                        ti.atomic_add(self.delta[k][axis], corr3[axis])
                        ti.atomic_add(self.delta[l][axis], corr4[axis])

    @ti.func
    def _apply_particle(self, p, dt):
        if self.flags[p] & _ACTIVE:
            x0 = self.x_in[p]
            x_new = self.x_out[p] + self.delta[p]
            v_new = (x_new - x0) / dt
            speed = v_new.norm()
            if speed > self.particle_max_velocity:
                v_new *= self.particle_max_velocity / speed
                x_new = x0 + v_new * dt
            self.x_in[p] = x_new
            self.v_in[p] = v_new

    @ti.kernel
    def _fused_substep(self, dt: ti.f32, attach_active: ti.i32):
        for p in range(self.n):
            self._integrate_particle(p, dt)
        for i in range(self.clear_m):
            if i < self.n:
                self.delta[i] = ti.Vector.zero(ti.f32, 3)
            if i < self.n_springs:
                self.spring_lambda[i] = 0.0
            if i < self.n_bends:
                self.bend_lambda[i] = 0.0
            if i < self.n_attachments:
                self.att_lambda[i] = 0.0
        for slot in range(self.body.contact_max):
            self.body._solve_slot(slot, dt)
        if ti.static(self.flag_drag_on):
            for p in range(self.n):
                self.drag._solve_particle(p)
        if ti.static(self.flag_pt_on):
            for slot in range(self.self_contact.pt_capacity):
                self.self_contact._solve_pt_slot(slot, self.self_contact.relaxation)
        if ti.static(self.flag_ee_on):
            for thread in range(min(self.self_contact.ee_capacity, MAX_THREADS)):
                slot = thread
                while slot < self.self_contact.ee_capacity:
                    self.self_contact._solve_ee_slot(slot, self.self_contact.relaxation)
                    slot += MAX_THREADS
        if ti.static(self.flag_springs_on):
            for s in range(self.n_springs):
                self._solve_spring(s, dt)
        if ti.static(self.flag_bends_on):
            for b in range(self.n_bends):
                self._solve_bend(b, dt)
        if ti.static(self.flag_attach_capable):
            for a in range(self.n_attachments):
                if attach_active != 0:
                    self.attach._solve_attachment(a, dt)
        for p in range(self.n):
            self._apply_particle(p, dt)

    def step_frame(self, frame: int) -> None:
        config = self.scene.sim
        if frame == int(config["zero_gravity_steps"]):
            _set_gravity(self.gravity, *(float(g) for g in self.gravity_on))
        self.attach.release(frame)
        smooth = self._smooth.get(frame)
        if smooth is not None:
            self.body.replace_points(smooth)

        snapshot(self)
        self.self_contact.clear_flags()
        self.self_contact.rebuild()
        self.body.generate()
        if self.enable["global_collision_filter"]:
            self.self_contact.piercing_survey()
        if self.n_springs:
            self.self_contact.detect_edge_edge(self.detect_dt)
        self.self_contact.detect_point_triangle(self.detect_dt)
        attach_active = 1 if self.attach.active else 0
        for _ in range(self.substeps):
            self._fused_substep(self.sub_dt, attach_active)

    def _substep(self) -> None:
        integrate(self, self.sub_dt)
        constraints.clear(self)
        self.body.solve(self.sub_dt)
        if self.enable["cloth_reference_drag"]:
            self.drag.solve()
        if self.enable["triangle_particle_collisions"]:
            self.self_contact.solve_point_triangle()
        if self.n_springs and self.enable["edge_edge_collisions"]:
            self.self_contact.solve_edge_edge()
        constraints.solve_internal(self, self.sub_dt)
        self.attach.solve(self.sub_dt)
        constraints.apply(self, self.sub_dt)

    def positions(self) -> np.ndarray:
        return np.asarray(self.x_in.to_numpy()[: self.n], dtype=np.float32).copy()

    def count_self_intersections(self) -> int:
        return int(self.self_contact.count_intersections())

    def count_body_intersections(self) -> int:
        return int(self.body.count_intersections())

    @ti.kernel
    def _gather_overflow(self):
        self._counters[0] = self.body._overflow[0]
        self._counters[1] = self.self_contact.pt_overflow[0]
        self._counters[2] = self.self_contact.ee_overflow[0]
        self._counters[3] = self.self_contact.grid.overflow_count[0]

    def read_overflow(self) -> dict[str, int]:
        self._gather_overflow()
        soft, pt, ee, grid = (int(v) for v in self._counters.to_numpy())
        if grid > self._grid_overflow:
            print(f"taichi triangle grid overflow: {grid - self._grid_overflow} entries dropped")
            self._grid_overflow = grid
        now = {"soft_contact": soft, "point_triangle": pt, "edge_edge": ee}
        dropped = {name: value - self._overflow[name] for name, value in now.items() if value > self._overflow[name]}
        self._overflow = now
        return dropped
