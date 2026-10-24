from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import warp as wp
from newton import ParticleFlags

if TYPE_CHECKING:
    import newton

    from .builder import Ctx

UNBOUNDED = 1.0e6
FLAG_INSIDE_BODY = 2


@wp.kernel
def generate_body_contacts(
    x: wp.array(dtype=wp.vec3),
    particle_radius: wp.array(dtype=float),
    particle_flags: wp.array(dtype=wp.int32),
    body_mesh: wp.uint64,
    face_filters: wp.array2d(dtype=wp.uint8),
    particle_filter_id: wp.array(dtype=wp.int32),
    thickness: float,
    margin: float,
    shape_index: int,
    contact_max: int,
    contact_count: wp.array(dtype=wp.int32),
    contact_particle: wp.array(dtype=wp.int32),
    contact_shape: wp.array(dtype=wp.int32),
    contact_body_pos: wp.array(dtype=wp.vec3),
    contact_body_vel: wp.array(dtype=wp.vec3),
    contact_normal: wp.array(dtype=wp.vec3),
    overflow: wp.array(dtype=wp.int32),
    flag_drag: wp.array(dtype=wp.int32),
):
    tid = wp.tid()
    flag_drag[tid] = 0

    if (particle_flags[tid] & ParticleFlags.ACTIVE) == 0:
        return

    px = x[tid]
    query = wp.mesh_query_point_sign_normal(body_mesh, px, UNBOUNDED)
    if not query.result:
        return

    filter_id = particle_filter_id[tid]
    if filter_id >= 0:
        # a filtered closest face discards the contact and the inside test both
        if face_filters[filter_id, query.face] != wp.uint8(0):
            return

    surface = wp.mesh_eval_position(body_mesh, query.face, query.u, query.v)
    gap = px - surface
    n = wp.normalize(gap) * query.sign
    d = wp.length(gap) * query.sign - thickness

    if d > -margin and d < margin + particle_radius[tid]:
        slot = wp.atomic_add(contact_count, 0, 1)
        if slot < contact_max:
            contact_particle[slot] = tid
            contact_shape[slot] = shape_index
            # thickness shell point; the radius is subtracted by the solve kernel
            contact_body_pos[slot] = surface + n * thickness
            contact_body_vel[slot] = wp.vec3(0.0, 0.0, 0.0)
            contact_normal[slot] = n
        else:
            wp.atomic_add(overflow, 0, 1)

    if d < -margin:
        flag_drag[tid] = FLAG_INSIDE_BODY


