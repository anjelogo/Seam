"""Listing photos + tags -> a PatternSpec (fabric pattern in real cm), via Claude."""

from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pydantic import ValidationError

from drape._repo import DRAPE, bootstrap

bootstrap()

from drape.params import photo_block  # noqa: E402
from drape.patternspec import (  # noqa: E402
    PatternKind,
    PatternSpec,
    PlacementPanel,
    StripeDirection,
    TrimKind,
)
from drape.size_body import CHART  # noqa: E402

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 4096
PHOTO_MAX = 1024
PRICE_IN, PRICE_OUT = 3.0 / 1e6, 15.0 / 1e6

PROMPTS = Path(__file__).resolve().parent / "prompts"

BOTTOM_CATEGORIES = {"pants", "jeans", "cargo", "shorts", "skirt"}
LETTER_TO_WAIST = {"XS": "W26", "S": "W28", "M": "W32", "L": "W34", "XL": "W36", "XXL": "W38"}
TOP_LETTERS = {"XS", "S", "M", "L", "XL", "XXL"}
MIN_PERIOD_PX = 3.0
FFT_MIN_PROFILES = 5
FFT_PEAK_RATIO = 3.0
FFT_REL_DIFF = 0.30
# the FFT verifies the model's period within this factor; wider peaks are drape folds, not the weave
FFT_WINDOW = 3.0


def _runs(mask_row: np.ndarray) -> list[np.ndarray]:
    idx = np.flatnonzero(mask_row)
    if not len(idx):
        return []
    splits = np.flatnonzero(np.diff(idx) > 1) + 1
    return np.split(idx, splits)


def _run_width(mask_row: np.ndarray, x_center: int | None = None) -> int:
    runs = _runs(mask_row)
    if not runs:
        return 0
    if x_center is None:
        return max(len(r) for r in runs)
    for r in runs:
        if r[0] <= x_center <= r[-1]:
            return len(r)
    return max(len(r) for r in runs)


def measure_waist_px(alpha: np.ndarray) -> tuple[int, int]:
    """Widest contiguous opaque run a little below the top edge (the waistband)."""
    ys, _ = np.nonzero(alpha)
    top, bottom = int(ys.min()), int(ys.max())
    span = max(bottom - top, 1)
    lo, hi = top + max(int(0.02 * span), 1), top + max(int(0.12 * span), 2)
    best_row, best_w = lo, 0
    for row in range(lo, hi + 1):
        w = _run_width(alpha[row])
        if w > best_w:
            best_w, best_row = w, row
    return best_w, best_row


def measure_chest_px(alpha: np.ndarray) -> tuple[int, int]:
    """Torso width at 25-35% of the height: the median centre-anchored run, which skips the sleeves."""
    ys, xs = np.nonzero(alpha)
    top, bottom = int(ys.min()), int(ys.max())
    x_center = int(round((xs.min() + xs.max()) / 2))
    span = max(bottom - top, 1)
    lo, hi = top + int(0.25 * span), top + int(0.35 * span)
    widths, rows = [], []
    for row in range(lo, max(hi, lo + 1) + 1):
        w = _run_width(alpha[row], x_center)
        if w:
            widths.append(w)
            rows.append(row)
    if not widths:
        return 0, lo
    med = float(np.median(widths))
    i = int(np.argmin(np.abs(np.array(widths) - med)))
    return widths[i], rows[i]


