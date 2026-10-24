from __future__ import annotations

from typing import TYPE_CHECKING

import warp as wp

if TYPE_CHECKING:
    from .builder import Ctx, SimParams

_EPS = 1.0e-6
_DET_EPS = 1.0e-12
_DENOM_EPS = 1.0e-5
_SEG_EPS = 1.0e-3


@wp.func
def _tri_bary(a: wp.vec3, b: wp.vec3, c: wp.vec3, p: wp.vec3):
    ab = b - a
    ac = c - a
    ap = p - a

    d1 = wp.dot(ab, ap)
    d2 = wp.dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return wp.vec3(1.0, 0.0, 0.0)

    bp = p - b
    d3 = wp.dot(ab, bp)
    d4 = wp.dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return wp.vec3(0.0, 1.0, 0.0)

    vc = d1 * d4 - d3 * d2
    v = d1 / (d1 - d3)
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return wp.vec3(1.0 - v, v, 0.0)

    cp = p - c
    d5 = wp.dot(ab, cp)
    d6 = wp.dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return wp.vec3(0.0, 0.0, 1.0)

    vb = d5 * d2 - d1 * d6
    w = d2 / (d2 - d6)
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return wp.vec3(1.0 - w, 0.0, w)

    va = d3 * d6 - d5 * d4
    w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        return wp.vec3(0.0, 1.0 - w, w)

    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    return wp.vec3(1.0 - v - w, v, w)


@wp.func
def _seg_seg(p0: wp.vec3, p1: wp.vec3, q0: wp.vec3, q1: wp.vec3):
    d1 = p1 - p0
    d2 = q1 - q0
    rv = p0 - q0
    a = wp.dot(d1, d1)
    e = wp.dot(d2, d2)
    f = wp.dot(d2, rv)
    if a <= _SEG_EPS and e <= _SEG_EPS:
        return wp.vec2(0.0, 0.0)
    if a <= _SEG_EPS:
        return wp.vec2(0.0, wp.clamp(f / e, 0.0, 1.0))
    c = wp.dot(d1, rv)
    if e <= _SEG_EPS:
        return wp.vec2(wp.clamp(-c / a, 0.0, 1.0), 0.0)
    b = wp.dot(d1, d2)
    denom = a * e - b * b
    s = float(0.0)
    if denom != 0.0:
        s = wp.clamp((b * f - c * e) / denom, 0.0, 1.0)
    t = (b * s + f) / e
    if t < 0.0:
        return wp.vec2(wp.clamp(-c / a, 0.0, 1.0), 0.0)
    if t > 1.0:
        return wp.vec2(wp.clamp((b - c) / a, 0.0, 1.0), 1.0)
    return wp.vec2(s, t)


@wp.func
def _predict_dx(v: wp.vec3, w: float, g: wp.vec3, dt: float):
    # §10.1: no half, and gravity carries the inverse mass
    return v * dt + g * (w * dt * dt)


@wp.func
def _ray_tri_t(orig: wp.vec3, dir: wp.vec3, a: wp.vec3, b: wp.vec3, c: wp.vec3):
    e1 = b - a
    e2 = c - a
    pv = wp.cross(dir, e2)
    det = wp.dot(e1, pv)
    if wp.abs(det) < _DET_EPS:
        return -1.0
    inv = 1.0 / det
    tv = orig - a
    u = wp.dot(tv, pv) * inv
    if u < 0.0 or u > 1.0:
        return -1.0
    qv = wp.cross(tv, e1)
    vb = wp.dot(dir, qv) * inv
    if vb < 0.0 or u + vb > 1.0:
        return -1.0
    return wp.dot(e2, qv) * inv


@wp.func
def _segment_pierce_face(
    mesh: wp.uint64,
    points: wp.array(dtype=wp.vec3),
    vi: int,
    vj: int,
):
    p0 = points[vi]
    p1 = points[vj]
    seg = p1 - p0
    length = wp.length(seg)
    if length <= _EPS:
        return -1
    dir = seg / length

    query = wp.mesh_query_aabb(mesh, wp.min(p0, p1), wp.max(p0, p1))
    face = int(0)
    best = int(-1)
    best_t = float(length)
    while wp.mesh_query_next(query, face):
        i0 = wp.mesh_get_index(mesh, face * 3 + 0)
        i1 = wp.mesh_get_index(mesh, face * 3 + 1)
        i2 = wp.mesh_get_index(mesh, face * 3 + 2)
        shared = i0 == vi or i0 == vj or i1 == vi or i1 == vj or i2 == vi or i2 == vj
        if not shared:
            t = _ray_tri_t(p0, dir, points[i0], points[i1], points[i2])
            if t >= 0.0 and t < best_t:
                best_t = t
                best = face
    return best