# adapted from Newton's solve_particle_shape_contacts, Apache-2.0
@wp.kernel
def solve_body_contacts(
    x: wp.array(dtype=wp.vec3),
    v: wp.array(dtype=wp.vec3),
    particle_inv_mass: wp.array(dtype=float),
    particle_radius: wp.array(dtype=float),
    particle_flags: wp.array(dtype=wp.int32),
    shape_material_mu: wp.array(dtype=float),
    particle_mu: float,
    particle_ka: float,
    shape_index: int,
    contact_max: int,
    contact_count: wp.array(dtype=wp.int32),
    contact_particle: wp.array(dtype=wp.int32),
    contact_body_pos: wp.array(dtype=wp.vec3),
    contact_normal: wp.array(dtype=wp.vec3),
    dt: float,
    relaxation: float,
    delta: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()

    count = wp.min(contact_max, contact_count[0])
    if tid >= count:
        return

    p = contact_particle[tid]
    if (particle_flags[p] & ParticleFlags.ACTIVE) == 0:
        return

    n = contact_normal[tid]
    c = wp.dot(n, x[p] - contact_body_pos[tid]) - particle_radius[p]
    if c > particle_ka:
        return

    denom = particle_inv_mass[p]
    if denom == 0.0:
        return

    mu = 0.5 * (particle_mu + shape_material_mu[shape_index])

    vel = v[p]
    vt = vel - n * wp.dot(n, vel)

    delta_n = n * c
    delta_f = wp.normalize(vt) * wp.max(mu * c, -wp.length(vt) * dt)
    # upstream scales by the inverse mass here; the reference does not (SIM_SPEC 10.5)
    wp.atomic_add(delta, p, (delta_f - delta_n) / denom * relaxation)


@wp.kernel
def count_body_crossings(
    springs: wp.array(dtype=wp.int32),
    points: wp.array(dtype=wp.vec3),
    body_mesh: wp.uint64,
    counter: wp.array(dtype=wp.int32),
):
    s = wp.tid()
    a = points[springs[2 * s + 0]]
    b = points[springs[2 * s + 1]]
    seg = b - a
    edge_len = wp.length(seg)
    if edge_len == 0.0:
        return
    if wp.mesh_query_ray_anyhit(body_mesh, a, seg / edge_len, edge_len):
        wp.atomic_add(counter, 0, 1)


class BodyCollider:
    def __init__(
        self,
        ctx: Ctx,
        newton_body_mesh: newton.Mesh,
        thickness: float,
        soft_contact_margin: float,
    ) -> None:
        mesh = newton_body_mesh.mesh
        if mesh is None:
            raise RuntimeError("body mesh is not finalized; build BodyCollider after Model.finalize()")
        self.mesh = mesh
        ctx.body_mesh = mesh
        self.thickness = float(thickness)
        self.margin = float(soft_contact_margin)
        self.ctx = ctx
        self.device = mesh.points.device
        self.contact_max = int(ctx.soft_contact_particle.shape[0])
        self.particle_count = int(ctx.x_frame0.shape[0])
        self.spring_count = int(ctx.springs.shape[0]) // 2

    def generate(self) -> None:
        ctx = self.ctx
        ctx.soft_contact_count.zero_()
        ctx.soft_contact_overflow.zero_()
        wp.launch(
            generate_body_contacts,
            dim=self.particle_count,
            inputs=[
                ctx.x_frame0,
                ctx.model.particle_radius,
                ctx.model.particle_flags,
                self.mesh.id,
                ctx.face_filters,
                ctx.particle_filter_id,
                self.thickness,
                self.margin,
                ctx.shape_index_body,
                self.contact_max,
            ],
            outputs=[
                ctx.soft_contact_count,
                ctx.soft_contact_particle,
                ctx.soft_contact_shape,
                ctx.soft_contact_body_pos,
                ctx.soft_contact_body_vel,
                ctx.soft_contact_normal,
                ctx.soft_contact_overflow,
                ctx.flag_drag,
            ],
            device=self.device,
        )

    def solve(self, dt: float, relaxation: float = 0.9) -> None:
        ctx = self.ctx
        model = ctx.model
        wp.launch(
            solve_body_contacts,
            dim=self.contact_max,
            inputs=[
                ctx.state_out.particle_q,
                ctx.state_out.particle_qd,
                model.particle_inv_mass,
                model.particle_radius,
                model.particle_flags,
                model.shape_material_mu,
                float(model.particle_mu),
                float(model.particle_adhesion),
                ctx.shape_index_body,
                self.contact_max,
                ctx.soft_contact_count,
                ctx.soft_contact_particle,
                ctx.soft_contact_body_pos,
                ctx.soft_contact_normal,
                dt,
                relaxation,
            ],
            outputs=[ctx.delta],
            device=self.device,
        )

    def replace_points(self, verts: np.ndarray) -> None:
        points = np.ascontiguousarray(verts, dtype=np.float32).reshape(-1, 3)
        if points.shape[0] != self.mesh.points.shape[0]:
            raise ValueError(
                f"expected {self.mesh.points.shape[0]} body vertices, got {points.shape[0]}"
            )
        wp.copy(self.mesh.points, wp.array(points, dtype=wp.vec3, device=self.device))
        self.mesh.refit()

    def count_body_intersections(self) -> int:
        ctx = self.ctx
        ctx.counter_body.zero_()
        if self.particle_count == 0 or self.spring_count == 0:
            return 0
        wp.launch(
            count_body_crossings,
            dim=self.spring_count,
            inputs=[ctx.springs, ctx.cloth_mesh.points, self.mesh.id],
            outputs=[ctx.counter_body],
            device=self.device,
        )
        return int(ctx.counter_body.numpy()[0])
