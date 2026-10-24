import dataclasses
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import newton
import numpy as np
import warp as wp


class StitchGeometryError(RuntimeError):
    """Stitching geometry could not be built; the frame loop tags this gt_edges_creation."""


@dataclasses.dataclass(frozen=True)
class SimParams:
    substeps: int = 10                    # §1.4
    iterations: int = 1                   # §1.5, must stay 1
    soft_contact_relaxation: float = 0.9  # §1.5
    self_contact_relaxation: float = 1.0  # §4.7, hard projection
    soft_contact_max: int = 65536         # §6.27
    ee_per_spring: int = 192              # §6.27
    pt_per_particle: int = 64             # §6.27
    pt_query_radii: float = 3.0           # §4.7, box half-extent = 3 * radius
    detect_band_radii: float = 2.5        # §4.7, 2r + 0.5r
    whole_body_shape_index: int = 0       # §3.2, §6.14
    gravity_on: tuple[float, float, float] = (0.0, -9.81, 0.0)  # §1.3
    ray_axes: tuple = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))  # §4.3 three-ray vote


@dataclasses.dataclass
class ClothData:
    verts: np.ndarray                 # (V,3) cm, post Y-shift
    faces: np.ndarray                 # (F,3)
    stitch_set: frozenset
    labels: dict[str, list[int]]
    panel_of_vertex: list[str | None]
    panel_pref_label: dict[str, str]
    vertex_labels: dict[str, list[int]]
    measurements: dict[str, float]
    body_verts: np.ndarray            # (B,3) cm, x100 then Y-shift
    body_faces: np.ndarray            # (Bf,3)
    body_seg: dict[str, list[int]]
    y_shift: float
    boxmesh_obj_path: Path
    orig_lens: dict = dataclasses.field(default_factory=dict, repr=False)
    # filled by add_cloth_sewing
    springs: np.ndarray | None = None
    spring_rest: np.ndarray | None = None
    edges: np.ndarray | None = None
    tri_rest_pose: np.ndarray | None = None
    tri_rest_area: np.ndarray | None = None
    particle_mass: np.ndarray | None = None

    def rest_length(self, i: int, j: int) -> float | None:
        v = self.orig_lens.get((int(i), int(j)))
        if v is None:
            v = self.orig_lens.get((int(j), int(i)))
        return None if v is None else float(v)


