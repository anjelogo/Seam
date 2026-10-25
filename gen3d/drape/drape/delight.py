"""Strip baked shading (lighting gradients, broad wrinkle shading) off a garment cutout, hue untouched."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from drape._repo import DRAPE, bootstrap

bootstrap()

LUMA = np.array([0.2126, 0.7152, 0.0722])
RADIUS_FRAC = 0.06
EPS = 1.0
Y_EPS = 0.01  # additive luma floor: near-black 8-bit quantization explodes in log space otherwise
GAIN_LO, GAIN_HI = 0.5, 2.0
SAT_T, VAL_T = 0.15, 0.1
WRINKLE_RATIO, WRINKLE_FLOOR = 0.6, 0.02
HUE_MEAN_LIMIT = 2.0
CLIP_LIMIT = 1.0
PREVIEW_PX = 512
GREY = np.array([128.0, 128.0, 128.0])


def srgb_to_linear(u8: np.ndarray) -> np.ndarray:
    x = u8.astype(np.float64) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.maximum(x, 0.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def rgb_to_hsv(rgb01: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r, g, b = rgb01[..., 0], rgb01[..., 1], rgb01[..., 2]
    maxc, minc = rgb01.max(-1), rgb01.min(-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc > 0, delta / np.where(maxc == 0, 1, maxc), 0.0)
    safe = np.where(delta == 0, 1, delta)
    rc, gc, bc = (maxc - r) / safe, (maxc - g) / safe, (maxc - b) / safe
    is_r = (maxc == r) & (delta != 0)
    is_g = (maxc == g) & (delta != 0) & ~is_r
    is_b = (delta != 0) & ~is_r & ~is_g
    h = np.zeros_like(maxc)
    h[is_r] = bc[is_r] - gc[is_r]
    h[is_g] = 2.0 + rc[is_g] - bc[is_g]
    h[is_b] = 4.0 + gc[is_b] - rc[is_b]
    return (h / 6.0) % 1.0, s, v


def box_norm(x: np.ndarray, mask_f: np.ndarray, size: int) -> np.ndarray:
    """Box filter that only ever averages over mask pixels."""
    num = ndimage.uniform_filter(x * mask_f, size=size, mode="nearest")
    den = ndimage.uniform_filter(mask_f, size=size, mode="nearest")
    return num / np.maximum(den, 1e-6)


def guided_base(logy: np.ndarray, mask_f: np.ndarray, size: int, eps: float) -> np.ndarray:
    """Self-guided filter (He et al.) on log luma: smooths flat shading, keeps print and stripe edges."""
    mean_i = box_norm(logy, mask_f, size)
    var_i = box_norm(logy * logy, mask_f, size) - mean_i * mean_i
    a = var_i / (var_i + eps)
    b = mean_i * (1 - a)
    return box_norm(a, mask_f, size) * logy + box_norm(b, mask_f, size)


def shading_base(rgb_u8: np.ndarray, mask_f: np.ndarray, size: int) -> np.ndarray:
    linear = srgb_to_linear(rgb_u8)
    y = linear @ LUMA
    logy = np.log(y + Y_EPS)
    return guided_base(logy, mask_f, size, EPS)


def delight(rgba: np.ndarray) -> tuple[np.ndarray, dict]:
    albedo, info, _ = _delight(rgba)
    return albedo, info


def _delight(rgba: np.ndarray) -> tuple[np.ndarray, dict, np.ndarray]:
    alpha = rgba[..., 3]
    mask = alpha > 127
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("no opaque pixels")
    width = int(xs.max() - xs.min() + 1)
    r = max(int(round(RADIUS_FRAC * width)), 3)
    size = 2 * r + 1
    mask_f = mask.astype(np.float64)

    base_before = shading_base(rgba[..., :3], mask_f, size)
    med = float(np.median(base_before[mask]))
    gain = np.clip(np.exp(med - base_before), GAIN_LO, GAIN_HI)

    linear = srgb_to_linear(rgba[..., :3])
    srgb_out = linear_to_srgb(linear * gain[..., None])
    clipped = (srgb_out < 0) | (srgb_out > 1)
    out_rgb = np.where(mask[..., None], np.round(np.clip(srgb_out, 0, 1) * 255), rgba[..., :3])
    albedo = np.dstack([out_rgb, alpha]).astype(np.uint8)

    base_after = shading_base(albedo[..., :3], mask_f, size)

    h0, s0, v0 = rgb_to_hsv(rgba[..., :3].astype(np.float64) / 255.0)
    h1, _, _ = rgb_to_hsv(albedo[..., :3].astype(np.float64) / 255.0)
    dh = np.abs(h0 - h1) * 360
    dh = np.minimum(dh, 360 - dh)
    sel = mask & (s0 > SAT_T) & (v0 > VAL_T)
    hue_max = float(dh[sel].max()) if sel.any() else 0.0
    hue_mean = float(dh[sel].mean()) if sel.any() else 0.0

    info = {
        "method": "guided-self-log-luma",
        "radius_px": r,
        "garment_width_px": width,
        "eps": EPS,
        "median_luma": round(med, 4),
        "wrinkle_score_before": round(float(base_before[mask].std()), 4),
        "wrinkle_score_after": round(float(base_after[mask].std()), 4),
        "hue_shift_deg_max": round(hue_max, 3),
        "hue_shift_deg_mean": round(hue_mean, 3),
        "clip_pct": round(100.0 * clipped.any(-1)[mask].mean(), 3),
    }
    return albedo, info, gain


def flatten_grey(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4] / 255
    return np.round(rgba[..., :3] * a + GREY * (1 - a)).astype(np.uint8)


def make_preview(cutout: np.ndarray, albedo: np.ndarray, gain: np.ndarray, mask: np.ndarray) -> Image.Image:
    before = Image.fromarray(flatten_grey(cutout)).resize((PREVIEW_PX, PREVIEW_PX), Image.Resampling.LANCZOS)
    after = Image.fromarray(flatten_grey(albedo)).resize((PREVIEW_PX, PREVIEW_PX), Image.Resampling.LANCZOS)
    gain_u8 = np.clip((gain - GAIN_LO) / (GAIN_HI - GAIN_LO) * 255, 0, 255).astype(np.uint8)
    gain_rgb = np.where(mask[..., None], gain_u8[..., None], 128).astype(np.uint8).repeat(3, -1)
    gainimg = Image.fromarray(gain_rgb).resize((PREVIEW_PX, PREVIEW_PX), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (PREVIEW_PX * 3, PREVIEW_PX), (128, 128, 128))
    for i, panel in enumerate((before, after, gainimg)):
        canvas.paste(panel, (i * PREVIEW_PX, 0))
    return canvas


def item_dirs(inputs: Path, only: str | None = None) -> list[Path]:
    out = []
    for d in sorted(p for p in inputs.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        if (d / "item.json").exists() and (d / "cutout.png").exists():
            out.append(d)
    return out


def process_item(d: Path) -> dict:
    cutout = np.asarray(Image.open(d / "cutout.png").convert("RGBA"))
    albedo, info, gain = _delight(cutout)
    mask = cutout[..., 3] > 127
    Image.fromarray(albedo).save(d / "albedo.png")
    (d / "delight.json").write_text(json.dumps(info, indent=2))
    make_preview(cutout, albedo, gain, mask).save(d / "delight_preview.png")
    return info


def verify_item(d: Path) -> list[str]:
    info = json.loads((d / "delight.json").read_text())
    cutout = np.asarray(Image.open(d / "cutout.png").convert("RGBA"))
    albedo = np.asarray(Image.open(d / "albedo.png").convert("RGBA"))
    problems = []
    before, after = info["wrinkle_score_before"], info["wrinkle_score_after"]
    if before >= WRINKLE_FLOOR and after > WRINKLE_RATIO * before:
        problems.append(f"wrinkle {before:.4f} -> {after:.4f} (want <= {WRINKLE_RATIO * before:.4f})")
    if info["hue_shift_deg_mean"] >= HUE_MEAN_LIMIT:
        problems.append(f"hue_shift_deg_mean {info['hue_shift_deg_mean']:.2f} >= {HUE_MEAN_LIMIT}")
    if info["clip_pct"] >= CLIP_LIMIT:
        problems.append(f"clip_pct {info['clip_pct']:.2f} >= {CLIP_LIMIT}")
    if not np.array_equal(cutout[..., 3], albedo[..., 3]):
        problems.append("alpha changed")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--only")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    dirs = item_dirs(a.inputs, a.only)
    if not dirs:
        raise SystemExit(f"no items with item.json + cutout.png under {a.inputs}")

    if a.verify:
        bad = 0
        for d in dirs:
            problems = verify_item(d)
            status = "FAIL " + "; ".join(problems) if problems else "pass"
            print(f"{d.name} | {status}")
            bad += bool(problems)
        print(f"ok: {len(dirs) - bad}/{len(dirs)} pass verify" if not bad else f"FAILED: {bad}/{len(dirs)}")
        if bad:
            raise SystemExit(1)
        return

    for d in dirs:
        info = process_item(d)
        print(f"{d.name} | r={info['radius_px']} px | wrinkle {info['wrinkle_score_before']:.4f} -> "
              f"{info['wrinkle_score_after']:.4f} | hue {info['hue_shift_deg_mean']:.2f} deg | "
              f"clip {info['clip_pct']:.2f}%")
    print(f"ok: {len(dirs)} albedos")


if __name__ == "__main__":
    main()
