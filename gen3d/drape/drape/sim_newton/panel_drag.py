from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import warp as wp
from newton import ParticleFlags

if TYPE_CHECKING:
    from .builder import ClothData, Ctx, SimParams

UNBOUNDED = 1.0e6
NO_REFERENCE = -1
NO_FILTER = -1
FLAG_CLOTH_CLOTH = 1
FLAG_INSIDE_BODY = 2

STITCH = "stitch"
ARMS = "arms"
LEGS = "legs"
SINGLE_ARMS = ("left_arm", "right_arm")
SINGLE_LEGS = ("left_leg", "right_leg")
TRUNK = "body"
INTERNAL = "face_internal"

# §3.5: filter 0 hides the arms from leg fabric, filter 1 the internal faces from trunk fabric
FILTER_FACES = (SINGLE_ARMS + (ARMS,), (INTERNAL,))
FILTER_FABRIC = (SINGLE_LEGS + (LEGS,), (TRUNK,))

ALLOW_PAIRS: tuple[tuple[str, str], ...] = (
    ("left_arm", "body"),
    ("right_arm", "body"),
    ("left_leg", "right_leg"),
    ("left_arm", "left_leg"),
    ("right_arm", "left_leg"),
    ("left_arm", "right_leg"),
    ("right_arm", "right_leg"),
    ("left_arm", "legs"),
    ("right_arm", "legs"),
)


def read_segmentation(path: Path) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    with open(path) as handle:
        rows = handle.read().splitlines()
    for index, row in enumerate(rows):
        label = row.split(",")[0].strip()
        if not label:
            continue
        if label.startswith(STITCH):
            label = STITCH
        out.setdefault(label, []).append(index)
    return out


def vertex_neighbours(faces: np.ndarray) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    for a, b, c in np.asarray(faces, dtype=np.int64).reshape(-1, 3):
        i, j, k = int(a), int(b), int(c)
        out[i].extend((j, k))
        out[j].extend((k, i))
        out[k].extend((i, j))
    return dict(out)


