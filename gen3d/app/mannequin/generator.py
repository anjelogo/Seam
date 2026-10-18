import numpy as np
from scipy.interpolate import PchipInterpolator

from app.mannequin.params import ARM_ANGLE, ARM_FORWARD, FOOT_SOLE, STATIONS, body_params

N_TRUNK, N_ARM, N_LEG, N_FOOT = 64, 24, 32, 24
TRUNK_SEGMENTS = (7, 5, 4, 4, 4, 6, 4)
N_BOWL, N_HEAD_LO, N_HEAD_HI = 7, 6, 10
N_CAP, N_TIP, N_ANKLE = 6, 4, 3
ARM_SEGMENTS = (7, 7, 11, 8)
LEG_SEGMENTS = (9, 10, 17)
LEG_MARKS = (0.25, 0.52)
N_HEEL, N_SOLE = 3, 14


def _marks(start: int, counts: tuple, names: tuple) -> dict:
    out, i = {}, start
    for n, name in zip(counts, names):
        i += n
        out[name] = i
    return out


# ring index of each landmark inside its part
TRUNK = {"hip": N_BOWL, **_marks(N_BOWL, TRUNK_SEGMENTS, STATIONS[1:])}
TRUNK["head"] = TRUNK["necktop"] + N_HEAD_LO
TRUNK["rings"] = TRUNK["head"] + N_HEAD_HI + 1
ARM = {"joint": N_CAP - 1, **_marks(N_CAP - 1, ARM_SEGMENTS, ("mid_upper", "elbow", "wrist", "tip_start"))}
ARM["rings"] = ARM["tip_start"] + N_TIP + 1
LEG = {"joint": N_CAP - 1, **_marks(N_CAP - 1, LEG_SEGMENTS, ("mid_thigh", "knee", "ankle"))}
LEG["rings"] = LEG["ankle"] + N_ANKLE + 1
FOOT = {"rings": 2 * N_HEEL + N_SOLE}
LAYOUT = (
    ("trunk", TRUNK["rings"], N_TRUNK),
    ("arm_l", ARM["rings"], N_ARM),
    ("arm_r", ARM["rings"], N_ARM),
    ("leg_l", LEG["rings"], N_LEG),
    ("leg_r", LEG["rings"], N_LEG),
    ("foot_l", FOOT["rings"], N_FOOT),
    ("foot_r", FOOT["rings"], N_FOOT),
)
FLIP = {"trunk": False, "arm": True, "leg": True, "foot": True}


def _segments(marks, counts) -> np.ndarray:
    return np.concatenate([a + (b - a) * np.arange(1, n + 1) / n for a, b, n in zip(marks[:-1], marks[1:], counts)])


def angles(n: int) -> tuple[np.ndarray, np.ndarray]:
    th = 2 * np.pi * np.arange(n) / n
    return np.sin(th), np.cos(th)


def sexp(v: np.ndarray, ex: float) -> np.ndarray:
    return np.sign(v) * np.abs(v) ** (2.0 / ex)


