import gstaichi as ti
import numpy as np

from .grid import TriangleGrid


_LINEAR_CELLS = 512
_EPS = 1.0e-6
_DENOM_EPS = 1.0e-5
_SEG_EPS = 1.0e-3


@ti.func
def _f32_barrier(value):
    return ti.bit_cast(ti.bit_cast(value, ti.u32), ti.f32)


@ti.func
def _split_f32(value):
    bits = ti.bit_cast(value, ti.u32)
    high = ti.bit_cast(bits & ti.u32(0xFFFFF000), ti.f32)
    return ti.Vector([high, value - high])


@ti.func
def _two_sum(a, b):
    total = a + b
    carry = total - a
    error = (a - (total - carry)) + (b - carry)
    return ti.Vector([total, error])


@ti.func
def _two_product(a, b):
    product = _f32_barrier(a * b)
    sa = _split_f32(a)
    sb = _split_f32(b)
    error = _f32_barrier(_f32_barrier(sa[0] * sb[0]) - product)
    error = _f32_barrier(error + _f32_barrier(sa[0] * sb[1]))
    error = _f32_barrier(error + _f32_barrier(sa[1] * sb[0]))
    error = _f32_barrier(error + _f32_barrier(sa[1] * sb[1]))
    return ti.Vector([product, error])


@ti.func
def _det_f32(a, b, c, d):
    left = _two_product(a, b)
    right = _two_product(c, d)
    head = _two_sum(left[0], -right[0])
    tail = _two_sum(left[1], -right[1])
    carry = _two_sum(head[1], tail[0])
    result = _two_sum(head[0], carry[0])
    error = _f32_barrier(tail[1] + carry[1] + result[1])
    return _f32_barrier(result[0] + error)


@ti.func
def _project_f32(value, scale, depth):
    product = _f32_barrier(scale * depth)
    return _f32_barrier(value - product)


@ti.func
def _length(value):
    return ti.sqrt(value.dot(value))


@ti.func
def _tri_bary(a, b, c, point):
    ab = b - a
    ac = c - a
    ap = point - a
    d1 = ab.dot(ap)
    d2 = ac.dot(ap)
    result = ti.Vector([0.0, 0.0, 0.0])
    done = ti.i32(0)

    if d1 <= 0.0 and d2 <= 0.0:
        result = ti.Vector([1.0, 0.0, 0.0])
        done = 1
    bp = point - b
    d3 = ab.dot(bp)
    d4 = ac.dot(bp)
    if done == 0 and d3 >= 0.0 and d4 <= d3:
        result = ti.Vector([0.0, 1.0, 0.0])
        done = 1
    vc = d1 * d4 - d3 * d2
    if done == 0 and vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        result = ti.Vector([1.0 - v, v, 0.0])
        done = 1

    cp = point - c
    d5 = ab.dot(cp)
    d6 = ac.dot(cp)
    if done == 0 and d6 >= 0.0 and d5 <= d6:
        result = ti.Vector([0.0, 0.0, 1.0])
        done = 1
    vb = d5 * d2 - d1 * d6
    if done == 0 and vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        result = ti.Vector([1.0 - w, 0.0, w])
        done = 1
    va = d3 * d6 - d5 * d4
    if done == 0 and va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        result = ti.Vector([0.0, 1.0 - w, w])
        done = 1
    if done == 0:
        denom = 1.0 / (va + vb + vc)
        v = vb * denom
        w = vc * denom
        result = ti.Vector([1.0 - v - w, v, w])
    return result