def extract_submesh(
    verts: np.ndarray, indices_flat: np.ndarray, part_vertex_ids: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    source = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    ids = np.asarray(part_vertex_ids, dtype=np.int64).reshape(-1)
    lookup = np.full(len(source), -1, dtype=np.int64)
    lookup[ids] = np.arange(len(ids))
    tris = np.asarray(indices_flat, dtype=np.int64).reshape(-1, 3)
    mapped = lookup[tris] if len(tris) else np.zeros((0, 3), dtype=np.int64)
    keep = (mapped >= 0).all(axis=1) if len(mapped) else np.zeros(0, dtype=bool)
    faces = np.ascontiguousarray(mapped[keep], dtype=np.int32).reshape(-1)
    return source[ids], faces


def create_face_filter(
    body_verts: np.ndarray,
    body_indices_flat: np.ndarray,
    body_seg: dict[str, list[int]],
    part_names: Sequence[str],
    smpl_body: bool = False,
) -> np.ndarray:
    seg = _body_parts(body_seg, smpl_body)
    labels = _last_label_per_vertex(seg, len(np.asarray(body_verts).reshape(-1, 3)))
    wanted = {str(name) for name in part_names}
    marked = np.array([label in wanted for label in labels], dtype=bool)
    tris = np.asarray(body_indices_flat, dtype=np.int64).reshape(-1, 3)
    if not len(tris):
        return np.zeros(0, dtype=bool)
    # majority of the three vertices; an unlabelled vertex never counts
    return marked[tris].sum(axis=1) * 2 > 3


def assign_face_filter_points(
    panel_labels: Sequence[str | None],
    part_names: Sequence[str],
    filter_id: int,
    neighbours: dict[int, list[int]] | None = None,
    existing: np.ndarray | None = None,
) -> np.ndarray:
    count = len(panel_labels)
    if existing is None:
        out = np.full(count, NO_FILTER, dtype=np.int32)
    else:
        out = np.asarray(existing, dtype=np.int32).copy()
    wanted = {str(name) for name in part_names}
    for i in range(count):
        if out[i] != NO_FILTER:
            continue  # §3.5: the earlier assignment wins
        label = panel_labels[i]
        if label:
            if label in wanted:
                out[i] = filter_id
            continue
        if neighbours is None:
            continue
        nbrs = neighbours.get(i)
        if not nbrs:
            continue
        hits = sum(1 for j in nbrs if panel_labels[j] in wanted)
        if hits * 2 > len(nbrs):
            out[i] = filter_id
    return out


def _body_parts(body_seg: dict[str, list[int]], smpl_body: bool) -> dict[str, list[int]]:
    if smpl_body:
        raise NotImplementedError("the SMPL segmentation collapse is not ported (§3.4)")
    return dict(body_seg)


def _merge_limbs(seg: dict[str, list[int]]) -> dict[str, list[int]]:
    merged = dict(seg)
    for name, sides in ((ARMS, SINGLE_ARMS), (LEGS, SINGLE_LEGS)):
        union: list[int] = []
        for side in sides:
            union.extend(seg.get(side, ()))
        merged[name] = union
    return merged


def _last_label_per_vertex(seg: dict[str, list[int]], count: int) -> list[str | None]:
    labels: list[str | None] = [None] * count
    for name, verts in seg.items():
        for v in verts:
            labels[int(v)] = name  # §6.5.3: a multi-label vertex keeps only the last name
    return labels


def _labels_per_vertex(seg: dict[str, list[int]], count: int) -> list[list[str]]:
    carried: list[list[str]] = [[] for _ in range(count)]
    for name, verts in seg.items():
        for v in verts:
            carried[int(v)].append(name)
    return carried


def _device(ctx: Ctx):
    model = getattr(ctx, "model", None)
    return model.device if model is not None else wp.get_device()


@wp.kernel
def closest_face(
    points: wp.array(dtype=wp.vec3),
    mesh: wp.uint64,
    out_face: wp.array(dtype=wp.int32),
):
    tid = wp.tid()
    query = wp.mesh_query_point_no_sign(mesh, points[tid], UNBOUNDED)
    if query.result:
        out_face[tid] = query.face
    else:
        out_face[tid] = -1


def _closest_body_face(
    cloth_verts: np.ndarray, body_verts: np.ndarray, body_faces: np.ndarray, device=None
) -> np.ndarray:
    device = wp.get_device() if device is None else device
    mesh = wp.Mesh(
        points=wp.array(
            np.ascontiguousarray(np.asarray(body_verts).reshape(-1, 3), dtype=np.float32),
            dtype=wp.vec3,
            device=device,
        ),
        indices=wp.array(
            np.ascontiguousarray(body_faces, dtype=np.int32).reshape(-1), dtype=wp.int32, device=device
        ),
    )
    points = np.ascontiguousarray(np.asarray(cloth_verts).reshape(-1, 3), dtype=np.float32)
    out = wp.full(len(points), -1, dtype=wp.int32, device=device)
    wp.launch(
        closest_face,
        dim=len(points),
        inputs=[wp.array(points, dtype=wp.vec3, device=device), mesh.id],
        outputs=[out],
        device=device,
    )
    return out.numpy()


class PanelAssignment:
    def run(
        self,
        cloth: ClothData,
        *,
        strategy: str = "closest",
        merge_two_legs: bool = True,
        smpl_body: bool = False,
    ) -> tuple[list[str | None], dict[str, list[int]]]:
        if strategy != "closest":
            raise NotImplementedError(f"panel assignment strategy {strategy!r} is not ported (§3.4)")
        seg = _body_parts(cloth.body_seg, smpl_body)
        merged = _merge_limbs(seg)
        body_verts = np.asarray(cloth.body_verts, dtype=np.float64).reshape(-1, 3)
        body_faces = np.asarray(cloth.body_faces, dtype=np.int64).reshape(-1, 3)
        carried = _labels_per_vertex(seg, len(body_verts))
        verts = np.asarray(cloth.verts, dtype=np.float64).reshape(-1, 3)
        face_of = _closest_body_face(verts, body_verts, body_faces)

        labels: list[str | None] = [None] * len(verts)
        used: dict[str, list[int]] = {}
        for panel, panel_verts in cloth.labels.items():
            if not panel or panel == STITCH:
                continue
            scores = {name: 0.0 for name in seg}
            for v in panel_verts:
                face = int(face_of[int(v)])
                if face < 0:
                    continue
                for bv in body_faces[face]:
                    for name in carried[int(bv)]:
                        scores[name] += 1.0 / 3.0
            preferred = str(cloth.panel_pref_label.get(panel) or "")
            if preferred:
                for name in scores:
                    if preferred not in name:
                        scores[name] = -1.0  # §3.4: a non-matching part is cancelled
            winner = max(scores, key=lambda name: scores[name])
            if merge_two_legs and winner in SINGLE_LEGS and "pant" not in panel:
                winner = LEGS
            for v in panel_verts:
                labels[int(v)] = winner
            if winner not in used:
                used[winner] = list(merged[winner])  # votes un-merged, used parts merged (§3.4)
        return labels, used

    def build_filters(self, cloth: ClothData, panel_labels: Sequence[str | None], ctx: Ctx) -> None:
        device = _device(ctx)
        body_faces_flat = np.ascontiguousarray(cloth.body_faces, dtype=np.int32).reshape(-1)
        filters = np.stack(
            [
                create_face_filter(cloth.body_verts, body_faces_flat, cloth.body_seg, names)
                for names in FILTER_FACES
            ]
        ).astype(np.uint8)
        neighbours = vertex_neighbours(cloth.faces)
        ids: np.ndarray | None = None
        for filter_id, names in enumerate(FILTER_FABRIC):
            ids = assign_face_filter_points(panel_labels, names, filter_id, neighbours, ids)
        ctx.face_filters = wp.array(filters, dtype=wp.uint8, device=device)
        ctx.particle_filter_id = wp.array(
            np.ascontiguousarray(ids, dtype=np.int32), dtype=wp.int32, device=device
        )

    def register_reference_shapes(
        self, used_parts: dict[str, list[int]], cloth: ClothData, ctx: Ctx
    ) -> dict[str, int]:
        device = _device(ctx)
        flat = np.ascontiguousarray(cloth.body_faces, dtype=np.int32).reshape(-1)
        name_to_index: dict[str, int] = {}
        ids: list[int] = []
        for name, part_verts in used_parts.items():
            sub_verts, sub_faces = extract_submesh(cloth.body_verts, flat, part_verts)
            if not sub_faces.size:
                print(f"body part {name} has no whole face and is not registered as a reference shape")
                continue
            mesh = wp.Mesh(
                points=wp.array(
                    np.ascontiguousarray(sub_verts, dtype=np.float32), dtype=wp.vec3, device=device
                ),
                indices=wp.array(sub_faces, dtype=wp.int32, device=device),
            )
            name_to_index[name] = len(ctx.ref_meshes)
            ctx.ref_meshes.append(mesh)
            ids.append(mesh.id)
        ctx.ref_mesh_ids = wp.array(np.asarray(ids, dtype=np.uint64), dtype=wp.uint64, device=device)
        return name_to_index

    def add_reference_labels(
        self,
        panel_labels: Sequence[str | None],
        pairs: Sequence[tuple[str, str]],
        name_to_index: dict[str, int],
        ctx: Ctx,
    ) -> dict[str, int]:
        count = len(panel_labels)
        model = getattr(ctx, "model", None)
        if model is not None and int(model.particle_count) != count:
            raise ValueError(
                f"reference label list has {count} entries for {int(model.particle_count)} particles"
            )
        if not name_to_index:
            raise ValueError("no reference shape is registered (§3.4)")
        device = _device(ctx)
        ref = np.full(count, NO_REFERENCE, dtype=np.int32)
        unknown: set[str] = set()
        for i, label in enumerate(panel_labels):
            if not label or label == STITCH:
                continue
            index = name_to_index.get(label)
            if index is None:
                unknown.add(label)
                continue
            ref[i] = index
        for label in sorted(unknown):
            print(f"reference label {label} names no registered shape; those particles get no reference")
        kept = [
            (name_to_index[a], name_to_index[b])
            for a, b in pairs
            if a in name_to_index and b in name_to_index
        ]
        ctx.ref_label = wp.array(ref, dtype=wp.int32, device=device)
        if kept:
            ctx.allow_pairs = wp.array(
                np.asarray(kept, dtype=np.int32).reshape(-1, 2), dtype=wp.vec2i, device=device
            )
        else:
            ctx.allow_pairs = wp.zeros(0, dtype=wp.vec2i, device=device)
        ctx.n_pairs = len(kept)
        return name_to_index


@wp.func
def inside_reference_body(mesh: wp.uint64, p: wp.vec3, axes: wp.array(dtype=wp.vec3)) -> bool:
    # §4.3 three-ray parity vote, unanimity required
    votes = int(0)
    for k in range(3):
        hit = wp.mesh_query_ray(mesh, p, axes[k], UNBOUNDED)
        if hit.result:
            if hit.sign < 0.0:
                votes += 1
    return votes == 3


@wp.kernel
def drag_particles(
    flag_drag: wp.array(dtype=wp.int32),
    ref_label: wp.array(dtype=wp.int32),
    ref_mesh_ids: wp.array(dtype=wp.uint64),
    body_mesh: wp.uint64,
    x0: wp.array(dtype=wp.vec3),
    particle_radius: wp.array(dtype=float),
    particle_flags: wp.array(dtype=wp.int32),
    margin: float,
    axes: wp.array(dtype=wp.vec3),
    delta: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    flag = flag_drag[tid]
    if flag == 0:
        return
    if (particle_flags[tid] & ParticleFlags.ACTIVE) == 0:
        return
    label = ref_label[tid]
    if label < 0:
        return

    px = x0[tid]
    if flag == FLAG_CLOTH_CLOTH:
        mesh = ref_mesh_ids[label]
        query = wp.mesh_query_point_no_sign(mesh, px, UNBOUNDED)
        if not query.result:
            return
        target = wp.mesh_eval_position(mesh, query.face, query.u, query.v)
        if wp.length(target - px) <= margin + particle_radius[tid]:
            return
        # full projection onto the part, no compliance: the §4.9 cap is the only limit
        wp.atomic_add(delta, tid, target - px)
    elif flag == FLAG_INSIDE_BODY:
        if not inside_reference_body(body_mesh, px, axes):
            return
        query = wp.mesh_query_point_no_sign(body_mesh, px, UNBOUNDED)
        if not query.result:
            return
        target = wp.mesh_eval_position(body_mesh, query.face, query.u, query.v)
        wp.atomic_add(delta, tid, target - px)


class PanelDrag:
    def __init__(self, ctx: Ctx, params: SimParams, margin: float, k: float = 1.0e7) -> None:
        self.ctx = ctx
        self.margin = float(margin)
        self.k = float(k)  # §6.12: stored, never read
        self.device = _device(ctx)
        self.particle_count = int(ctx.x_frame0.shape[0])
        self.axes = wp.array(
            np.asarray(params.ray_axes, dtype=np.float32).reshape(-1, 3), dtype=wp.vec3, device=self.device
        )

    def solve(self, dt: float) -> None:
        ctx = self.ctx
        if ctx.body_mesh is None:
            raise RuntimeError("body mesh is missing; build PanelDrag after the body collider")
        wp.launch(
            drag_particles,
            dim=self.particle_count,
            inputs=[
                ctx.flag_drag,
                ctx.ref_label,
                ctx.ref_mesh_ids,
                ctx.body_mesh.id,
                ctx.x_frame0,
                ctx.model.particle_radius,
                ctx.model.particle_flags,
                self.margin,
                self.axes,
            ],
            outputs=[ctx.delta],
            device=self.device,
        )