def calibrate(item_dir: Path, item: dict) -> dict:
    """Which real-world span to trust, and how many cutout pixels it spans."""
    tags = item.get("tags") or {}
    category = (tags.get("category") or "").strip().lower()
    size = (tags.get("size_normalized") or "").strip().upper()
    alpha = np.asarray(Image.open(item_dir / "cutout.png").convert("RGBA"))[..., 3] > 127

    if category in BOTTOM_CATEGORIES:
        waist_size = LETTER_TO_WAIST.get(size, size if size.startswith("W") else "W32")
        row_cm = CHART.get(("bottom", waist_size), CHART[("bottom", "W32")])
        ref, used_size = "waist", waist_size
        ref_px, row = measure_waist_px(alpha)
    else:
        chest_size = size if size in TOP_LETTERS else "M"
        row_cm = CHART.get(("top", chest_size), CHART[("top", "M")])
        ref, used_size = "chest", chest_size
        ref_px, row = measure_chest_px(alpha)

    ref_cm = row_cm[0] / 2
    px_per_cm = ref_px / ref_cm if ref_cm and ref_px else 0.0
    return {
        "ref": ref, "size": used_size, "ref_cm": round(ref_cm, 2),
        "ref_px": int(ref_px), "row": int(row), "px_per_cm": round(px_per_cm, 3),
    }


def calib_text(calib: dict) -> str:
    return (
        f"Based on size {calib['size']}, the garment's {calib['ref']} laid flat is ~{calib['ref_cm']:.1f} cm "
        f"across. In Image 1 (the cutout) that span measures {calib['ref_px']} px (row {calib['row']}), so "
        f"1 cm \u2248 {calib['px_per_cm']:.2f} px there. Use this scale to convert what you measure in the "
        f"photos into period_cm, line_width_cm, widths_cm and gap_cm."
    )