@ti.func
def _seg_seg(p0, p1, q0, q1):
    d1 = p1 - p0
    d2 = q1 - q0
    relative = p0 - q0
    a = d1.dot(d1)
    e = d2.dot(d2)
    f = d2.dot(relative)
    result = ti.Vector([0.0, 0.0])
    done = ti.i32(0)
    if a <= _SEG_EPS and e <= _SEG_EPS:
        done = 1
    if done == 0 and a <= _SEG_EPS:
        result = ti.Vector([0.0, ti.math.clamp(f / e, 0.0, 1.0)])
        done = 1
    c = d1.dot(relative)
    if done == 0 and e <= _SEG_EPS:
        result = ti.Vector([ti.math.clamp(-c / a, 0.0, 1.0), 0.0])
        done = 1
    if done == 0:
        b = d1.dot(d2)
        denom = a * e - b * b
        s = 0.0
        if denom != 0.0:
            s = ti.math.clamp((b * f - c * e) / denom, 0.0, 1.0)
        t = (b * s + f) / e
        if t < 0.0:
            result = ti.Vector([ti.math.clamp(-c / a, 0.0, 1.0), 0.0])
        elif t > 1.0:
            result = ti.Vector([ti.math.clamp((b - c) / a, 0.0, 1.0), 1.0])
        else:
            result = ti.Vector([s, t])
    return result


@ti.func
def _predict_dx(velocity, inv_mass, gravity, dt):
    return velocity * dt + gravity * (inv_mass * dt * dt)


@ti.func
def _ray_tri_t(origin, direction, a, b, c):
    kz = ti.i32(0)
    largest = ti.abs(direction[0])
    if ti.abs(direction[1]) > largest:
        kz = 1
        largest = ti.abs(direction[1])
    if ti.abs(direction[2]) > largest:
        kz = 2
    kx = (kz + 1) % 3
    ky = (kx + 1) % 3
    if direction[kz] < 0.0:
        swap = kx
        kx = ky
        ky = swap

    sx = direction[kx] / direction[kz]
    sy = direction[ky] / direction[kz]
    sz = 1.0 / direction[kz]
    va = a - origin
    vb = b - origin
    vc = c - origin
    ax = _project_f32(va[kx], sx, va[kz])
    ay = _project_f32(va[ky], sy, va[kz])
    bx = _project_f32(vb[kx], sx, vb[kz])
    by = _project_f32(vb[ky], sy, vb[kz])
    cx = _project_f32(vc[kx], sx, vc[kz])
    cy = _project_f32(vc[ky], sy, vc[kz])
    u = _det_f32(cx, by, cy, bx)
    v = _det_f32(ax, cy, ay, cx)
    w = _det_f32(bx, ay, by, ax)

    result = -1.0
    mixed = (u < 0.0 or v < 0.0 or w < 0.0) and (
        u > 0.0 or v > 0.0 or w > 0.0
    )
    det = u + v + w
    if not mixed and det != 0.0:
        tnum = (
            u * (sz * va[kz])
            + v * (sz * vb[kz])
            + w * (sz * vc[kz])
        )
        if not ((det > 0.0 and tnum < 0.0) or (det < 0.0 and tnum > 0.0)):
            result = tnum / det
    return result


def _edge_neighbours(faces: np.ndarray) -> np.ndarray:
    owner = {}
    for f, tri in enumerate(faces.tolist()):
        for e in range(3):
            owner.setdefault((tri[e], tri[(e + 1) % 3]), []).append(f)
    out = np.full(3 * len(faces), -1, dtype=np.int32)
    for f, tri in enumerate(faces.tolist()):
        for e in range(3):
            twins = owner.get((tri[(e + 1) % 3], tri[e]), [])
            if len(twins) == 1 and len(owner[(tri[e], tri[(e + 1) % 3])]) == 1:
                out[3 * f + e] = twins[0]
    return out