@wp.func
def _first_label(ref_label: wp.array(dtype=wp.int32), i0: int, i1: int, i2: int):
    if ref_label[i0] >= 0:
        return ref_label[i0]
    if ref_label[i1] >= 0:
        return ref_label[i1]
    return ref_label[i2]


@wp.kernel
def _survey_kernel(
    springs: wp.array(dtype=wp.int32),
    mesh: wp.uint64,
    points: wp.array(dtype=wp.vec3),
    ref_label: wp.array(dtype=wp.int32),
    allow_pairs: wp.array(dtype=wp.vec2i),
    n_pairs: int,
    flag_pierced: wp.array(dtype=wp.int32),
    flag_drag: wp.array(dtype=wp.int32),
    counter: wp.array(dtype=wp.int32),
):
    s = wp.tid()
    vi = springs[2 * s + 0]
    vj = springs[2 * s + 1]

    face = _segment_pierce_face(mesh, points, vi, vj)
    if face < 0:
        return

    flag_pierced[vi] = 1
    flag_pierced[vj] = 1
    wp.atomic_add(counter, 0, 1)

    face_label = _first_label(
        ref_label,
        wp.mesh_get_index(mesh, face * 3 + 0),
        wp.mesh_get_index(mesh, face * 3 + 1),
        wp.mesh_get_index(mesh, face * 3 + 2),
    )
    if face_label < 0:
        return

    edge_label = ref_label[vi]
    if edge_label < 0:
        edge_label = ref_label[vj]
    if edge_label == face_label:
        return

    for k in range(n_pairs):
        pair = allow_pairs[k]
        hit_fwd = pair[0] == face_label and pair[1] == edge_label
        hit_rev = pair[0] == edge_label and pair[1] == face_label
        if hit_fwd or hit_rev:
            flag_drag[vi] = 1
            flag_drag[vj] = 1


@wp.kernel
def _count_kernel(
    springs: wp.array(dtype=wp.int32),
    mesh: wp.uint64,
    points: wp.array(dtype=wp.vec3),
    counter: wp.array(dtype=wp.int32),
):
    s = wp.tid()
    if _segment_pierce_face(mesh, points, springs[2 * s + 0], springs[2 * s + 1]) >= 0:
        wp.atomic_add(counter, 0, 1)


@wp.kernel
def _detect_pt_kernel(
    x0: wp.array(dtype=wp.vec3),
    v0: wp.array(dtype=wp.vec3),
    mesh: wp.uint64,
    tri: wp.array(dtype=wp.int32),
    inv_mass: wp.array(dtype=wp.float32),
    radius: wp.array(dtype=wp.float32),
    gravity: wp.array(dtype=wp.vec3),
    flag_pierced: wp.array(dtype=wp.int32),
    dt: float,
    box_radii: float,
    band_radii: float,
    slots: int,
    pt_tri: wp.array(dtype=wp.int32),
    pt_side: wp.array(dtype=wp.int32),
    pt_filtered: wp.array(dtype=wp.uint8),
    pt_block_count: wp.array(dtype=wp.int32),
    overflow: wp.array(dtype=wp.int32),
):
    p = wp.tid()
    if flag_pierced[p] != 0:
        pt_block_count[p] = 0
        return

    r = radius[p]
    x = x0[p]
    h = box_radii * r
    ext = wp.vec3(h, h, h)
    g = gravity[0]
    dx_p = _predict_dx(v0[p], inv_mass[p], g, dt)
    band = band_radii * r
    base = p * slots

    query = wp.mesh_query_aabb(mesh, x - ext, x + ext)
    face = int(0)
    count = int(0)
    while wp.mesh_query_next(query, face):
        if count >= slots:
            wp.atomic_add(overflow, 0, 1)
            break
        slot = base + count
        i0 = tri[3 * face + 0]
        i1 = tri[3 * face + 1]
        i2 = tri[3 * face + 2]
        pt_tri[slot] = face
        pt_side[slot] = 0
        pt_filtered[slot] = wp.uint8(1)

        if i0 != p and i1 != p and i2 != p:
            a = x0[i0]
            b = x0[i1]
            c = x0[i2]
            ncr = wp.cross(b - a, c - a)
            nl = wp.length(ncr)
            if nl > _EPS:
                nrm = ncr / nl
                side = int(0)
                if wp.dot(nrm, x - a) < 0.0:
                    side = 1
                    nrm = -nrm
                pt_side[slot] = side

                w = _tri_bary(a, b, c, x)
                sep = (a * w[0] + b * w[1] + c * w[2]) - x
                dist = wp.length(sep)
                e = -nrm
                if dist > _EPS:
                    e = sep / dist
                dx_q = (
                    _predict_dx(v0[i0], inv_mass[i0], g, dt) * w[0]
                    + _predict_dx(v0[i1], inv_mass[i1], g, dt) * w[1]
                    + _predict_dx(v0[i2], inv_mass[i2], g, dt) * w[2]
                )
                if dist - wp.dot(dx_p, e) + wp.dot(dx_q, e) < band:
                    pt_filtered[slot] = wp.uint8(0)
        count += 1

    pt_block_count[p] = count