class Ctx:
    def __init__(self, model: "newton.Model", cloth: ClothData, config, params: SimParams):
        dev = model.device
        v = model.particle_count
        s = model.spring_count
        e = model.edge_count
        f = len(cloth.faces)
        bf = len(cloth.body_faces)

        self.model = model
        self.state_in = model.state()
        self.state_out = model.state()
        self.control = model.control()
        self.shape_index_body = params.whole_body_shape_index

        self.delta = wp.zeros(v, dtype=wp.vec3, device=dev)
        self.x_tmp = wp.zeros(v, dtype=wp.vec3, device=dev)
        self.x_frame0 = wp.zeros(v, dtype=wp.vec3, device=dev)
        self.v_frame0 = wp.zeros(v, dtype=wp.vec3, device=dev)
        self.lambda_spring = wp.zeros(s, dtype=wp.float32, device=dev)
        self.lambda_bend = wp.zeros(e, dtype=wp.float32, device=dev)
        self.body_delta = wp.zeros(1, dtype=wp.spatial_vector, device=dev)

        self.cloth_tri_flat = wp.array(
            np.ascontiguousarray(cloth.faces, dtype=np.int32).reshape(-1), dtype=wp.int32, device=dev
        )
        self.cloth_mesh = wp.Mesh(
            points=wp.clone(model.particle_q), indices=self.cloth_tri_flat
        )
        self.springs = model.spring_indices
        self.edges2d = model.edge_indices
        self.edge_rest = model.edge_rest_angle
        self.edge_props = model.edge_bending_properties

        n_soft = params.soft_contact_max
        self.soft_contact_count = wp.zeros(1, dtype=wp.int32, device=dev)
        self.soft_contact_particle = wp.zeros(n_soft, dtype=wp.int32, device=dev)
        self.soft_contact_shape = wp.zeros(n_soft, dtype=wp.int32, device=dev)
        self.soft_contact_body_pos = wp.zeros(n_soft, dtype=wp.vec3, device=dev)
        self.soft_contact_body_vel = wp.zeros(n_soft, dtype=wp.vec3, device=dev)
        self.soft_contact_normal = wp.zeros(n_soft, dtype=wp.vec3, device=dev)
        self.soft_contact_overflow = wp.zeros(1, dtype=wp.int32, device=dev)
        self.body_mesh: wp.Mesh | None = None
        self.face_filters = wp.zeros((1, bf), dtype=wp.uint8, device=dev)
        self.particle_filter_id = wp.full(v, -1, dtype=wp.int32, device=dev)
        self.body_thickness = float(config.body_thickness)

        n_pt = params.pt_per_particle * v
        n_ee = params.ee_per_spring * s
        self.flag_pierced = wp.zeros(v, dtype=wp.int32, device=dev)
        self.flag_drag = wp.zeros(v, dtype=wp.int32, device=dev)
        self.pt_block_count = wp.zeros(v, dtype=wp.int32, device=dev)
        self.pt_tri = wp.zeros(n_pt, dtype=wp.int32, device=dev)
        self.pt_side = wp.zeros(n_pt, dtype=wp.int32, device=dev)
        self.pt_filtered = wp.zeros(n_pt, dtype=wp.uint8, device=dev)
        self.ee_block_count = wp.zeros(s, dtype=wp.int32, device=dev)
        self.ee_other = wp.zeros((n_ee, 2), dtype=wp.int32, device=dev)
        self.ee_dir = wp.zeros(n_ee, dtype=wp.vec3, device=dev)
        self.ee_filtered = wp.zeros(n_ee, dtype=wp.uint8, device=dev)
        self.counter_global_self = wp.zeros(1, dtype=wp.int32, device=dev)
        self.counter_self = wp.zeros(1, dtype=wp.int32, device=dev)
        self.counter_body = wp.zeros(1, dtype=wp.int32, device=dev)
        self.pt_overflow = wp.zeros(1, dtype=wp.int32, device=dev)
        self.ee_overflow = wp.zeros(1, dtype=wp.int32, device=dev)

        self.ref_label = wp.full(v, -1, dtype=wp.int32, device=dev)
        self.ref_mesh_ids = wp.zeros(0, dtype=wp.uint64, device=dev)
        self.ref_meshes: list[wp.Mesh] = []
        self.allow_pairs = wp.zeros(0, dtype=wp.vec2i, device=dev)
        self.n_pairs = 0
        self.ref_margin = float(config.cloth_reference_margin)

        self.att_particle = wp.zeros(0, dtype=wp.int32, device=dev)
        self.att_point = wp.zeros(0, dtype=wp.vec3, device=dev)
        self.att_normal = wp.zeros(0, dtype=wp.vec3, device=dev)
        self.att_stiffness = wp.zeros(0, dtype=wp.float32, device=dev)
        self.att_damping = wp.zeros(0, dtype=wp.float32, device=dev)
        self.att_lambda = wp.zeros(0, dtype=wp.float32, device=dev)

        self.attachment_constraint = bool(config.enable_attachment_constraint)
        self.cloth_reference_drag = bool(config.enable_cloth_reference_drag)
        self.global_collision_filter = bool(config.enable_global_collision_filter)  # §6.23
        self.enable_triangle_particle_collisions = bool(config.enable_triangle_particle_collisions)
        self.enable_edge_edge_collisions = bool(config.enable_edge_edge_collisions)
        self.enable_particle_particle_collisions = bool(config.enable_particle_particle_collisions)
        if self.enable_particle_particle_collisions:
            raise NotImplementedError("particle-particle collisions are not supported (SIM_SPEC §6.18)")
        self.ground = bool(config.ground)
        self.particle_max_velocity = float(config.global_max_velocity)
        self.global_viscous_damping = (
            float(config.global_damping_factor),
            float(config.global_damping_effective_velocity),
            float(config.global_max_velocity),
        )
        self.n_faces = f


@dataclasses.dataclass
class Components:
    body: Any
    self_contact: Any
    attach: Any
    drag: Any
    integrate: Callable[[Ctx, float], None]
    smoother: Any | None = None


def _interior_edges(faces: np.ndarray) -> np.ndarray:
    """Bending elements over interior edges only: (i_opp, j_opp, k, l) per face winding."""
    incident: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    order: list[tuple[int, int]] = []
    for a, b, c in faces:
        for u, w, opp in ((a, b, c), (b, c, a), (c, a, b)):
            key = (u, w) if u < w else (w, u)
            if key not in incident:
                order.append(key)
            incident[key].append((int(u), int(w), int(opp)))
    out = []
    non_manifold = 0
    for key in order:
        rows = incident[key]
        if len(rows) != 2:
            if len(rows) > 2:
                non_manifold += 1
            continue
        k, l, i = rows[0]
        j = rows[1][2]
        out.append((i, j, k, l))
    if non_manifold:
        print(f"skipped {non_manifold} non-manifold edges")
    return np.asarray(out, dtype=np.int32).reshape(-1, 4)