@ti.data_oriented
class SelfContact:
    def __init__(self, sim) -> None:
        self.sim = sim
        self.n = int(sim.n)
        self.n_faces = int(sim.n_faces)
        self.n_springs = int(sim.n_springs)
        params = sim.scene.sim
        self.pt_capacity = int(params["pt_per_particle"]) * self.n
        self.ee_capacity = int(params["ee_per_spring"]) * self.n_springs
        self.query_radii = float(np.float32(params["pt_query_radii"]))
        self.band_radii = float(np.float32(params["detect_band_radii"]))
        self.relaxation = float(np.float32(params["self_contact_relaxation"]))

        self.grid = TriangleGrid(sim)
        self.pt_owner = ti.field(ti.i32, shape=max(self.pt_capacity, 1))
        self.pt_tri = ti.field(ti.i32, shape=max(self.pt_capacity, 1))
        self.pt_side = ti.field(ti.i32, shape=max(self.pt_capacity, 1))
        self.pt_filtered = ti.field(ti.i32, shape=max(self.pt_capacity, 1))
        self.ee_owner = ti.field(ti.i32, shape=max(self.ee_capacity, 1))
        self.ee_other = ti.Vector.field(2, ti.i32, shape=max(self.ee_capacity, 1))
        self.ee_dir = ti.Vector.field(3, ti.f32, shape=max(self.ee_capacity, 1))
        self.ee_filtered = ti.field(ti.i32, shape=max(self.ee_capacity, 1))
        self.pt_count = ti.field(ti.i32, shape=1)
        self.ee_count = ti.field(ti.i32, shape=1)
        self.pt_overflow = ti.field(ti.i32, shape=1)
        self.ee_overflow = ti.field(ti.i32, shape=1)
        self.global_counter = ti.field(ti.i32, shape=1)
        self.intersection_counter = ti.field(ti.i32, shape=1)

        pairs = np.asarray(sim.scene.arrays["allow_pairs"], dtype=np.int32).reshape(-1, 2)
        self.n_pairs = len(pairs)
        self.allow_pairs = ti.Vector.field(2, ti.i32, shape=max(self.n_pairs, 1))
        if self.n_pairs:
            self.allow_pairs.from_numpy(pairs)
        self.edge_neighbour = ti.field(ti.i32, shape=max(3 * self.n_faces, 1))
        if self.n_faces:
            self.edge_neighbour.from_numpy(_edge_neighbours(np.asarray(sim.scene.arrays["faces"], dtype=np.int64)))
        self.pt_filtered.fill(1)
        self.ee_filtered.fill(1)

    @ti.func
    def _segment_pierce_face(self, vi, vj):
        p0 = self.sim.x_in[vi]
        p1 = self.sim.x_in[vj]
        segment = p1 - p0
        length = _length(segment)
        best = ti.i32(-1)
        best_t = length
        if length > _EPS:
            direction = segment / length
            query_lo = ti.min(p0, p1)
            query_hi = ti.max(p0, p1)
            cell_lo = self.grid.cell(query_lo)
            cell_hi = self.grid.cell(query_hi)
            for i, j, k in ti.ndrange(
                (cell_lo[0], cell_hi[0] + 1),
                (cell_lo[1], cell_hi[1] + 1),
                (cell_lo[2], cell_hi[2] + 1),
            ):
                cell = ti.Vector([i, j, k])
                for entry in range(self.grid.query_start(cell), self.grid.query_end(cell)):
                    if self.grid.accepts(entry, cell, query_lo, query_hi, cell_lo):
                        face = self.grid.entry_face[entry]
                        indices = self.sim.faces[face]
                        shared = (
                            indices[0] == vi
                            or indices[0] == vj
                            or indices[1] == vi
                            or indices[1] == vj
                            or indices[2] == vi
                            or indices[2] == vj
                        )
                        if not shared:
                            t = _ray_tri_t(
                                p0,
                                direction,
                                self.sim.x_in[indices[0]],
                                self.sim.x_in[indices[1]],
                                self.sim.x_in[indices[2]],
                            )
                            if t >= 0.0 and t < best_t:
                                best_t = t
                                best = face
        return best

    @ti.kernel
    def _survey(self):
        for spring in range(self.n_springs):
            edge = self.sim.springs[spring]
            vi = edge[0]
            vj = edge[1]
            face = self._segment_pierce_face(vi, vj)
            if face >= 0:
                self.sim.flag_pierced[vi] = 1
                self.sim.flag_pierced[vj] = 1
                ti.atomic_add(self.global_counter[0], 1)
                indices = self.sim.faces[face]
                face_label = self.sim.ref_label[indices[0]]
                if face_label < 0:
                    face_label = self.sim.ref_label[indices[1]]
                if face_label < 0:
                    face_label = self.sim.ref_label[indices[2]]
                if face_label >= 0:
                    edge_label = self.sim.ref_label[vi]
                    if edge_label < 0:
                        edge_label = self.sim.ref_label[vj]
                    if edge_label != face_label:
                        for pair_index in range(self.n_pairs):
                            pair = self.allow_pairs[pair_index]
                            if (
                                pair[0] == face_label and pair[1] == edge_label
                            ) or (
                                pair[0] == edge_label and pair[1] == face_label
                            ):
                                self.sim.flag_drag[vi] = 1
                                self.sim.flag_drag[vj] = 1

    @ti.kernel
    def _detect_pt(self, dt: ti.f32, box_radii: ti.f32, band_radii: ti.f32):
        for particle in range(self.n):
            if self.sim.flag_pierced[particle] == 0:
                radius = self.sim.radius[particle]
                point = self.sim.x_frame0[particle]
                extent = ti.Vector([1.0, 1.0, 1.0]) * (box_radii * radius)
                query_lo = point - extent
                query_hi = point + extent
                cell_lo = self.grid.cell(query_lo)
                cell_hi = self.grid.cell(query_hi)
                need = ti.i32(0)
                for i, j, k in ti.ndrange(
                    (cell_lo[0], cell_hi[0] + 1),
                    (cell_lo[1], cell_hi[1] + 1),
                    (cell_lo[2], cell_hi[2] + 1),
                ):
                    cell = ti.Vector([i, j, k])
                    for entry in range(self.grid.query_start(cell), self.grid.query_end(cell)):
                        if self.grid.accepts(entry, cell, query_lo, query_hi, cell_lo):
                            need += 1
                if need > 0:
                    base = ti.atomic_add(self.pt_count[0], need)
                    if base + need > self.pt_capacity:
                        ti.atomic_add(self.pt_overflow[0], 1)
                        for slot in range(self.pt_capacity):
                            if slot >= base:
                                self.pt_filtered[slot] = 1
                    else:
                        gravity = self.sim.gravity[0]
                        dx_particle = _predict_dx(
                            self.sim.v_frame0[particle],
                            self.sim.inv_mass[particle],
                            gravity,
                            dt,
                        )
                        band = band_radii * radius
                        count = ti.i32(0)
                        for i, j, k in ti.ndrange(
                            (cell_lo[0], cell_hi[0] + 1),
                            (cell_lo[1], cell_hi[1] + 1),
                            (cell_lo[2], cell_hi[2] + 1),
                        ):
                            cell = ti.Vector([i, j, k])
                            for entry in range(
                                self.grid.query_start(cell), self.grid.query_end(cell)
                            ):
                                if self.grid.accepts(
                                    entry, cell, query_lo, query_hi, cell_lo
                                ):
                                    slot = base + count
                                    face = self.grid.entry_face[entry]
                                    indices = self.sim.faces[face]
                                    self.pt_owner[slot] = particle
                                    self.pt_tri[slot] = face
                                    self.pt_side[slot] = 0
                                    self.pt_filtered[slot] = 1
                                    if (
                                        indices[0] != particle
                                        and indices[1] != particle
                                        and indices[2] != particle
                                    ):
                                        a = self.sim.x_frame0[indices[0]]
                                        b = self.sim.x_frame0[indices[1]]
                                        c = self.sim.x_frame0[indices[2]]
                                        cross = (b - a).cross(c - a)
                                        normal_length = _length(cross)
                                        if normal_length > _EPS:
                                            normal = cross / normal_length
                                            if normal.dot(point - a) < 0.0:
                                                self.pt_side[slot] = 1
                                                normal = -normal
                                            weights = _tri_bary(a, b, c, point)
                                            separation = (
                                                a * weights[0]
                                                + b * weights[1]
                                                + c * weights[2]
                                                - point
                                            )
                                            distance = _length(separation)
                                            direction = -normal
                                            if distance > _EPS:
                                                direction = separation / distance
                                            dx_triangle = (
                                                _predict_dx(
                                                    self.sim.v_frame0[indices[0]],
                                                    self.sim.inv_mass[indices[0]],
                                                    gravity,
                                                    dt,
                                                )
                                                * weights[0]
                                                + _predict_dx(
                                                    self.sim.v_frame0[indices[1]],
                                                    self.sim.inv_mass[indices[1]],
                                                    gravity,
                                                    dt,
                                                )
                                                * weights[1]
                                                + _predict_dx(
                                                    self.sim.v_frame0[indices[2]],
                                                    self.sim.inv_mass[indices[2]],
                                                    gravity,
                                                    dt,
                                                )
                                                * weights[2]
                                            )
                                            if (
                                                distance
                                                - dx_particle.dot(direction)
                                                + dx_triangle.dot(direction)
                                                < band
                                            ):
                                                self.pt_filtered[slot] = 0
                                    count += 1

    @ti.func
    def _box_overlaps(self, face, query_lo, query_hi):
        lo = self.grid.tri_lo[face]
        hi = self.grid.tri_hi[face]
        return (
            lo[0] <= query_hi[0] and lo[1] <= query_hi[1] and lo[2] <= query_hi[2]
            and hi[0] >= query_lo[0] and hi[1] >= query_lo[1] and hi[2] >= query_lo[2]
        )

    @ti.func
    def _ee_face(self, spring, face, base, count, vi, vj, p0, p1, edge_length, radius, band,
                 dx_i, dx_j, gravity, dt, query_lo, query_hi):
        segment = p1 - p0
        indices = self.sim.faces[face]
        for local_edge in ti.static(range(3)):
            slot = base + count + local_edge
            ia = indices[local_edge]
            ib = indices[(local_edge + 1) % 3]
            self.ee_owner[slot] = spring
            self.ee_other[slot] = ti.Vector([ia, ib])
            self.ee_dir[slot] = ti.Vector([0.0, 0.0, 0.0])
            self.ee_filtered[slot] = 1
            if ia != vi and ia != vj and ib != vi and ib != vj:
                # the reversed edge lives on the neighbour face; keep the lower face's copy
                duplicate = ti.i32(0)
                neighbour = self.edge_neighbour[face * 3 + local_edge]
                if neighbour >= 0 and neighbour < face:
                    if self._box_overlaps(neighbour, query_lo, query_hi):
                        duplicate = 1
                if duplicate == 0 and edge_length > _EPS:
                    q0 = self.sim.x_frame0[ia]
                    q1 = self.sim.x_frame0[ib]
                    weights = _seg_seg(p0, p1, q0, q1)
                    sw = weights[0]
                    tw = weights[1]
                    near_end = (
                        sw * edge_length < radius
                        or (1.0 - sw) * edge_length < radius
                        or tw * edge_length < radius
                        or (1.0 - tw) * edge_length < radius
                    )
                    if not near_end:
                        connection = (q0 + (q1 - q0) * tw) - (p0 + segment * sw)
                        distance = _length(connection)
                        if distance > _EPS:
                            direction = connection / distance
                            dx_query = dx_i * (1.0 - sw) + dx_j * sw
                            dx_other = _predict_dx(
                                self.sim.v_frame0[ia], self.sim.inv_mass[ia], gravity, dt
                            ) * (1.0 - tw) + _predict_dx(
                                self.sim.v_frame0[ib], self.sim.inv_mass[ib], gravity, dt
                            ) * tw
                            if distance - dx_query.dot(direction) + dx_other.dot(direction) < band:
                                self.ee_dir[slot] = direction
                                self.ee_filtered[slot] = 0
        return count + 3

    @ti.kernel
    def _detect_ee(self, dt: ti.f32, box_radii: ti.f32, band_radii: ti.f32):
        for spring in range(self.n_springs):
            edge = self.sim.springs[spring]
            vi = edge[0]
            vj = edge[1]
            if self.sim.flag_pierced[vi] == 0 and self.sim.flag_pierced[vj] == 0:
                radius = ti.max(self.sim.radius[vi], self.sim.radius[vj])
                p0 = self.sim.x_frame0[vi]
                p1 = self.sim.x_frame0[vj]
                edge_length = _length(p1 - p0)
                extent = ti.Vector([1.0, 1.0, 1.0]) * (0.5 * edge_length + box_radii * radius)
                midpoint = 0.5 * (p0 + p1)
                query_lo = midpoint - extent
                query_hi = midpoint + extent
                cell_lo = self.grid.cell(query_lo)
                cell_hi = self.grid.cell(query_hi)
                span = cell_hi - cell_lo + 1
                # long open-seam springs at the start span thousands of cells; a face scan is cheaper there
                linear = span[0] * span[1] * span[2] > _LINEAR_CELLS
                need = ti.i32(0)
                if linear:
                    for face in range(self.n_faces):
                        if self._box_overlaps(face, query_lo, query_hi):
                            need += 3
                else:
                    for i, j, k in ti.ndrange(
                        (cell_lo[0], cell_hi[0] + 1), (cell_lo[1], cell_hi[1] + 1), (cell_lo[2], cell_hi[2] + 1)
                    ):
                        cell = ti.Vector([i, j, k])
                        for entry in range(self.grid.query_start(cell), self.grid.query_end(cell)):
                            if self.grid.accepts(entry, cell, query_lo, query_hi, cell_lo):
                                need += 3
                if need > 0:
                    base = ti.atomic_add(self.ee_count[0], need)
                    if base + need > self.ee_capacity:
                        ti.atomic_add(self.ee_overflow[0], 1)
                        for slot in range(self.ee_capacity):
                            if slot >= base:
                                self.ee_filtered[slot] = 1
                    else:
                        gravity = self.sim.gravity[0]
                        dx_i = _predict_dx(self.sim.v_frame0[vi], self.sim.inv_mass[vi], gravity, dt)
                        dx_j = _predict_dx(self.sim.v_frame0[vj], self.sim.inv_mass[vj], gravity, dt)
                        band = band_radii * radius
                        count = ti.i32(0)
                        if linear:
                            for face in range(self.n_faces):
                                if self._box_overlaps(face, query_lo, query_hi):
                                    count = self._ee_face(spring, face, base, count, vi, vj, p0, p1, edge_length,
                                                          radius, band, dx_i, dx_j, gravity, dt, query_lo, query_hi)
                        else:
                            for i, j, k in ti.ndrange(
                                (cell_lo[0], cell_hi[0] + 1), (cell_lo[1], cell_hi[1] + 1), (cell_lo[2], cell_hi[2] + 1)
                            ):
                                cell = ti.Vector([i, j, k])
                                for entry in range(self.grid.query_start(cell), self.grid.query_end(cell)):
                                    if self.grid.accepts(entry, cell, query_lo, query_hi, cell_lo):
                                        count = self._ee_face(spring, self.grid.entry_face[entry], base, count, vi, vj,
                                                              p0, p1, edge_length, radius, band, dx_i, dx_j, gravity,
                                                              dt, query_lo, query_hi)

    @ti.func
    def _solve_pt_slot(self, slot, relaxation):
        if slot < ti.min(self.pt_count[0], self.pt_capacity):
            if self.pt_filtered[slot] == 0:
                particle = self.pt_owner[slot]
                face = self.pt_tri[slot]
                indices = self.sim.faces[face]
                a = self.sim.x_out[indices[0]]
                b = self.sim.x_out[indices[1]]
                c = self.sim.x_out[indices[2]]
                cross = (b - a).cross(c - a)
                normal_length = _length(cross)
                if normal_length > _EPS:
                    normal = cross / normal_length
                    if self.pt_side[slot] != 0:
                        normal = -normal
                    point = self.sim.x_out[particle]
                    weights = _tri_bary(a, b, c, point)
                    closest = a * weights[0] + b * weights[1] + c * weights[2]
                    constraint = normal.dot(point - closest) - 2.0 * self.sim.radius[particle]
                    if constraint < 0.0:
                        inv_mass = self.sim.inv_mass[particle]
                        denom = inv_mass + self.sim.inv_mass[indices[0]]
                        if denom >= _DENOM_EPS:
                            correction = normal * (
                                -constraint / denom * inv_mass * relaxation
                            )
                            for axis in ti.static(range(3)):
                                ti.atomic_add(
                                    self.sim.delta[particle][axis], correction[axis]
                                )

    @ti.kernel
    def _solve_pt(self, relaxation: ti.f32):
        for slot in range(self.pt_capacity):
            self._solve_pt_slot(slot, relaxation)

    @ti.func
    def _solve_ee_slot(self, slot, relaxation):
        if slot < ti.min(self.ee_count[0], self.ee_capacity):
            if self.ee_filtered[slot] == 0:
                spring = self.ee_owner[slot]
                edge = self.sim.springs[spring]
                vi = edge[0]
                vj = edge[1]
                other = self.ee_other[slot]
                ia = other[0]
                ib = other[1]
                p0 = self.sim.x_out[vi]
                p1 = self.sim.x_out[vj]
                q0 = self.sim.x_out[ia]
                q1 = self.sim.x_out[ib]
                weights = _seg_seg(p0, p1, q0, q1)
                sw = weights[0]
                tw = weights[1]
                connection = (q0 + (q1 - q0) * tw) - (p0 + (p1 - p0) * sw)
                distance = _length(connection)
                if distance > _EPS:
                    direction = connection / distance
                    if direction.dot(self.ee_dir[slot]) < 0.0:
                        direction = -direction
                    radius = ti.max(self.sim.radius[vi], self.sim.radius[vj])
                    constraint = connection.dot(direction) - 2.0 * radius
                    if constraint < 0.0:
                        wi = self.sim.inv_mass[vi]
                        wj = self.sim.inv_mass[vj]
                        gi = 1.0 - sw
                        gj = sw
                        ga = 1.0 - tw
                        gb = tw
                        denom = (
                            gi * gi * wi
                            + gj * gj * wj
                            + ga * ga * self.sim.inv_mass[ia]
                            + gb * gb * self.sim.inv_mass[ib]
                        )
                        if denom >= _DENOM_EPS:
                            multiplier = -constraint / denom * relaxation
                            correction_i = direction * (-multiplier * wi * gi)
                            correction_j = direction * (-multiplier * wj * gj)
                            for axis in ti.static(range(3)):
                                ti.atomic_add(self.sim.delta[vi][axis], correction_i[axis])
                                ti.atomic_add(self.sim.delta[vj][axis], correction_j[axis])

    @ti.kernel
    def _solve_ee(self, relaxation: ti.f32):
        for slot in range(self.ee_capacity):
            self._solve_ee_slot(slot, relaxation)

    @ti.kernel
    def _count_intersections(self):
        for spring in range(self.n_springs):
            edge = self.sim.springs[spring]
            if self._segment_pierce_face(edge[0], edge[1]) >= 0:
                ti.atomic_add(self.intersection_counter[0], 1)

    def clear_flags(self) -> None:
        self.sim.flag_pierced.fill(0)
        self.sim.flag_drag.fill(0)
        self.global_counter.fill(0)

    def rebuild(self) -> None:
        self.grid.rebuild()

    def piercing_survey(self) -> None:
        if self.n_springs:
            self._survey()

    def detect_edge_edge(self, dt: float) -> None:
        if self.n_springs:
            self.ee_count.fill(0)
            self._detect_ee(float(np.float32(dt)), self.query_radii, self.band_radii)

    def detect_point_triangle(self, dt: float) -> None:
        self.pt_count.fill(0)
        self._detect_pt(float(np.float32(dt)), self.query_radii, self.band_radii)

    def solve_point_triangle(self) -> None:
        self._solve_pt(self.relaxation)

    def solve_edge_edge(self) -> None:
        if self.n_springs:
            self._solve_ee(self.relaxation)

    def count_intersections(self) -> int:
        if self.n == 0 or self.n_springs == 0:
            return 0
        self.rebuild()
        self.intersection_counter.fill(0)
        self._count_intersections()
        return int(self.intersection_counter.to_numpy()[0])

    def overflow(self) -> dict[str, int]:
        return {
            "point_triangle": int(self.pt_overflow.to_numpy()[0]),
            "edge_edge": int(self.ee_overflow.to_numpy()[0]),
        }