@wp.kernel
def _detect_ee_kernel(
    x0: wp.array(dtype=wp.vec3),
    v0: wp.array(dtype=wp.vec3),
    mesh: wp.uint64,
    tri: wp.array(dtype=wp.int32),
    springs: wp.array(dtype=wp.int32),
    inv_mass: wp.array(dtype=wp.float32),
    radius: wp.array(dtype=wp.float32),
    gravity: wp.array(dtype=wp.vec3),
    flag_pierced: wp.array(dtype=wp.int32),
    dt: float,
    box_radii: float,
    band_radii: float,
    slots: int,
    ee_other: wp.array2d(dtype=wp.int32),
    ee_dir: wp.array(dtype=wp.vec3),
    ee_filtered: wp.array(dtype=wp.uint8),
    ee_block_count: wp.array(dtype=wp.int32),
    overflow: wp.array(dtype=wp.int32),
):
    s = wp.tid()
    vi = springs[2 * s + 0]
    vj = springs[2 * s + 1]
    if flag_pierced[vi] != 0 or flag_pierced[vj] != 0:
        ee_block_count[s] = 0
        return

    r = wp.max(radius[vi], radius[vj])
    p0 = x0[vi]
    p1 = x0[vj]
    seg = p1 - p0
    elen = wp.length(seg)
    g = gravity[0]
    dx_i = _predict_dx(v0[vi], inv_mass[vi], g, dt)
    dx_j = _predict_dx(v0[vj], inv_mass[vj], g, dt)
    band = band_radii * r
    base = s * slots

    h = 0.5 * elen + box_radii * r
    ext = wp.vec3(h, h, h)
    mid = 0.5 * (p0 + p1)

    query = wp.mesh_query_aabb(mesh, mid - ext, mid + ext)
    face = int(0)
    count = int(0)
    full = int(0)
    while wp.mesh_query_next(query, face):
        for e in range(3):
            if full == 0:
                if count >= slots:
                    wp.atomic_add(overflow, 0, 1)
                    full = 1
                else:
                    slot = base + count
                    ia = tri[3 * face + e]
                    ib = tri[3 * face + ((e + 1) % 3)]
                    ee_other[slot, 0] = ia
                    ee_other[slot, 1] = ib
                    ee_dir[slot] = wp.vec3(0.0, 0.0, 0.0)
                    ee_filtered[slot] = wp.uint8(1)

                    if ia != vi and ia != vj and ib != vi and ib != vj:
                        # the shared edge of two faces is traversed in opposite order
                        dup = int(0)
                        for k in range(count):
                            if ee_other[base + k, 0] == ib and ee_other[base + k, 1] == ia:
                                dup = 1
                        if dup == 0 and elen > _EPS:
                            q0 = x0[ia]
                            q1 = x0[ib]
                            oseg = q1 - q0
                            st = _seg_seg(p0, p1, q0, q1)
                            sw = st[0]
                            tw = st[1]
                            # §10.3: all four products use the query edge's length
                            near_end = (
                                sw * elen < r
                                or (1.0 - sw) * elen < r
                                or tw * elen < r
                                or (1.0 - tw) * elen < r
                            )
                            if not near_end:
                                conn = (q0 + oseg * tw) - (p0 + seg * sw)
                                dist = wp.length(conn)
                                if dist > _EPS:
                                    dir = conn / dist
                                    dx_q = dx_i * (1.0 - sw) + dx_j * sw
                                    dx_o = _predict_dx(
                                        v0[ia], inv_mass[ia], g, dt
                                    ) * (1.0 - tw) + _predict_dx(
                                        v0[ib], inv_mass[ib], g, dt
                                    ) * tw
                                    if dist - wp.dot(dx_q, dir) + wp.dot(dx_o, dir) < band:
                                        ee_dir[slot] = dir
                                        ee_filtered[slot] = wp.uint8(0)
                    count += 1
        if full == 1:
            break

    ee_block_count[s] = count