def _springs_from_edges(edges: np.ndarray) -> np.ndarray:
    """§3.3: five pairs per bending element, deduplicated over the whole garment."""
    seen: set[tuple[int, int]] = set()
    out = []
    for i, j, k, l in edges:
        for a, b in ((i, k), (i, l), (j, k), (j, l), (k, l)):
            key = (int(a), int(b)) if a < b else (int(b), int(a))
            if key in seen:
                continue
            seen.add(key)
            out.append((int(a), int(b)))
    return np.asarray(out, dtype=np.int32).reshape(-1, 2)


def _flat_rest_pose(a: float, b: float, c: float) -> tuple[np.ndarray, float]:
    """Rest basis and area of the flat triangle with sides a=|pq|, b=|pr|, c=|qr|."""
    if a <= 0.0 or b <= 0.0 or c <= 0.0:
        raise StitchGeometryError(f"non-positive stitch rest length ({a}, {b}, {c})")
    x = (a * a + b * b - c * c) / (2.0 * a)
    y2 = b * b - x * x
    if y2 <= 0.0:
        raise StitchGeometryError(f"stitch rest lengths violate the triangle inequality ({a}, {b}, {c})")
    y = float(np.sqrt(y2))
    d = np.array(((a, x), (0.0, y)), dtype=np.float64)
    return np.linalg.inv(d), 0.5 * a * y


def add_cloth_sewing(builder: "newton.ModelBuilder", cloth: ClothData, config) -> None:
    verts = np.asarray(cloth.verts, dtype=np.float64)
    faces = np.ascontiguousarray(cloth.faces, dtype=np.int32)
    n_v, n_f = len(verts), len(faces)
    if faces.size and (faces.max() >= n_v or faces.min() < 0):
        raise StitchGeometryError("cloth face references a vertex outside the box mesh")
    if cloth.stitch_set and max(cloth.stitch_set) >= n_v:
        raise StitchGeometryError("stitching vertex set references a vertex outside the box mesh")

    radius = float(config.garment_radius)
    p_start = builder.particle_count
    for p in verts:
        builder.add_particle(pos=(float(p[0]), float(p[1]), float(p[2])), vel=(0.0, 0.0, 0.0),
                             mass=0.0, radius=radius)

    t_start = len(builder.tri_indices)
    areas = builder.add_triangles(
        faces[:, 0] + p_start, faces[:, 1] + p_start, faces[:, 2] + p_start,
        tri_ke=[float(config.garment_tri_ke)] * n_f, tri_ka=[float(config.garment_tri_ka)] * n_f,
        tri_kd=[float(config.garment_tri_kd)] * n_f, tri_drag=[float(config.garment_tri_drag)] * n_f,
        tri_lift=[float(config.garment_tri_lift)] * n_f,
    )
    areas = np.asarray(areas, dtype=np.float64)
    kept = areas > 0.0
    elem_of_face = np.cumsum(kept) - 1
    if not kept.all():
        print(f"{int((~kept).sum())} of {n_f} triangles degenerate at build and excluded (§3.3)")

    stitch = np.array([any(int(x) in cloth.stitch_set for x in tri) for tri in faces], dtype=bool)
    rest_area = areas.copy()
    rest_pose = np.zeros((n_f, 2, 2), dtype=np.float64)
    rest_pose[:] = np.eye(2)
    for fi in np.flatnonzero(kept):
        rest_pose[fi] = np.asarray(builder.tri_poses[t_start + int(elem_of_face[fi])], dtype=np.float64)

    if cloth.orig_lens:
        def side(u: int, w: int) -> float:
            length = cloth.rest_length(u, w)
            return length if length is not None else float(np.linalg.norm(verts[u] - verts[w]))

        for fi in np.flatnonzero(stitch):
            i, j, k = (int(x) for x in sorted(faces[fi]))
            pose, area = _flat_rest_pose(side(i, j), side(i, k), side(j, k))
            rest_pose[fi], rest_area[fi] = pose, area
    elif stitch.any():
        # §3.3 fallback: one equilateral rest shape scaled to the mean normal-triangle area
        normal_mean = float(areas[~stitch & kept].mean()) if (~stitch & kept).any() else 0.0
        side_len = float(config.resolution_scale)
        pose, area = _flat_rest_pose(side_len, side_len, side_len)
        scale = np.sqrt(normal_mean / area) if area > 0.0 and normal_mean > 0.0 else 1.0
        rest_pose[stitch] = pose / scale
        rest_area[stitch] = area * scale * scale
        print("orig_lens absent: stitch triangles use the equilateral fallback rest shape (§3.3)")

    for fi in np.flatnonzero(stitch & kept):
        ei = t_start + int(elem_of_face[fi])
        builder.tri_poses[ei] = rest_pose[fi].tolist()
        builder.tri_areas[ei] = float(rest_area[fi])

    mass = np.zeros(n_v, dtype=np.float64)
    share = np.repeat(rest_area * float(config.garment_density) / 3.0, 3)
    np.add.at(mass, faces.reshape(-1), share)
    for i in range(n_v):
        builder.particle_mass[p_start + i] = float(mass[i])

    edges = _interior_edges(faces)
    n_e = len(edges)
    if n_e:
        builder.add_edges(
            (edges[:, 0] + p_start).tolist(), (edges[:, 1] + p_start).tolist(),
            (edges[:, 2] + p_start).tolist(), (edges[:, 3] + p_start).tolist(),
            rest=[0.0] * n_e,                                  # §3.3 flat everywhere
            edge_ke=[float(config.garment_edge_ke)] * n_e, edge_kd=[float(config.garment_edge_kd)] * n_e,
        )

    springs = _springs_from_edges(edges)
    s_start = len(builder.spring_rest_length)
    ke, kd = float(config.spring_ke), float(config.spring_kd)
    for a, b in springs:
        builder.add_spring(int(a) + p_start, int(b) + p_start, ke, kd, 0.0)
    spring_rest = np.empty(len(springs), dtype=np.float64)
    for idx, (a, b) in enumerate(springs):
        length = cloth.rest_length(int(a), int(b))
        if length is None:
            length = float(builder.spring_rest_length[s_start + idx])
        else:
            builder.spring_rest_length[s_start + idx] = length
        spring_rest[idx] = length

    cloth.springs = springs
    cloth.spring_rest = spring_rest.astype(np.float32)
    cloth.edges = edges
    cloth.tri_rest_pose = rest_pose.astype(np.float32)
    cloth.tri_rest_area = rest_area.astype(np.float32)
    cloth.particle_mass = mass.astype(np.float32)