def smoothstep(e0: float, e1: float, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def trunk_section(p: dict, y: float) -> np.ndarray:
    t = p["torso"]
    if y <= t[0, 0]:
        # cubic closure stays wide where the thighs join
        k = max(0.0, 1 - ((t[0, 0] - y) / (t[0, 0] - p["crotch"])) ** 3) ** (1 / 3)
        return np.array([t[0, 1] * k, t[0, 2] * k, t[0, 3] * k, t[0, 4], t[0, 5]])
    if y <= t[-1, 0]:
        if "spline" not in p:
            p["spline"] = PchipInterpolator(t[:, 0], t[:, 1:], axis=0)
        return p["spline"](y)
    hy, h_up, h_dn, ha_up, ha_lo, hbf, hbb, hz = p["head"]
    q = (y - hy) / (h_up if y >= hy else h_dn)
    e = np.sqrt(max(0.0, 1 - q * q))
    taper = min(q, 0.0)
    head = np.array([ha_up + (ha_up - ha_lo) * taper, hbf * (1 + 0.08 * taper), hbb]) * e
    # neck fades out inside the head; 4-norm gives a smooth jaw
    wn = (1 - smoothstep(hy - 0.3 * h_dn, hy + 0.5 * h_up, y)) * t[-1, 1:4] ** 4
    wh = head**4
    w = wh[0] / (wn[0] + wh[0]) if wn[0] + wh[0] > 0 else 1.0
    return np.r_[(wn + wh) ** 0.25, t[-1, 4] * (1 - w) + hz * w, 2.0]


def trunk_ring(p: dict, y: float) -> np.ndarray:
    a, bf, bb, zc, ex = trunk_section(p, y)
    s, c = angles(N_TRUNK)
    amp, ly, up, dn, th0, sig = p["lobe"]
    th = np.arctan2(s, c)
    lobe = amp * np.exp(-(((y - ly) / (up if y > ly else dn)) ** 2))
    lobe = lobe * (np.exp(-(((th - th0) / sig) ** 2)) + np.exp(-(((th + th0) / sig) ** 2)))
    z = zc + np.where(c >= 0, bf, bb) * sexp(c, ex) + lobe
    return np.stack([a * sexp(s, ex), np.full(N_TRUNK, y), z], -1)


def trunk_heights(p: dict) -> np.ndarray:
    t = p["torso"]
    hy, h_up = p["head"][:2]
    psi = np.pi / 2 * np.arange(N_BOWL, 0, -1) / (N_BOWL + 1)
    return np.concatenate([
        t[0, 0] - (t[0, 0] - p["crotch"]) * np.sin(psi),
        t[:1, 0],
        _segments(t[:, 0], TRUNK_SEGMENTS),
        t[-1, 0] + (hy - t[-1, 0]) * np.arange(1, N_HEAD_LO + 1) / N_HEAD_LO,
        hy + h_up * np.sin(np.pi / 2 * np.arange(1, N_HEAD_HI + 1) / (N_HEAD_HI + 1)),
    ])


def trunk(p: dict) -> tuple:
    hy, h_up = p["head"][:2]
    rings = np.stack([trunk_ring(p, y) for y in trunk_heights(p)])
    return rings, np.array([0.0, p["crotch"], p["torso"][0, 4]]), np.array([0.0, hy + h_up, p["head"][7]])


def _frame(u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    e2 = np.array([0.0, 0.0, 1.0]) - u[2] * u
    e2 /= np.linalg.norm(e2)
    return np.cross(e2, u), e2


def _tube(origin: np.ndarray, u: np.ndarray, s: np.ndarray, r: np.ndarray, n: int) -> np.ndarray:
    e1, e2 = _frame(u)
    sn, cs = angles(n)
    c1 = r[:, :1] * sn
    c2 = np.where(cs >= 0, r[:, 1:2], r[:, 2:3]) * cs
    return origin + s[:, None, None] * u + c1[..., None] * e1 + c2[..., None] * e2


def arm_dir() -> np.ndarray:
    u = np.array([np.sin(ARM_ANGLE), -np.cos(ARM_ANGLE), np.tan(ARM_FORWARD)])
    return u / np.linalg.norm(u)


def arm(p: dict) -> tuple:
    st, marks, j, u = p["arm"], p["arm_marks"], p["shoulder_joint"], arm_dir()
    spline = PchipInterpolator(st[:, 0], st[:, 1:], axis=0)
    a = np.pi / 2 * np.arange(1, N_CAP + 1) / N_CAP
    b = np.pi / 2 * np.arange(1, N_TIP + 1) / (N_TIP + 1)
    body = _segments(np.r_[0.0, marks[:4]], ARM_SEGMENTS)
    s = np.concatenate([-st[0, 1] * np.cos(a), body, marks[3] + (marks[4] - marks[3]) * np.sin(b)])
    r = np.vstack([np.outer(np.sin(a), st[0, 1:]), spline(body), np.outer(np.cos(b), spline(marks[3]))])
    return _tube(j, u, s, np.c_[r, r[:, 1]], N_ARM), j - u * st[0, 1], j + u * marks[4]


def leg_axis(p: dict) -> tuple[np.ndarray, np.ndarray, float]:
    h, a = p["hip_joint"], p["ankle"]
    length = float(np.linalg.norm(a - h))
    return h, (a - h) / length, length


def _leg_spline(p: dict, length: float) -> PchipInterpolator:
    return PchipInterpolator(p["leg"][:, 0] * length, p["leg"][:, 1:], axis=0)


def leg(p: dict) -> tuple:
    st = p["leg"]
    h, u, length = leg_axis(p)
    a = np.pi / 2 * np.arange(1, N_CAP + 1) / N_CAP
    b = np.pi / 2 * np.arange(1, N_ANKLE + 1) / (N_ANKLE + 1)
    body = _segments(np.r_[0.0, LEG_MARKS, 1.0] * length, LEG_SEGMENTS)
    r_top, r_ank = st[0, 1], st[-1, 1]
    s = np.concatenate([-r_top * np.cos(a), body, length + r_ank * np.sin(b)])
    r = np.vstack([np.outer(np.sin(a), st[0, 1:]), _leg_spline(p, length)(body), np.outer(np.cos(b), st[-1, 1:])])
    return _tube(h, u, s, r, N_LEG), h - u * r_top, h + u * (length + r_ank)


def leg_ring_at(p: dict, y: float) -> np.ndarray | None:
    st = p["leg"]
    h, u, length = leg_axis(p)
    s, r_top = (y - h[1]) / u[1], st[0, 1]
    if s < -r_top or s > length:
        return None
    r = st[0, 1:] * np.sqrt(1 - (s / r_top) ** 2) if s < 0 else _leg_spline(p, length)(s)
    return _tube(h, u, np.array([s]), r[None], N_LEG)[0]


def foot(p: dict) -> tuple:
    st, (z_heel, z_toe) = p["foot"], p["foot_ends"]
    x0, _, az = p["ankle"]
    x0 += 0.006
    b = np.pi / 2 * np.arange(1, N_HEEL + 1) / (N_HEEL + 1)
    z0, z1 = st[0, 0], st[-1, 0]
    body = z0 + (z1 - z0) * np.arange(N_SOLE) / (N_SOLE - 1)
    z = np.concatenate([z0 - (z0 - z_heel) * np.sin(b[::-1]), body, z1 + (z_toe - z1) * np.sin(b)])
    k = np.concatenate([np.cos(b[::-1]), np.ones(N_SOLE), np.cos(b)])[:, None]
    wh = np.vstack([np.tile(st[0, 1:], (N_HEEL, 1)), PchipInterpolator(st[:, 0], st[:, 1:], axis=0)(body), np.tile(st[-1, 1:], (N_HEEL, 1))])
    sn, cs = angles(N_FOOT)
    x = x0 + wh[:, :1] * k * sn
    # flat-ish sole: shallow lower half, tall upper half
    y = FOOT_SOLE + np.where(cs >= 0, wh[:, 1:2] - FOOT_SOLE, FOOT_SOLE) * k * cs
    rings = np.stack([x, y, np.broadcast_to(az + z[:, None], x.shape)], -1)
    return rings, np.array([x0, FOOT_SOLE, az + z_heel]), np.array([x0, FOOT_SOLE, az + z_toe])


def mirror(v: np.ndarray) -> np.ndarray:
    return v * np.array([-1.0, 1.0, 1.0])


def body_parts(p: dict) -> dict:
    out = {"trunk": trunk(p)}
    for kind, fn in (("arm", arm), ("leg", leg), ("foot", foot)):
        part = fn(p)
        out[kind + "_l"] = part
        out[kind + "_r"] = tuple(mirror(v) for v in part)
    return {name: out[name] for name, _, _ in LAYOUT}


def part_flip(name: str) -> bool:
    kind, _, side = name.partition("_")
    return FLIP[kind] != (side == "r")


def tube_vertices(rings: np.ndarray, start=None, end=None) -> np.ndarray:
    out = [rings.reshape(-1, 3)]
    if start is not None:
        out.insert(0, start[None])
    if end is not None:
        out.append(end[None])
    return np.vstack(out)


def tube_faces(rings: int, n: int, start: bool = True, end: bool = True, flip: bool = False, keep=None) -> np.ndarray:
    off = int(start)
    idx = off + np.arange(rings * n).reshape(rings, n)
    nxt = np.roll(idx, -1, axis=1)
    quads = np.stack([idx[:-1], nxt[:-1], nxt[1:], idx[1:]], -1)
    quads = (quads[keep] if keep is not None else quads).reshape(-1, 4)
    faces = [quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]]
    if start:
        faces.append(np.stack([np.zeros(n, int), nxt[0], idx[0]], -1))
    if end:
        faces.append(np.stack([np.full(n, off + rings * n), idx[-1], nxt[-1]], -1))
    f = np.vstack(faces)
    return f[:, ::-1] if flip else f


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def part_normals(name: str, part: tuple) -> tuple:
    rings, s, e = part
    r, k = rings.shape[:2]
    n = vertex_normals(tube_vertices(*part), tube_faces(r, k, flip=part_flip(name)))
    return n[1 : 1 + r * k].reshape(r, k, 3), n[0], n[-1]


def body_mesh(base, sliders: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    p = body_params(base, sliders)
    verts, faces, n = [], [], 0
    for name, part in body_parts(p).items():
        v = tube_vertices(*part)
        faces.append(tube_faces(len(part[0]), part[0].shape[1], flip=part_flip(name)) + n)
        verts.append(v)
        n += len(v)
    return np.vstack(verts) * p["scale"], np.vstack(faces)


def split(verts: np.ndarray) -> dict:
    out, i = {}, 0
    for name, r, n in LAYOUT:
        out[name] = (verts[i + 1 : i + 1 + r * n].reshape(r, n, 3), verts[i], verts[i + 1 + r * n])
        i += r * n + 2
    return out
