import numpy as np

from app.mannequin.generator import (
    LEG,
    N_FOOT,
    N_LEG,
    body_parts,
    leg_ring_at,
    mirror,
    part_flip,
    part_normals,
    tube_faces,
    tube_vertices,
    vertex_normals,
)
from app.mannequin.params import body_params

# shaft: how far the boot climbs above the ankle joint
SHOES = {"shoe_v1": dict(shaft=0.0), "boot_v1": dict(shaft=0.12)}
UPPER, SOLE, BEVEL, SHAFT_RINGS = 0.012, 0.025, 0.003, 6
# sole margin past the upper at the sides and at heel and toe
SIDE, END = 0.005, 0.01
# collar: clearance off the ankle, lowest height, widening across the foot
CLEAR, COLLAR, WIDE = 0.014, 0.06, 1.2
# grid neighbors, edges first
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _upper(parts: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rings, s, e = parts["foot_l"]
    n, ns, ne = part_normals("foot_l", parts["foot_l"])
    shell = rings + UPPER * n
    # what hangs below the sole top tucks inside the sole
    shell[..., 1] = np.maximum(shell[..., 1], SOLE / 2)
    return shell, s + UPPER * ns, e + UPPER * ne


def _faces(keep: np.ndarray, swap: np.ndarray) -> np.ndarray:
    rings, flip = len(keep) + 1, part_flip("foot_l")
    idx = 1 + np.arange(rings * N_FOOT).reshape(rings, N_FOOT)
    nxt = np.roll(idx, -1, 1)
    q = np.stack([idx[:-1], nxt[:-1], nxt[1:], idx[1:]], -1)
    q = np.where(swap[..., None], np.roll(q, -1, -1), q)[keep]
    f = np.vstack([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    return np.vstack([f[:, ::-1] if flip else f, tube_faces(rings, N_FOOT, flip=flip, keep=np.zeros_like(keep))])


def _collar(shell: np.ndarray, base) -> tuple[np.ndarray, np.ndarray]:
    # cut on the middle body so every body keeps the same faces
    parts = body_parts(body_params(base))
    ref = _upper(parts)[0]
    ankle = parts["leg_l"][0][LEG["ankle"]]
    c, half = (ankle.max(0) + ankle.min(0)) / 2, (ankle.max(0) - ankle.min(0)) / 2 + CLEAR
    r = np.linalg.norm((ref - c)[..., [0, 2]] / (half[[0, 2]] * [WIDE, 1.0]), axis=-1)
    f = np.maximum((r - 1) * half[2], COLLAR - ref[..., 1])
    hole = f < 0
    keep = ~(hole[:-1] | hole[1:] | np.roll(hole[:-1], -1, 1) | np.roll(hole[1:], -1, 1))
    # split quads along the diagonal facing away from the hole so its corners do not fold
    along = np.arange(len(f) - 1)[:, None] + 0.5 - f[:, 0].argmin()
    swap = along * ((np.arange(N_FOOT) + 0.5 + N_FOOT / 2) % N_FOOT - N_FOOT / 2) < 0
    fn = np.stack([np.roll(f, d, (0, 1)) for d in NEIGHBORS])
    cut = (f >= 0) & (fn < 0)
    # edge vertices move to the mean of where the cut crosses their edges
    t = np.where(cut[:4], f / np.maximum(f - fn[:4], 1e-12), 0.0)
    step = np.stack([np.roll(shell, d, (0, 1)) for d in NEIGHBORS[:4]]) - shell
    side = cut[:4].any(0)
    shell = shell + (t[..., None] * step).sum(0) / np.maximum(cut[:4].sum(0), 1)[..., None]
    # staircase corners settle between their two moved neighbors
    for i, (dr, dj) in enumerate(NEIGHBORS[4:], 4):
        m = cut[i] & ~side
        shell[m] = (np.roll(shell, (dr, 0), (0, 1))[m] + np.roll(shell, (0, dj), (0, 1))[m]) / 2
    return shell, _faces(keep, swap)


def _sole(shell: np.ndarray, s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    q = N_FOOT // 4
    loop = np.vstack([s, shell[:, q], e, shell[::-1, 3 * q]])[:, [0, 2]]
    t = np.roll(loop, -1, 0) - np.roll(loop, 1, 0)
    n = np.stack([t[:, 1], -t[:, 0]], 1) / np.linalg.norm(t, axis=1, keepdims=True)
    loop = loop + n * (SIDE + (END - SIDE) * n[:, 1:] ** 2)
    xz = loop - np.array([BEVEL, 0, 0, BEVEL])[:, None, None] * n
    ys = np.broadcast_to(np.array([0, BEVEL, SOLE - BEVEL, SOLE])[:, None], xz.shape[:2])
    c = loop.mean(0)
    verts = tube_vertices(np.stack([xz[..., 0], ys, xz[..., 1]], -1), np.r_[c[0], 0, c[1]], np.r_[c[0], SOLE, c[1]])
    return verts, tube_faces(4, len(loop), flip=True)


def _shaft(p: dict, parts: dict, height: float) -> tuple[np.ndarray, np.ndarray]:
    ys = p["ankle"][1] + height * np.arange(SHAFT_RINGS, 0, -1) / SHAFT_RINGS
    # below the ankle it follows the rounded end of the leg down into the shoe
    rings = np.concatenate([np.stack([leg_ring_at(p, y) for y in ys]), parts["leg_l"][0][LEG["ankle"] :]])
    faces = tube_faces(len(rings), N_LEG, False, False, part_flip("leg_l"))
    v = tube_vertices(rings)
    return v + UPPER * vertex_normals(v, faces), faces


def shoe_mesh(template_id: str, base, sliders: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    p = body_params(base, sliders)
    parts = body_parts(p)
    shell, s, e = _upper(parts)
    sole = _sole(shell, s, e)
    shaft = SHOES[template_id]["shaft"]
    if shaft:
        # the shaft hides the ankle so the boot keeps its upper closed
        upper = tube_faces(len(shell), N_FOOT, flip=part_flip("foot_l"))
    else:
        shell, upper = _collar(shell, p["base"])
    patches = [(tube_vertices(shell, s, e), upper), sole] + ([_shaft(p, parts, shaft)] if shaft else [])
    verts, faces, n = [], [], 0
    for v, f in patches:
        verts.append(v)
        faces.append(f + n)
        n += len(v)
    # drop the vertices the collar cut left unused
    used, inv = np.unique(np.vstack(faces), return_inverse=True)
    verts, faces = np.vstack(verts)[used], inv.reshape(-1, 3)
    # the right shoe mirrors the left
    return np.vstack([verts, mirror(verts)]) * p["scale"], np.vstack([faces, faces[:, ::-1] + len(verts)])


def shoe_uv(verts: np.ndarray) -> np.ndarray:
    # side projection shared by both shoes: heel to toe across, top to sole down
    lo, hi = verts.min(0), verts.max(0)
    return np.stack([(verts[:, 2] - lo[2]) / (hi[2] - lo[2]), (hi[1] - verts[:, 1]) / (hi[1] - lo[1])], 1)
