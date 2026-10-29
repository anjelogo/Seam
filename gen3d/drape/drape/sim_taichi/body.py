from dataclasses import dataclass
from typing import Final

import gstaichi as ti
import numpy as np


UNBOUNDED: Final = 1.0e6
FLAG_INSIDE_BODY: Final = 2
_ACTIVE: Final = 1
_SLIVER: Final = 1.0e-6
_SIGN_EPSILON: Final = 1.0e-3


@dataclass(frozen=True, slots=True)
class _BvhArrays:
    points: np.ndarray
    faces: np.ndarray
    node_lo: np.ndarray
    node_hi: np.ndarray
    node_skip: np.ndarray
    node_prim: np.ndarray
    roots: np.ndarray
    ends: np.ndarray
    face_offsets: np.ndarray
    average_edges: np.ndarray


def _mesh_nodes(points: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not len(faces):
        empty_vec = np.empty((0, 3), dtype=np.float32)
        empty_int = np.empty(0, dtype=np.int32)
        return empty_vec, empty_vec.copy(), empty_int, empty_int.copy()

    triangles = points[faces]
    centroids = triangles.mean(axis=1, dtype=np.float32)
    lowers: list[np.ndarray] = []
    uppers: list[np.ndarray] = []
    skips: list[int] = []
    prims: list[int] = []

    def build(face_ids: np.ndarray) -> None:
        index = len(lowers)
        bounds = triangles[face_ids].reshape(-1, 3)
        lowers.append(bounds.min(axis=0))
        uppers.append(bounds.max(axis=0))
        skips.append(0)
        prims.append(-1)
        if len(face_ids) == 1:
            prims[index] = int(face_ids[0])
        else:
            selected = centroids[face_ids]
            extent = selected.max(axis=0) - selected.min(axis=0)
            axis = int(np.argmax(extent))
            order = np.argsort(selected[:, axis], kind="stable")
            ordered = face_ids[order]
            middle = len(ordered) // 2
            build(ordered[:middle])
            build(ordered[middle:])
        skips[index] = len(lowers)

    build(np.arange(len(faces), dtype=np.int32))
    return (
        np.asarray(lowers, dtype=np.float32),
        np.asarray(uppers, dtype=np.float32),
        np.asarray(skips, dtype=np.int32),
        np.asarray(prims, dtype=np.int32),
    )


def _build_arrays(meshes: list[tuple[np.ndarray, np.ndarray]]) -> _BvhArrays:
    points_out: list[np.ndarray] = []
    faces_out: list[np.ndarray] = []
    node_lo_out: list[np.ndarray] = []
    node_hi_out: list[np.ndarray] = []
    node_skip_out: list[np.ndarray] = []
    node_prim_out: list[np.ndarray] = []
    roots = np.full(len(meshes), -1, dtype=np.int32)
    ends = np.full(len(meshes), -1, dtype=np.int32)
    face_offsets = np.zeros(len(meshes) + 1, dtype=np.int32)
    average_edges = np.zeros(len(meshes), dtype=np.float32)
    point_offset = 0
    face_offset = 0
    node_offset = 0

    for mesh_id, (points, faces) in enumerate(meshes):
        points_out.append(points)
        faces_out.append(faces + np.int32(point_offset))
        face_offsets[mesh_id] = face_offset
        if len(faces):
            edges = points[faces[:, [1, 2, 0]]] - points[faces]
            lengths = np.sqrt(np.sum(edges * edges, axis=2, dtype=np.float32))
            average_edges[mesh_id] = np.mean(lengths, dtype=np.float32)
            lo, hi, skip, prim = _mesh_nodes(points, faces)
            roots[mesh_id] = node_offset
            ends[mesh_id] = node_offset + len(prim)
            node_lo_out.append(lo)
            node_hi_out.append(hi)
            node_skip_out.append(skip + np.int32(node_offset))
            node_prim_out.append(np.where(prim >= 0, prim + np.int32(face_offset), prim).astype(np.int32))
            node_offset += len(prim)
        point_offset += len(points)
        face_offset += len(faces)

    face_offsets[-1] = face_offset
    return _BvhArrays(
        points=np.concatenate(points_out) if points_out else np.empty((0, 3), dtype=np.float32),
        faces=np.concatenate(faces_out) if faces_out else np.empty((0, 3), dtype=np.int32),
        node_lo=np.concatenate(node_lo_out) if node_lo_out else np.empty((0, 3), dtype=np.float32),
        node_hi=np.concatenate(node_hi_out) if node_hi_out else np.empty((0, 3), dtype=np.float32),
        node_skip=np.concatenate(node_skip_out) if node_skip_out else np.empty(0, dtype=np.int32),
        node_prim=np.concatenate(node_prim_out) if node_prim_out else np.empty(0, dtype=np.int32),
        roots=roots,
        ends=ends,
        face_offsets=face_offsets,
        average_edges=average_edges,
    )


# Closest-point and ray math adapted from Warp 1.18, Apache-2.0.
@ti.data_oriented
class FlatBvh:
    def __init__(self, meshes: list[tuple[np.ndarray, np.ndarray]]) -> None:
        self._points = [np.ascontiguousarray(points, dtype=np.float32) for points, _ in meshes]
        self._faces = [np.ascontiguousarray(faces, dtype=np.int32) for _, faces in meshes]
        arrays = _build_arrays(list(zip(self._points, self._faces, strict=True)))
        self.mesh_count = len(meshes)
        self.point_count = len(arrays.points)
        self.face_count = len(arrays.faces)
        self.node_count = len(arrays.node_prim)
        self.points = ti.Vector.field(3, dtype=ti.f32, shape=max(1, self.point_count))
        self.faces = ti.Vector.field(3, dtype=ti.i32, shape=max(1, self.face_count))
        self.node_lo = ti.Vector.field(3, dtype=ti.f32, shape=max(1, self.node_count))
        self.node_hi = ti.Vector.field(3, dtype=ti.f32, shape=max(1, self.node_count))
        self.node_skip = ti.field(dtype=ti.i32, shape=max(1, self.node_count))
        self.node_prim = ti.field(dtype=ti.i32, shape=max(1, self.node_count))
        self.roots = ti.field(dtype=ti.i32, shape=max(1, self.mesh_count))
        self.ends = ti.field(dtype=ti.i32, shape=max(1, self.mesh_count))
        self.face_offsets = ti.field(dtype=ti.i32, shape=max(1, self.mesh_count + 1))
        self.average_edges = ti.field(dtype=ti.f32, shape=max(1, self.mesh_count))
        self._upload(arrays)

    def _upload(self, arrays: _BvhArrays) -> None:
        points = np.zeros((max(1, self.point_count), 3), dtype=np.float32)
        faces = np.zeros((max(1, self.face_count), 3), dtype=np.int32)
        node_lo = np.zeros((max(1, self.node_count), 3), dtype=np.float32)
        node_hi = np.zeros((max(1, self.node_count), 3), dtype=np.float32)
        node_skip = np.zeros(max(1, self.node_count), dtype=np.int32)
        node_prim = np.full(max(1, self.node_count), -1, dtype=np.int32)
        roots = np.full(max(1, self.mesh_count), -1, dtype=np.int32)
        ends = np.full(max(1, self.mesh_count), -1, dtype=np.int32)
        face_offsets = np.zeros(max(1, self.mesh_count + 1), dtype=np.int32)
        average_edges = np.zeros(max(1, self.mesh_count), dtype=np.float32)
        points[: self.point_count] = arrays.points
        faces[: self.face_count] = arrays.faces
        node_lo[: self.node_count] = arrays.node_lo
        node_hi[: self.node_count] = arrays.node_hi
        node_skip[: self.node_count] = arrays.node_skip
        node_prim[: self.node_count] = arrays.node_prim
        roots[: self.mesh_count] = arrays.roots
        ends[: self.mesh_count] = arrays.ends
        face_offsets[: self.mesh_count + 1] = arrays.face_offsets
        average_edges[: self.mesh_count] = arrays.average_edges
        self.points.from_numpy(points)
        self.faces.from_numpy(faces)
        self.node_lo.from_numpy(node_lo)
        self.node_hi.from_numpy(node_hi)
        self.node_skip.from_numpy(node_skip)
        self.node_prim.from_numpy(node_prim)
        self.roots.from_numpy(roots)
        self.ends.from_numpy(ends)
        self.face_offsets.from_numpy(face_offsets)
        self.average_edges.from_numpy(average_edges)

    def replace_points(self, mesh: int, points: np.ndarray) -> None:
        self._points[mesh] = np.ascontiguousarray(points, dtype=np.float32)
        arrays = _build_arrays(list(zip(self._points, self._faces, strict=True)))
        if len(arrays.node_prim) != self.node_count:
            raise RuntimeError("BVH topology changed during point replacement")
        self._upload(arrays)

    @ti.func
    def _box_distance_sq(self, point, lower, upper):
        distance = ti.Vector.zero(ti.f32, 3)
        for axis in ti.static(range(3)):
            distance[axis] = ti.max(ti.max(lower[axis] - point[axis], point[axis] - upper[axis]), 0.0)
        return distance.dot(distance)

    @ti.func
    def _closest_barycentric(self, a, b, c, point):
        ab = b - a
        ac = c - a
        ap = point - a
        d1 = ab.dot(ap)
        d2 = ac.dot(ap)
        uv = ti.Vector([0.0, 0.0])
        if d1 <= 0.0 and d2 <= 0.0:
            uv = ti.Vector([1.0, 0.0])
        else:
            bp = point - b
            d3 = ab.dot(bp)
            d4 = ac.dot(bp)
            if d3 >= 0.0 and d4 <= d3:
                uv = ti.Vector([0.0, 1.0])
            else:
                vc = d1 * d4 - d3 * d2
                if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
                    v = d1 / (d1 - d3)
                    uv = ti.Vector([1.0 - v, v])
                else:
                    cp = point - c
                    d5 = ab.dot(cp)
                    d6 = ac.dot(cp)
                    if d6 >= 0.0 and d5 <= d6:
                        uv = ti.Vector([0.0, 0.0])
                    else:
                        vb = d5 * d2 - d1 * d6
                        if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
                            w = d2 / (d2 - d6)
                            uv = ti.Vector([1.0 - w, 0.0])
                        else:
                            va = d3 * d6 - d5 * d4
                            if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
                                w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
                                uv = ti.Vector([0.0, 1.0 - w])
                            else:
                                denominator = 1.0 / (va + vb + vc)
                                v = vb * denominator
                                w = vc * denominator
                                uv = ti.Vector([1.0 - v - w, v])
        return uv

    @ti.func
    def query_point_no_sign(self, mesh, point, max_dist):
        best_sq = max_dist * max_dist
        best_face = -1
        best_u = 0.0
        best_v = 0.0
        node = self.roots[mesh]
        end = self.ends[mesh]
        while node >= 0 and node < end:
            if self._box_distance_sq(point, self.node_lo[node], self.node_hi[node]) <= best_sq:
                primitive = self.node_prim[node]
                if primitive >= 0:
                    face = self.faces[primitive]
                    a = self.points[face[0]]
                    b = self.points[face[1]]
                    c = self.points[face[2]]
                    e0 = b - a
                    e1 = c - a
                    e2 = c - b
                    normal = e0.cross(e1)
                    if normal.norm() / (e0.dot(e0) + e1.dot(e1) + e2.dot(e2)) >= _SLIVER:
                        bary = self._closest_barycentric(a, b, c, point)
                        closest = a * bary[0] + b * bary[1] + c * (1.0 - bary[0] - bary[1])
                        distance_sq = (closest - point).dot(closest - point)
                        if distance_sq < best_sq:
                            best_sq = distance_sq
                            best_face = primitive
                            best_u = bary[0]
                            best_v = bary[1]
                    node = self.node_skip[node]
                else:
                    node += 1
            else:
                node = self.node_skip[node]
        hit = best_face >= 0 and best_sq < max_dist * max_dist
        local_face = best_face - self.face_offsets[mesh]
        return hit, local_face, best_u, best_v

    @ti.func
    def query_point_sign_normal(self, mesh, point, max_dist):
        best_dist = max_dist
        best_face = -1
        best_u = 0.0
        best_v = 0.0
        accumulated_normal = ti.Vector.zero(ti.f32, 3)
        epsilon = self.average_edges[mesh] * _SIGN_EPSILON
        epsilon_sq = epsilon * epsilon
        node = self.roots[mesh]
        end = self.ends[mesh]
        while node >= 0 and node < end:
            bound = best_dist + epsilon
            if self._box_distance_sq(point, self.node_lo[node], self.node_hi[node]) <= bound * bound:
                primitive = self.node_prim[node]
                if primitive >= 0:
                    face = self.faces[primitive]
                    a = self.points[face[0]]
                    b = self.points[face[1]]
                    c = self.points[face[2]]
                    e0 = b - a
                    e1 = c - a
                    e2 = c - b
                    normal = e0.cross(e1)
                    e0_sq = e0.dot(e0)
                    e1_sq = e1.dot(e1)
                    e2_sq = e2.dot(e2)
                    normal_length = normal.norm()
                    if normal_length / (e0_sq + e1_sq + e2_sq) >= _SLIVER:
                        bary = self._closest_barycentric(a, b, c, point)
                        closest = a * bary[0] + b * bary[1] + c * (1.0 - bary[0] - bary[1])
                        distance = (closest - point).norm()
                        if distance < best_dist + epsilon:
                            cp = closest - a
                            cq = closest - b
                            cr = closest - c
                            cp_sq = cp.dot(cp)
                            cq_sq = cq.dot(cq)
                            cr_sq = cr.dot(cr)
                            weight = 0.0
                            if cp_sq < epsilon_sq:
                                weight = ti.acos((e0 / ti.sqrt(e0_sq)).dot(e1 / ti.sqrt(e1_sq)))
                            elif cq_sq < epsilon_sq:
                                weight = ti.acos((e2 / ti.sqrt(e2_sq)).dot(-e0 / ti.sqrt(e0_sq)))
                            elif cr_sq < epsilon_sq:
                                weight = ti.acos((-e1 / ti.sqrt(e1_sq)).dot(-e2 / ti.sqrt(e2_sq)))
                            else:
                                e0cp = e0.dot(cp)
                                e2cq = e2.dot(cq)
                                e1cp = e1.dot(cp)
                                near_edge = (
                                    cp_sq * e0_sq - e0cp * e0cp < epsilon_sq * e0_sq
                                    or cq_sq * e2_sq - e2cq * e2cq < epsilon_sq * e2_sq
                                    or cp_sq * e1_sq - e1cp * e1cp < epsilon_sq * e1_sq
                                )
                                weight = ti.math.pi if near_edge else 2.0 * ti.math.pi
                            weighted = weight * normal / normal_length
                            if distance > best_dist - epsilon:
                                accumulated_normal += weighted
                                if distance < best_dist:
                                    best_dist = distance
                                    best_face = primitive
                                    best_u = bary[0]
                                    best_v = bary[1]
                            else:
                                best_dist = distance
                                best_face = primitive
                                best_u = bary[0]
                                best_v = bary[1]
                                accumulated_normal = weighted
                    node = self.node_skip[node]
                else:
                    node += 1
            else:
                node = self.node_skip[node]
        hit = best_face >= 0 and best_dist < max_dist
        sign = -1.0
        if hit:
            face = self.faces[best_face]
            closest = (
                self.points[face[0]] * best_u
                + self.points[face[1]] * best_v
                + self.points[face[2]] * (1.0 - best_u - best_v)
            )
            if accumulated_normal.dot(point - closest) > 0.0:
                sign = 1.0
        local_face = best_face - self.face_offsets[mesh]
        return hit, local_face, best_u, best_v, sign

    @ti.func
    def eval_position(self, mesh, face, u, v):
        primitive = self.face_offsets[mesh] + face
        indices = self.faces[primitive]
        return (
            self.points[indices[0]] * u
            + self.points[indices[1]] * v
            + self.points[indices[2]] * (1.0 - u - v)
        )

    @ti.func
    def _ray_box(self, start, direction, lower, upper, max_t):
        near = -1.0e30
        far = 1.0e30
        hit = True
        for axis in ti.static(range(3)):
            if direction[axis] == 0.0:
                if start[axis] < lower[axis] or start[axis] > upper[axis]:
                    hit = False
            else:
                first = (lower[axis] - start[axis]) / direction[axis]
                second = (upper[axis] - start[axis]) / direction[axis]
                near = ti.max(near, ti.min(first, second))
                far = ti.min(far, ti.max(first, second))
        return hit and far >= 0.0 and far >= near and near < max_t

    @ti.func
    def _ray_triangle(self, start, direction, a, b, c):
        kz = 0
        if ti.abs(direction[1]) > ti.abs(direction[kz]):
            kz = 1
        if ti.abs(direction[2]) > ti.abs(direction[kz]):
            kz = 2
        kx = kz + 1
        if kx == 3:
            kx = 0
        ky = kx + 1
        if ky == 3:
            ky = 0
        if direction[kz] < 0.0:
            swap = kx
            kx = ky
            ky = swap
        sx = direction[kx] / direction[kz]
        sy = direction[ky] / direction[kz]
        sz = 1.0 / direction[kz]
        aa = a - start
        bb = b - start
        cc = c - start
        ax = aa[kx] - sx * aa[kz]
        ay = aa[ky] - sy * aa[kz]
        bx = bb[kx] - sx * bb[kz]
        by = bb[ky] - sy * bb[kz]
        cx = cc[kx] - sx * cc[kz]
        cy = cc[ky] - sy * cc[kz]
        u_scaled = cx * by - cy * bx
        v_scaled = ax * cy - ay * cx
        w_scaled = bx * ay - by * ax
        mixed = (
            (u_scaled < 0.0 or v_scaled < 0.0 or w_scaled < 0.0)
            and (u_scaled > 0.0 or v_scaled > 0.0 or w_scaled > 0.0)
        )
        determinant = u_scaled + v_scaled + w_scaled
        hit = not mixed and determinant != 0.0
        ray_t = 0.0
        u = 0.0
        v = 0.0
        if hit:
            az = sz * aa[kz]
            bz = sz * bb[kz]
            cz = sz * cc[kz]
            scaled_t = u_scaled * az + v_scaled * bz + w_scaled * cz
            ray_t = scaled_t / determinant
            hit = ray_t >= 0.0
            u = u_scaled / determinant
            v = v_scaled / determinant
        return hit, ray_t, u, v, determinant

    @ti.func
    def query_ray(self, mesh, start, direction, max_t):
        best_t = max_t
        best_face = -1
        best_u = 0.0
        best_v = 0.0
        best_sign = 1.0
        node = self.roots[mesh]
        end = self.ends[mesh]
        while node >= 0 and node < end:
            if self._ray_box(start, direction, self.node_lo[node], self.node_hi[node], best_t):
                primitive = self.node_prim[node]
                if primitive >= 0:
                    face = self.faces[primitive]
                    hit, ray_t, u, v, sign = self._ray_triangle(
                        start, direction, self.points[face[0]], self.points[face[1]], self.points[face[2]]
                    )
                    if hit and ray_t < best_t:
                        best_t = ray_t
                        best_face = primitive
                        best_u = u
                        best_v = v
                        best_sign = sign
                    node = self.node_skip[node]
                else:
                    node += 1
            else:
                node = self.node_skip[node]
        local_face = best_face - self.face_offsets[mesh]
        return best_face >= 0, best_t, local_face, best_u, best_v, best_sign

    @ti.func
    def query_ray_anyhit(self, mesh, start, direction, max_t):
        found = False
        node = self.roots[mesh]
        end = self.ends[mesh]
        while node >= 0 and node < end and not found:
            if self._ray_box(start, direction, self.node_lo[node], self.node_hi[node], max_t):
                primitive = self.node_prim[node]
                if primitive >= 0:
                    face = self.faces[primitive]
                    hit, ray_t, _, _, _ = self._ray_triangle(
                        start, direction, self.points[face[0]], self.points[face[1]], self.points[face[2]]
                    )
                    found = hit and ray_t < max_t
                    node = self.node_skip[node]
                else:
                    node += 1
            else:
                node = self.node_skip[node]
        return found


@ti.data_oriented
class Body:
    def __init__(self, sim) -> None:
        self.sim = sim
        arrays = sim.scene.arrays
        settings = sim.scene.sim
        body_points = np.ascontiguousarray(arrays["body_v"], dtype=np.float32).reshape(-1, 3)
        body_faces = np.ascontiguousarray(arrays["body_f"], dtype=np.int32).reshape(-1, 3)
        ref_points = np.ascontiguousarray(arrays["ref_v"], dtype=np.float32).reshape(-1, 3)
        ref_faces = np.ascontiguousarray(arrays["ref_f"], dtype=np.int32).reshape(-1, 3)
        ref_v_off = np.asarray(arrays["ref_v_off"], dtype=np.int32)
        ref_f_off = np.asarray(arrays["ref_f_off"], dtype=np.int32)
        meshes = [(body_points, body_faces)]
        for part in range(len(ref_v_off) - 1):
            meshes.append(
                (
                    ref_points[ref_v_off[part] : ref_v_off[part + 1]],
                    ref_faces[ref_f_off[part] : ref_f_off[part + 1]],
                )
            )
        self.bvh = FlatBvh(meshes)
        self.body_vertex_count = len(body_points)
        self.contact_max = int(settings["soft_contact_max"])
        self.thickness = float(np.float32(settings["body_thickness"]))
        self.margin = float(np.float32(settings["soft_contact_margin"]))
        self.body_mu = float(np.float32(settings["body_mu"]))
        self.particle_mu = float(np.float32(settings["particle_mu"]))
        self.adhesion = float(np.float32(settings["particle_adhesion"]))
        self.relaxation = float(np.float32(settings["soft_contact_relaxation"]))
        capacity = max(1, self.contact_max)
        self.contact_count = ti.field(dtype=ti.i32, shape=1)
        self.contact_particle = ti.field(dtype=ti.i32, shape=capacity)
        self.contact_shape = ti.field(dtype=ti.i32, shape=capacity)
        self.contact_body_pos = ti.Vector.field(3, dtype=ti.f32, shape=capacity)
        self.contact_body_vel = ti.Vector.field(3, dtype=ti.f32, shape=capacity)
        self.contact_normal = ti.Vector.field(3, dtype=ti.f32, shape=capacity)
        self._overflow = ti.field(dtype=ti.i32, shape=1)
        self._counter = ti.field(dtype=ti.i32, shape=1)
        filters = np.ascontiguousarray(arrays["face_filters"], dtype=np.uint8)
        self.filter_count = filters.shape[0]
        self.face_filters = ti.field(
            dtype=ti.u8,
            shape=(max(1, self.filter_count), max(1, len(body_faces))),
        )
        padded_filters = np.zeros(self.face_filters.shape, dtype=np.uint8)
        padded_filters[: self.filter_count, : len(body_faces)] = filters
        self.face_filters.from_numpy(padded_filters)
        particle_filters = np.ascontiguousarray(arrays["particle_filter_id"], dtype=np.int32)
        self.particle_filter_id = ti.field(dtype=ti.i32, shape=max(1, sim.n))
        padded_particle_filters = np.full(max(1, sim.n), -1, dtype=np.int32)
        padded_particle_filters[: sim.n] = particle_filters
        self.particle_filter_id.from_numpy(padded_particle_filters)

    @ti.kernel
    def _generate(self):
        for particle in range(self.sim.n):
            self.sim.flag_drag[particle] = 0
            if self.sim.flags[particle] & _ACTIVE:
                point = self.sim.x_frame0[particle]
                hit, face, u, v, sign = self.bvh.query_point_sign_normal(0, point, UNBOUNDED)
                accepted = hit
                filter_id = self.particle_filter_id[particle]
                if accepted and filter_id >= 0 and self.face_filters[filter_id, face] != 0:
                    accepted = False
                if accepted:
                    surface = self.bvh.eval_position(0, face, u, v)
                    gap = point - surface
                    distance = gap.norm()
                    normal = ti.Vector.zero(ti.f32, 3)
                    if distance > 0.0:
                        normal = gap / distance * sign
                    signed_distance = distance * sign - self.thickness
                    if signed_distance > -self.margin and signed_distance < self.margin + self.sim.radius[particle]:
                        slot = ti.atomic_add(self.contact_count[0], 1)
                        if slot < self.contact_max:
                            self.contact_particle[slot] = particle
                            self.contact_shape[slot] = 0
                            self.contact_body_pos[slot] = surface + normal * self.thickness
                            self.contact_body_vel[slot] = ti.Vector.zero(ti.f32, 3)
                            self.contact_normal[slot] = normal
                        else:
                            ti.atomic_add(self._overflow[0], 1)
                    if signed_distance < -self.margin:
                        self.sim.flag_drag[particle] = FLAG_INSIDE_BODY

    @ti.func
    def _solve_slot(self, slot, dt):
        count = ti.min(self.contact_max, self.contact_count[0])
        if slot < count:
            particle = self.contact_particle[slot]
            if self.sim.flags[particle] & _ACTIVE:
                normal = self.contact_normal[slot]
                constraint = (
                    normal.dot(self.sim.x_out[particle] - self.contact_body_pos[slot])
                    - self.sim.radius[particle]
                )
                inverse_mass = self.sim.inv_mass[particle]
                if constraint <= self.adhesion and inverse_mass != 0.0:
                    mu = 0.5 * (self.particle_mu + self.body_mu)
                    velocity = self.sim.v_out[particle]
                    tangent = velocity - normal * normal.dot(velocity)
                    tangent_length = tangent.norm()
                    tangent_direction = ti.Vector.zero(ti.f32, 3)
                    if tangent_length > 0.0:
                        tangent_direction = tangent / tangent_length
                    normal_delta = normal * constraint
                    friction_delta = tangent_direction * ti.max(mu * constraint, -tangent_length * dt)
                    # No outer inverse-mass factor (§10.5).
                    correction = (friction_delta - normal_delta) / inverse_mass * self.relaxation
                    for axis in ti.static(range(3)):
                        ti.atomic_add(self.sim.delta[particle][axis], correction[axis])

    @ti.kernel
    def _solve(self, dt: ti.f32):
        for slot in range(self.contact_max):
            self._solve_slot(slot, dt)

    @ti.kernel
    def _count_intersections(self):
        for spring in range(self.sim.n_springs):
            endpoints = self.sim.springs[spring]
            start = self.sim.x_in[endpoints[0]]
            segment = self.sim.x_in[endpoints[1]] - start
            length = segment.norm()
            if length > 0.0 and self.bvh.query_ray_anyhit(0, start, segment / length, length):
                ti.atomic_add(self._counter[0], 1)

    def generate(self) -> None:
        self.contact_count.fill(0)
        self._generate()

    def solve(self, dt: float) -> None:
        self._solve(float(np.float32(dt)))

    def replace_points(self, verts_np: np.ndarray) -> None:
        points = np.ascontiguousarray(verts_np, dtype=np.float32).reshape(-1, 3)
        if len(points) != self.body_vertex_count:
            raise ValueError(f"expected {self.body_vertex_count} body vertices, got {len(points)}")
        self.bvh.replace_points(0, points)

    def count_intersections(self) -> int:
        self._counter.fill(0)
        self._count_intersections()
        return int(self._counter.to_numpy()[0])

    def overflow(self) -> int:
        return int(self._overflow.to_numpy()[0])