def build_scene(cloth: ClothData, config, params: SimParams, device: str | None = None,
                attachments=None) -> tuple[Ctx, Components]:
    from drape.sim_newton.body import BodyCollider
    from drape.sim_newton.integrate import integrate
    from drape.sim_newton.self_contact import SelfContact
    from drape.sim_newton.attach import Attachments
    from drape.sim_newton.panel_drag import ALLOW_PAIRS, PanelAssignment, PanelDrag

    builder = newton.ModelBuilder(up_axis=newton.Axis.Y, gravity=(0.0, 0.0, 0.0))
    add_cloth_sewing(builder, cloth, config)

    smoother = None
    if config.enable_body_smoothing:
        from drape.sim_newton.smoothing import BodySmoother

        smoother = BodySmoother(config, cloth)
        cloth.body_verts = np.asarray(smoother.start_verts, dtype=np.float64)

    body_faces_flat = np.ascontiguousarray(cloth.body_faces, dtype=np.int32).reshape(-1)
    newton_body_mesh = newton.Mesh(
        np.ascontiguousarray(cloth.body_verts, dtype=np.float32), body_faces_flat,
        compute_inertia=False, is_solid=False,
    )

    assignment = PanelAssignment()
    panel_labels, used_parts = assignment.run(cloth, strategy="closest", merge_two_legs=True, smpl_body=False)

    cfg = newton.ModelBuilder.ShapeConfig(mu=float(config.body_friction), margin=float(config.body_thickness))
    shape_index = builder.add_shape_mesh(-1, xform=wp.transform_identity(), mesh=newton_body_mesh,
                                         scale=(1.0, 1.0, 1.0), cfg=cfg)
    if shape_index != params.whole_body_shape_index:
        raise RuntimeError(f"body collider landed at shape {shape_index}, expected {params.whole_body_shape_index}")

    attach = attachments if attachments is not None else Attachments()

    model = builder.finalize(device)
    assert model.shape_body.numpy()[0] == -1, "the body collider must be a static shape"
    assert model.up_axis == newton.Axis.Y
    model.particle_max_velocity = float(config.global_max_velocity)   # §4.9
    model.particle_mu = float(config.particle_mu)                      # §4.3

    ctx = Ctx(model, cloth, config, params)
    ctx.body_mesh = newton_body_mesh.mesh                              # D3

    if config.enable_body_collision_filters:
        assignment.build_filters(cloth, panel_labels, ctx)
    name_to_index = assignment.register_reference_shapes(used_parts, cloth, ctx)
    assignment.add_reference_labels(panel_labels, ALLOW_PAIRS, name_to_index, ctx)
    attach.finalize(ctx)

    components = Components(
        body=BodyCollider(ctx, newton_body_mesh, float(config.body_thickness),
                          float(config.soft_contact_margin)),
        self_contact=SelfContact(ctx, params),
        attach=attach,
        drag=PanelDrag(ctx, params, float(config.cloth_reference_margin), k=float(config.cloth_reference_k)),
        integrate=integrate,
        smoother=smoother,
    )
    return ctx, components
