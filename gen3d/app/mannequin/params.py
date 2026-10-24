import numpy as np
from seam_shared.models import BodyBase

SLIDERS = ("height", "weight", "muscle", "shoulders", "chest", "waist", "hips", "leg_length")
STATIONS = ("hip", "waist", "underbust", "chest", "armpit", "shoulder", "neckbase", "necktop")
ARM_ANGLE, ARM_FORWARD = np.radians(20.0), np.radians(4.0)
FOOT_SOLE = 0.014

# meters at sliders 0.5; row layouts are noted on the masc keys
REF = {
    "masc": {
        "crotch": 0.815,
        "torso": (  # y, half width, front depth, back depth, z center, squareness

            (0.925, 0.176, 0.100, 0.122, -0.010, 2.2),
            (1.065, 0.138, 0.100, 0.095, 0.000, 2.1),
            (1.170, 0.150, 0.108, 0.100, 0.002, 2.3),
            (1.265, 0.164, 0.112, 0.103, 0.006, 2.4),
            (1.345, 0.168, 0.105, 0.103, 0.002, 2.5),
            (1.441, 0.1879, 0.082, 0.088, -0.008, 2.4),
            (1.4894, 0.062, 0.055, 0.060, -0.018, 2.0),
            (1.532, 0.056, 0.053, 0.055, -0.010, 2.0),
        ),
        "head": (1.640, 0.110, 0.115, 0.076, 0.064, 0.097, 0.100, 0.010),  # y, half height up/down, half width top/chin, depth front/back, z
        "lobe": (0.010, 1.270, 0.050, 0.035, 0.65, 0.55),  # depth, y, spread up/down, angle off front, angular spread
        "arm": (  # distance from shoulder joint, side radius, front radius
            (0.000, 0.056, 0.056), (0.060, 0.052, 0.053), (0.145, 0.047, 0.049), (0.240, 0.042, 0.043),
            (0.290, 0.039, 0.040), (0.340, 0.042, 0.043), (0.440, 0.034, 0.035), (0.535, 0.026, 0.031),
            (0.565, 0.021, 0.037), (0.610, 0.019, 0.046), (0.655, 0.018, 0.047), (0.690, 0.016, 0.044),
        ),
        "arm_marks": (0.145, 0.290, 0.535, 0.690, 0.725),  # mid upper arm, elbow, wrist, hand tip start, tip
        "hip_x": 0.086,
        "ankle": (0.100, 0.085, -0.012),
        "leg": (  # fraction hip->ankle, side, front, back radius
            (0.00, 0.089, 0.082, 0.088), (0.12, 0.082, 0.078, 0.083), (0.25, 0.073, 0.070, 0.074),
            (0.40, 0.061, 0.058, 0.061), (0.52, 0.054, 0.055, 0.053), (0.60, 0.053, 0.049, 0.059),
            (0.68, 0.056, 0.047, 0.066), (0.80, 0.047, 0.040, 0.052), (0.92, 0.037, 0.034, 0.038),
            (1.00, 0.035, 0.034, 0.035),
        ),
        "foot": (  # z from ankle, half width, top height
            (-0.060, 0.026, 0.058), (-0.035, 0.032, 0.085), (0.000, 0.037, 0.104), (0.040, 0.041, 0.090),
            (0.090, 0.045, 0.066), (0.140, 0.047, 0.048), (0.175, 0.044, 0.038),
        ),
        "foot_ends": (-0.078, 0.205),
    },
    "fem": {
        "crotch": 0.800,
        "torso": (
            (0.905, 0.186, 0.106, 0.134, -0.012, 2.2),
            (1.050, 0.122, 0.088, 0.085, 0.000, 2.0),
            (1.150, 0.130, 0.090, 0.088, 0.002, 2.2),
            (1.240, 0.144, 0.096, 0.093, 0.004, 2.3),
            (1.315, 0.150, 0.094, 0.094, 0.000, 2.4),
            (1.405, 0.1686, 0.074, 0.080, -0.008, 2.3),
            (1.4594, 0.054, 0.049, 0.052, -0.016, 2.0),
            (1.505, 0.050, 0.047, 0.048, -0.008, 2.0),
        ),
        "head": (1.615, 0.105, 0.110, 0.071, 0.059, 0.091, 0.095, 0.010),
        "lobe": (0.046, 1.245, 0.080, 0.045, 0.55, 0.50),
        "arm": (
            (0.000, 0.048, 0.048), (0.057, 0.045, 0.046), (0.138, 0.041, 0.043), (0.228, 0.036, 0.037),
            (0.275, 0.033, 0.034), (0.323, 0.036, 0.037), (0.418, 0.030, 0.031), (0.508, 0.022, 0.027),
            (0.537, 0.019, 0.033), (0.580, 0.017, 0.041), (0.622, 0.016, 0.042), (0.655, 0.014, 0.039),
        ),
        "arm_marks": (0.138, 0.275, 0.508, 0.655, 0.688),
        "hip_x": 0.090,
        "ankle": (0.098, 0.080, -0.012),
        "leg": (
            (0.00, 0.093, 0.086, 0.093), (0.12, 0.086, 0.080, 0.087), (0.25, 0.072, 0.068, 0.074),
            (0.40, 0.058, 0.055, 0.059), (0.52, 0.050, 0.051, 0.049), (0.60, 0.050, 0.046, 0.055),
            (0.68, 0.053, 0.043, 0.061), (0.80, 0.043, 0.036, 0.047), (0.92, 0.034, 0.031, 0.035),
            (1.00, 0.032, 0.030, 0.032),
        ),
        "foot": (
            (-0.055, 0.024, 0.055), (-0.032, 0.029, 0.080), (0.000, 0.034, 0.098), (0.037, 0.038, 0.085),
            (0.083, 0.041, 0.062), (0.129, 0.043, 0.045), (0.161, 0.040, 0.036),
        ),
        "foot_ends": (-0.072, 0.189),
    },
}