def cutout_block(item_dir: Path) -> dict:
    im = Image.open(item_dir / "cutout.png").convert("RGBA")
    bg = Image.new("RGB", im.size, (128, 128, 128))
    bg.paste(im, mask=im.split()[3])
    bg.thumbnail((PHOTO_MAX, PHOTO_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=88)
    data = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def photo_paths(item_dir: Path) -> list[Path]:
    photos_dir = item_dir / "photos"
    if photos_dir.is_dir():
        hits = sorted(photos_dir.glob("*.jpg"))
        if hits:
            return hits
    return [item_dir / "photo.jpg"]


def image_blocks(item_dir: Path) -> tuple[list[dict], list[str]]:
    blocks = [cutout_block(item_dir)]
    names = ["Image 1: cutout.png (garment on mid grey - placement boxes are fractions of this image)"]
    for i, p in enumerate(photo_paths(item_dir), start=2):
        blocks.append(photo_block(p))
        names.append(f"Image {i}: {p.name} (listing photo)")
    return blocks, names


def user_prompt(item: dict, calib: dict, image_names: list[str]) -> str:
    listing = item.get("listing") or {}
    tags = item.get("tags") or {}
    colors = tags.get("colors") or []
    fields = {
        "TITLE": (listing.get("title") or "").strip() or "untitled",
        "DESCRIPTION": (listing.get("description") or "").strip() or "none",
        "CATEGORY": tags.get("category") or "unknown",
        "PATTERN": tags.get("pattern") or "unknown",
        "COLORS": ", ".join(f"{c['name']} ({c['hex']}, {c['ratio']:.0%})" for c in colors) or "unknown",
        "MATERIAL": tags.get("material") or "unknown",
        "FIT": tags.get("fit") or "unknown",
        "STYLE_TAGS": ", ".join(tags.get("style_tags") or []) or "none",
        "SIZE_RAW": listing.get("size_raw") or "unknown",
        "SIZE_NORMALIZED": tags.get("size_normalized") or "unknown",
        "IMAGES": "\n".join(f"- {n}" for n in image_names),
        "CALIB": calib_text(calib),
    }
    text = (PROMPTS / "spec_user.md").read_text()
    for key, val in fields.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def _inline_refs(schema: dict) -> dict:
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                target = resolve(copy.deepcopy(defs[name]))
                extra = {k: resolve(v) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def tool_definition() -> dict:
    return {
        "name": "emit_pattern_spec",
        "description": "Emit the PatternSpec describing this garment's fabric pattern.",
        "input_schema": _inline_refs(PatternSpec.model_json_schema()),
    }


def semantic_errors(spec: PatternSpec) -> list[str]:
    errors = []
    for i, r in enumerate(spec.repeats):
        if r.line_width_cm >= r.period_cm:
            errors.append(f"repeats[{i}]: line_width_cm ({r.line_width_cm}) must be < period_cm ({r.period_cm})")
    for i, t in enumerate(spec.trims):
        if t.kind in (TrimKind.stripe, TrimKind.piping, TrimKind.binding) and not t.widths_cm:
            errors.append(f"trims[{i}]: kind={t.kind.value} needs non-empty widths_cm")
    for i, pl in enumerate(spec.placements):
        x0, y0, x1, y1 = pl.box
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            errors.append(f"placements[{i}]: box {pl.box} must satisfy 0<=x0<x1<=1 and 0<=y0<y1<=1")
        if pl.panel == PlacementPanel.back:
            errors.append(f"placements[{i}]: panel=back is never allowed (no back photo was provided)")
    needs_repeats = spec.kind in (PatternKind.stripes, PatternKind.pinstripes, PatternKind.plaid)
    if needs_repeats and not spec.repeats:
        errors.append(f"kind={spec.kind.value} requires a non-empty repeats list")
    if not needs_repeats and spec.repeats:
        errors.append(f"kind={spec.kind.value} must have an empty repeats list")
    return errors


def ask(safe: str, blocks: list[dict], prompt: str) -> dict:
    import anthropic

    system = (PROMPTS / "spec_system.md").read_text()
    tool = tool_definition()
    messages: list[dict] = [{"role": "user", "content": [*blocks, {"type": "text", "text": prompt}]}]

    client = anthropic.Anthropic()
    start = time.perf_counter()
    in_tok = out_tok = 0
    spec, errors, retried = None, [], False
    for attempt in (0, 1):
        msg = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages,
            tools=[tool], tool_choice={"type": "tool", "name": "emit_pattern_spec"},
        )
        u = msg.usage
        in_tok += u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
        out_tok += u.output_tokens
        tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
        if tool_use is None:
            spec, errors = None, ["no tool_use block in the reply"]
        else:
            try:
                spec = PatternSpec.model_validate(tool_use.input)
                errors = semantic_errors(spec)
            except ValidationError as e:
                spec, errors = None, [str(e)]
        if not errors:
            break
        if attempt:
            if spec is None:
                raise SystemExit(f"{safe}: model did not return a valid PatternSpec after one retry: {errors}")
            break
        retried = True
        messages += [
            {"role": "assistant", "content": msg.content},
            {"role": "user", "content": "This PatternSpec was rejected:\n" + "\n".join(errors)
             + "\n\nCall emit_pattern_spec again with a corrected, complete PatternSpec."},
        ]
    return {
        "spec": spec, "errors": errors, "retried": retried,
        "input_tokens": in_tok, "output_tokens": out_tok,
        "wall_seconds": round(time.perf_counter() - start, 2),
    }


def _lum_alpha(item_dir: Path) -> tuple[np.ndarray, np.ndarray, str]:
    albedo = item_dir / "albedo.png"
    source = "albedo" if albedo.exists() else "cutout"
    im = np.asarray(Image.open(albedo if source == "albedo" else item_dir / "cutout.png").convert("RGBA"))
    lum = im[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    alpha = im[..., 3] > 127
    return lum, alpha, source


def _profiles(lum: np.ndarray, alpha: np.ndarray, direction: str) -> list[np.ndarray]:
    ys, xs = np.nonzero(alpha)
    top, bottom, left, right = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    profiles = []
    if direction == "grain":
        y0, y1 = top + int(0.2 * (bottom - top)), top + int(0.8 * (bottom - top))
        for y in range(y0, y1 + 1):
            for run in _runs(alpha[y]):
                if len(run) >= 8:
                    profiles.append(lum[y, run[0] : run[-1] + 1])
    else:
        x0, x1 = left + int(0.2 * (right - left)), left + int(0.8 * (right - left))
        for x in range(x0, x1 + 1):
            for run in _runs(alpha[:, x]):
                if len(run) >= 8:
                    profiles.append(lum[run[0] : run[-1] + 1, x])
    return profiles


def _avg_power(profiles: list[np.ndarray]) -> tuple[np.ndarray, int, int]:
    from scipy.signal import detrend

    lens = [len(p) for p in profiles]
    length, med_len = max(lens), int(np.median(lens))
    spectra = []
    for p in profiles:
        # linear detrend (not just mean-subtract) so shading gradients don't swamp the stripe frequency
        w = detrend(p.astype(np.float64), type="linear") * np.hanning(len(p))
        padded = np.zeros(length)
        padded[: len(p)] = w
        spectra.append(np.abs(np.fft.rfft(padded)) ** 2)
    return np.mean(spectra, axis=0), length, med_len


def _dominant_period(avg: np.ndarray, length: int, med_len: int, near_px: float) -> tuple[float | None, float]:
    k = np.arange(len(avg))
    period_px = np.where(k > 0, length / np.maximum(k, 1), np.inf)
    lo, hi = max(MIN_PERIOD_PX, near_px / FFT_WINDOW), min(med_len / 3.0, near_px * FFT_WINDOW)
    valid = (k > 0) & (period_px >= lo) & (period_px <= hi)
    if valid.sum() < 3:
        return None, 0.0
    vals = avg[valid]
    peak = int(np.argmax(vals))
    peak_ratio = float(vals[peak] / max(float(np.median(vals)), 1e-9))
    return float(period_px[valid][peak]), peak_ratio


def fft_check(item_dir: Path, spec: PatternSpec, px_per_cm: float) -> list[dict]:
    if spec.kind not in (PatternKind.stripes, PatternKind.pinstripes, PatternKind.plaid) or px_per_cm <= 0:
        return []
    lum, alpha, source = _lum_alpha(item_dir)
    results = []
    for i, r in enumerate(spec.repeats):
        llm_period = r.period_cm
        if r.direction == StripeDirection.bias:
            results.append({"set": i, "direction": "bias", "source": source, "llm_period_cm": llm_period,
                            "fft_period_cm": None, "peak_ratio": 0.0, "trusted": "llm", "verdict": "skipped (bias)"})
            continue
        direction = r.direction.value
        profiles = _profiles(lum, alpha, direction)
        fft_period_cm, peak_ratio, verdict, trusted = None, 0.0, "fft inconclusive", "llm"
        if len(profiles) >= FFT_MIN_PROFILES:
            avg, length, med_len = _avg_power(profiles)
            period_px, peak_ratio = _dominant_period(avg, length, med_len, llm_period * px_per_cm)
            if period_px is not None:
                fft_period_cm = period_px / px_per_cm
                rel_diff = abs(llm_period - fft_period_cm) / fft_period_cm if fft_period_cm else 0.0
                if peak_ratio >= FFT_PEAK_RATIO and rel_diff > FFT_REL_DIFF:
                    print(f"FFT override {item_dir.name}: llm {llm_period:.2f} cm -> fft {fft_period_cm:.2f} cm")
                    r.period_cm = round(fft_period_cm, 3)
                    if r.line_width_cm >= r.period_cm:
                        r.line_width_cm = round(r.period_cm * 0.3, 3)
                    trusted, verdict = "fft", "fft override"
                elif peak_ratio >= FFT_PEAK_RATIO:
                    verdict = "fft agrees"
        results.append({
            "set": i, "direction": direction, "source": source, "llm_period_cm": round(llm_period, 3),
            "fft_period_cm": round(fft_period_cm, 3) if fft_period_cm is not None else None,
            "peak_ratio": round(peak_ratio, 2), "trusted": trusted, "verdict": verdict,
        })
    return results


def fft_verdict_summary(results: list[dict]) -> str:
    if not results:
        return "n/a"
    if any(r["trusted"] == "fft" for r in results):
        return "override"
    if all(r["fft_period_cm"] is None for r in results):
        return "inconclusive"
    return "agrees"


def load_spec(item_dir: Path) -> PatternSpec:
    return PatternSpec.model_validate_json((item_dir / "spec.json").read_text())


def recheck(item_dir: Path) -> list[dict]:
    """Re-run only the FFT check on a stored spec, starting from the model's own periods."""
    spec, meta = load_spec(item_dir), json.loads((item_dir / "spec_meta.json").read_text())
    for rec in meta.get("fft", []):
        if rec["trusted"] == "fft":
            spec.repeats[rec["set"]].period_cm = rec["llm_period_cm"]
    meta["fft"] = fft_check(item_dir, spec, meta["calibration"]["px_per_cm"])
    (item_dir / "spec.json").write_text(spec.model_dump_json(indent=2))
    (item_dir / "spec_meta.json").write_text(json.dumps(meta, indent=2))
    return meta["fft"]


def process(entry: dict, inputs: Path, force: bool) -> dict | None:
    item_dir = inputs / entry["safe"]
    if (item_dir / "spec.json").exists() and not force:
        return None
    item = json.loads((item_dir / "item.json").read_text())
    calib = calibrate(item_dir, item)
    blocks, names = image_blocks(item_dir)
    prompt = user_prompt(item, calib, names)
    result = ask(entry["safe"], blocks, prompt)
    spec = result["spec"]
    fft_results = fft_check(item_dir, spec, calib["px_per_cm"])

    (item_dir / "spec.json").write_text(spec.model_dump_json(indent=2))
    cost = result["input_tokens"] * PRICE_IN + result["output_tokens"] * PRICE_OUT
    meta = {
        "model": MODEL, "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"],
        "cost_usd": round(cost, 4), "wall_seconds": result["wall_seconds"], "retried": result["retried"],
        "errors": result["errors"], "calibration": calib, "fft": fft_results, "back_photo": False,
        "photos": [p.name for p in photo_paths(item_dir)],
    }
    (item_dir / "spec_meta.json").write_text(json.dumps(meta, indent=2))
    return {"safe": entry["safe"], "spec": spec, "meta": meta, "cost": cost, "fft": fft_results}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", default=str(DRAPE / "runs/inputs"), help="directory holding manifest.json")
    p.add_argument("--only", metavar="SAFE", help="process just this manifest item")
    p.add_argument("--force", action="store_true", help="rebuild spec.json even if it already exists")
    p.add_argument("--recheck", action="store_true", help="only re-run the FFT check on existing specs (no Claude)")
    a = p.parse_args()

    inputs = Path(a.inputs)
    entries = json.loads((inputs / "manifest.json").read_text())["items"]
    if a.only:
        entries = [e for e in entries if e["safe"] == a.only or e["id"] == a.only]
        if not entries:
            raise SystemExit(f"no manifest item matches {a.only!r}")

    if a.recheck:
        for e in entries:
            res = recheck(inputs / e["safe"])
            print(f"{e['safe']} | fft {fft_verdict_summary(res)} | " + "; ".join(
                f"{r['direction']} llm {r['llm_period_cm']} fft {r['fft_period_cm']} x{r['peak_ratio']} {r['verdict']}"
                for r in res))
        print(f"ok: {len(entries)} specs rechecked")
        return

    total, done = 0.0, 0
    for e in entries:
        r = process(e, inputs, a.force)
        if r is None:
            print(f"{e['safe']} | skip (spec.json exists)")
            continue
        total += r["cost"]
        spec, meta = r["spec"], r["meta"]
        line = (f"{e['safe']} | {spec.kind.value} | {len(spec.repeats)} repeats | {len(spec.trims)} trims | "
                f"{len(spec.placements)} placements | {meta['calibration']['px_per_cm']:.1f} px/cm | "
                f"fft {fft_verdict_summary(r['fft'])} | ${r['cost']:.4f}")
        if meta["retried"]:
            line += " | retried"
        print(line)
        for err in meta["errors"]:
            print(f"  {err}")
        done += 1
    print(f"ok: {done} specs | ${total:.4f} total")


if __name__ == "__main__":
    main()