@wp.kernel
def _solve_pt_kernel(
    x: wp.array(dtype=wp.vec3),
    tri: wp.array(dtype=wp.int32),
    inv_mass: wp.array(dtype=wp.float32),
    radius: wp.array(dtype=wp.float32),
    pt_tri: wp.array(dtype=wp.int32),
    pt_side: wp.array(dtype=wp.int32),
    pt_filtered: wp.array(dtype=wp.uint8),
    pt_block_count: wp.array(dtype=wp.int32),
    slots: int,
    relaxation: float,
    delta: wp.array(dtype=wp.vec3),
):
    p, k = wp.tid()
    if k >= pt_block_count[p]:
        return
    slot = p * slots + k
    if pt_filtered[slot] != wp.uint8(0):
        return

    wi = inv_mass[p]
    face = pt_tri[slot]
    i0 = tri[3 * face + 0]
    i1 = tri[3 * face + 1]
    i2 = tri[3 * face + 2]
    a = x[i0]
    b = x[i1]
    c = x[i2]
    ncr = wp.cross(b - a, c - a)
    nl = wp.length(ncr)
    if nl <= _EPS:
        return
    nrm = ncr / nl
    if pt_side[slot] != 0:
        nrm = -nrm

    xp = x[p]
    w = _tri_bary(a, b, c, xp)
    cval = wp.dot(xp - (a * w[0] + b * w[1] + c * w[2]), nrm) - 2.0 * radius[p]
    if cval >= 0.0:
        return

    # §10.2: the normal-variation gradients vanish, leaving particle and first vertex
    denom = wi + inv_mass[i0]
    if denom < _DENOM_EPS:
        return

    wp.atomic_add(delta, p, nrm * (-cval / denom * wi * relaxation))


@wp.kernel
def _solve_ee_kernel(
    x: wp.array(dtype=wp.vec3),
    springs: wp.array(dtype=wp.int32),
    inv_mass: wp.array(dtype=wp.float32),
    radius: wp.array(dtype=wp.float32),
    ee_other: wp.array2d(dtype=wp.int32),
    ee_dir: wp.array(dtype=wp.vec3),
    ee_filtered: wp.array(dtype=wp.uint8),
    ee_block_count: wp.array(dtype=wp.int32),
    slots: int,
    relaxation: float,
    delta: wp.array(dtype=wp.vec3),
):
    s, k = wp.tid()
    if k >= ee_block_count[s]:
        return
    slot = s * slots + k
    if ee_filtered[slot] != wp.uint8(0):
        return

    vi = springs[2 * s + 0]
    vj = springs[2 * s + 1]
    ia = ee_other[slot, 0]
    ib = ee_other[slot, 1]

    p0 = x[vi]
    p1 = x[vj]
    q0 = x[ia]
    q1 = x[ib]
    st = _seg_seg(p0, p1, q0, q1)
    sw = st[0]
    tw = st[1]
    conn = (q0 + (q1 - q0) * tw) - (p0 + (p1 - p0) * sw)
    dist = wp.length(conn)
    if dist <= _EPS:
        return
    dir = conn / dist
    if wp.dot(dir, ee_dir[slot]) < 0.0:
        dir = -dir

    cval = wp.dot(conn, dir) - 2.0 * wp.max(radius[vi], radius[vj])
    if cval >= 0.0:
        return

    wi = inv_mass[vi]
    wj = inv_mass[vj]
    gi = 1.0 - sw
    gj = sw
    ga = 1.0 - tw
    gb = tw
    denom = gi * gi * wi + gj * gj * wj + ga * ga * inv_mass[ia] + gb * gb * inv_mass[ib]
    if denom < _DENOM_EPS:
        return

    # four-body denominator, but only the query edge moves, along -e
    dlambda = -cval / denom * relaxation
    wp.atomic_add(delta, vi, dir * (-dlambda * wi * gi))
    wp.atomic_add(delta, vj, dir * (-dlambda * wj * gj))