# per station (half width, front depth, back depth): relative change per unit slider away from 0.5
TORSO_K = {
    "hip": (dict(weight=0.16, hips=0.18), dict(weight=0.25, hips=0.10), dict(weight=0.18, hips=0.26)),
    "waist": (dict(weight=0.30, waist=0.28, muscle=-0.04, hips=0.04), dict(weight=0.50, waist=0.28), dict(weight=0.25, waist=0.24)),
    "underbust": (dict(weight=0.22, waist=0.10, muscle=0.04), dict(weight=0.32, waist=0.08, chest=0.10), dict(weight=0.20)),
    "chest": (dict(weight=0.12, muscle=0.05, shoulders=0.03, chest=0.08), dict(weight=0.18, muscle=0.14, chest=0.22), dict(weight=0.15, muscle=0.10, chest=0.04)),
    "armpit": (dict(weight=0.10, muscle=0.06, shoulders=0.08), dict(weight=0.14, muscle=0.12, chest=0.10), dict(weight=0.12, muscle=0.10)),
    "shoulder": (dict(weight=0.06, muscle=0.07, shoulders=0.18), dict(weight=0.12, muscle=0.14), dict(weight=0.12, muscle=0.14)),
    "neckbase": (dict(weight=0.12, muscle=0.14, shoulders=0.04), dict(weight=0.12, muscle=0.14), dict(weight=0.12, muscle=0.14)),
    "necktop": (dict(weight=0.12, muscle=0.12),) * 3,
}
ARM_K = (dict(weight=0.14, muscle=0.24),) * 2 + (dict(weight=0.24, muscle=0.22),) * 3 + (dict(weight=0.16, muscle=0.14),) * 3 + (dict(weight=0.05, muscle=0.03),) * 4
LEG_K = (dict(weight=0.26, muscle=0.10, hips=0.08),) * 2 + (dict(weight=0.26, muscle=0.10),) * 2 + (dict(weight=0.15, muscle=0.08),) + (dict(weight=0.16, muscle=0.14),) * 3 + (dict(weight=0.06),) * 2


def _k(d: dict, coef: dict) -> float:
    return 1.0 + sum(c * d[name] for name, c in coef.items())


def body_params(base: BodyBase | str, sliders: dict | None = None) -> dict:
    base = BodyBase(base).value
    ref = REF[base]
    d = {k: (sliders or {}).get(k, 0.5) - 0.5 for k in SLIDERS}
    torso = np.array(ref["torso"])
    for i, name in enumerate(STATIONS):
        for col, coef in zip((1, 2, 3), TORSO_K[name]):
            torso[i, col] *= _k(d, coef)
    ankle = np.array(ref["ankle"])
    y_hip, y_nb = torso[0, 0], torso[6, 0]
    # longer legs shorten the torso so overall height stays put
    dl = (y_hip - ankle[1]) * 0.12 * d["leg_length"]

    def remap(y):
        return y + dl * np.clip((y_nb - y) / (y_nb - y_hip), 0.0, 1.0)

    torso[:, 0] = remap(torso[:, 0])
    arm = np.array(ref["arm"])
    arm[:, 1:] *= np.array([_k(d, c) for c in ARM_K])[:, None]
    leg = np.array(ref["leg"])
    leg[:, 1:] *= np.array([_k(d, c) for c in LEG_K])[:, None]
    lobe = np.array(ref["lobe"])
    lobe[0] *= _k(d, dict(chest=1.0, weight=0.3, muscle=0.8 if base == "masc" else 0.0))
    lobe[1] = remap(lobe[1])
    return {
        "base": base,
        "crotch": ref["crotch"] + dl,
        "torso": torso,
        "head": np.array(ref["head"]),
        "lobe": lobe,
        # dropped by the root radius, the arm cap's top meets the shoulder ring's widest point: no step either way
        "shoulder_joint": np.array([torso[5, 1], torso[5, 0] - arm[0, 1], torso[5, 4]]),
        "arm": arm,
        "arm_marks": np.array(ref["arm_marks"]),
        "hip_joint": np.array([ref["hip_x"] * _k(d, dict(weight=0.08, hips=0.10)), torso[0, 0] - 0.045, 0.0]),
        "ankle": ankle,
        "leg": leg,
        "foot": np.array(ref["foot"]),
        "foot_ends": np.array(ref["foot_ends"]),
        "scale": np.array([1 + 0.09 * d["height"], 1 + 0.18 * d["height"], 1 + 0.09 * d["height"]]),
    }