class SelfContact:
    def __init__(self, ctx: Ctx, params: SimParams) -> None:
        self.ctx = ctx
        self.params = params
        self.pt_per_particle = int(params.pt_per_particle)
        self.ee_per_spring = int(params.ee_per_spring)
        self.n_particles = int(ctx.flag_pierced.shape[0])
        self.n_springs = int(ctx.springs.shape[0]) // 2
        self.device = ctx.springs.device

    def clear_flags(self) -> None:
        self.ctx.flag_pierced.zero_()
        self.ctx.flag_drag.zero_()
        self.ctx.counter_global_self.zero_()

    def piercing_survey(self) -> None:
        if self.n_springs == 0:
            return
        ctx = self.ctx
        wp.launch(
            _survey_kernel,
            dim=self.n_springs,
            inputs=[
                ctx.springs,
                ctx.cloth_mesh.id,
                ctx.cloth_mesh.points,
                ctx.ref_label,
                ctx.allow_pairs,
                int(ctx.n_pairs),
                ctx.flag_pierced,
                ctx.flag_drag,
                ctx.counter_global_self,
            ],
            device=self.device,
        )

    def detect_point_triangle(self, frame_dt: float) -> None:
        ctx = self.ctx
        wp.launch(
            _detect_pt_kernel,
            dim=self.n_particles,
            inputs=[
                ctx.x_frame0,
                ctx.v_frame0,
                ctx.cloth_mesh.id,
                ctx.cloth_tri_flat,
                ctx.model.particle_inv_mass,
                ctx.model.particle_radius,
                ctx.model.gravity,
                ctx.flag_pierced,
                float(frame_dt),
                float(self.params.pt_query_radii),
                float(self.params.detect_band_radii),
                self.pt_per_particle,
                ctx.pt_tri,
                ctx.pt_side,
                ctx.pt_filtered,
                ctx.pt_block_count,
                ctx.pt_overflow,
            ],
            device=self.device,
        )

    def detect_edge_edge(self, frame_dt: float) -> None:
        if self.n_springs == 0:
            return
        ctx = self.ctx
        wp.launch(
            _detect_ee_kernel,
            dim=self.n_springs,
            inputs=[
                ctx.x_frame0,
                ctx.v_frame0,
                ctx.cloth_mesh.id,
                ctx.cloth_tri_flat,
                ctx.springs,
                ctx.model.particle_inv_mass,
                ctx.model.particle_radius,
                ctx.model.gravity,
                ctx.flag_pierced,
                float(frame_dt),
                float(self.params.pt_query_radii),
                float(self.params.detect_band_radii),
                self.ee_per_spring,
                ctx.ee_other,
                ctx.ee_dir,
                ctx.ee_filtered,
                ctx.ee_block_count,
                ctx.ee_overflow,
            ],
            device=self.device,
        )

    def solve_point_triangle(self) -> None:
        ctx = self.ctx
        wp.launch(
            _solve_pt_kernel,
            dim=(self.n_particles, self.pt_per_particle),
            inputs=[
                ctx.state_out.particle_q,
                ctx.cloth_tri_flat,
                ctx.model.particle_inv_mass,
                ctx.model.particle_radius,
                ctx.pt_tri,
                ctx.pt_side,
                ctx.pt_filtered,
                ctx.pt_block_count,
                self.pt_per_particle,
                float(self.params.self_contact_relaxation),
                ctx.delta,
            ],
            device=self.device,
        )

    def solve_edge_edge(self) -> None:
        if self.n_springs == 0:
            return
        ctx = self.ctx
        wp.launch(
            _solve_ee_kernel,
            dim=(self.n_springs, self.ee_per_spring),
            inputs=[
                ctx.state_out.particle_q,
                ctx.springs,
                ctx.model.particle_inv_mass,
                ctx.model.particle_radius,
                ctx.ee_other,
                ctx.ee_dir,
                ctx.ee_filtered,
                ctx.ee_block_count,
                self.ee_per_spring,
                float(self.params.self_contact_relaxation),
                ctx.delta,
            ],
            device=self.device,
        )

    def count_self_intersections(self) -> int:
        ctx = self.ctx
        ctx.counter_self.zero_()
        if self.n_particles == 0 or self.n_springs == 0:
            return 0
        wp.launch(
            _count_kernel,
            dim=self.n_springs,
            inputs=[ctx.springs, ctx.cloth_mesh.id, ctx.cloth_mesh.points, ctx.counter_self],
            device=self.device,
        )
        return int(ctx.counter_self.numpy()[0])
