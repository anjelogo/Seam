"""Build a size body: the wearer's measurements with girths overridden from a standard size chart."""

from drape._repo import bootstrap

bootstrap()

import argparse

import yaml

from drape.body import BODIES

# cm. tops: (chest girth, waist girth, body length). bottoms: (waist girth = in x 2.54, hip girth, inseam)
CHART = {
    ("top", "XS"): (84.0, 70.0, 64.0),
    ("top", "S"): (90.0, 76.0, 66.0),
    ("top", "M"): (96.0, 82.0, 68.0),
    ("top", "L"): (104.0, 90.0, 70.0),
    ("top", "XL"): (112.0, 98.0, 72.0),
    ("top", "XXL"): (120.0, 106.0, 74.0),
    ("bottom", "W26"): (66.0, 91.0, 76.0),
    ("bottom", "W28"): (71.1, 96.1, 77.0),
    ("bottom", "W30"): (76.2, 101.7, 78.0),
    ("bottom", "W32"): (81.3, 106.8, 79.0),
    ("bottom", "W34"): (86.4, 112.4, 80.0),
    ("bottom", "W36"): (91.4, 117.9, 81.0),
    ("bottom", "W38"): (96.5, 123.5, 81.0),
    ("bottom", "W40"): (101.6, 129.1, 81.0),
}


BAND_CM = 3.0
CROP_WORDS = ("crop", "cropped")
LENGTH_CATEGORIES = ("tee", "longsleeve")


def chart_length(slot: str, size: str | None) -> float | None:
    row = CHART.get((slot, (size or "").upper()))
    return row[2] if row else None


# mirrors the Shirt torso math (tee.py:34,39,45 over bodice.py:241-243); re-derive if the vendor changes it
def drafted_length_cm(body: dict[str, float], shirt_length: float, shirt_width: float,
                      collar_width_cm: float) -> float:
    import numpy as np

    sh_tan = float(np.tan(np.deg2rad(body["shoulder_incl"])))
    frac = (body["bust"] - body["back_width"]) / 2 / body["bust"]
    half = shirt_width * (body["bust"] - body["back_width"]) / 2
    fb_diff = (frac - (0.5 - frac)) * body["bust"]
    return shirt_length * body["waist_line"] + sh_tan * (half - collar_width_cm / 2 - fb_diff)


def clamp_body_length(values: dict, schema: dict, entry: dict, body: dict[str, float],
                      tags: tuple[str, ...] = ()) -> list[str]:
    from drape.params import _current, _fmt, width_cm

    path = "shirt.length"
    if path not in schema or _current(values, schema, "meta.upper") != "Shirt":
        return []
    if (entry.get("category") or "").strip().lower() not in LENGTH_CATEGORIES:
        return []
    size = (entry.get("size_normalized") or "").strip().upper()
    target = chart_length("top", size)
    if target is None:
        return []
    text = " ".join([entry.get("title") or "", entry.get("fit") or "", *tags]).lower()
    if any(w in text for w in CROP_WORDS):
        return [f"SKIP {path} (listing says cropped, chart {target:.1f}cm not the intent)"]

    sized = resize(body, "top", size)
    node = schema[path]
    cur = float(_current(values, schema, path))
    collar = width_cm(float(_current(values, schema, "collar.width")),
                      sized["neck_w"], sized["shoulder_w"] - 4.0)
    width = float(_current(values, schema, "shirt.width"))
    cm = drafted_length_cm(sized, cur, width, collar)
    lo, hi = target - BAND_CM, target + BAND_CM
    if lo - 1e-3 <= cm <= hi + 1e-3:
        return []
    want = min(max(cm, lo), hi)
    adj = cm - cur * sized["waist_line"]
    frac = round(min(max((want - adj) / sized["waist_line"], float(node["range"][0])),
                     float(node["range"][-1])), 6)
    got = drafted_length_cm(sized, frac, width, collar)
    values[path] = frac
    verb = "CLAMP" if abs(got - want) <= 1e-3 else "UNREACHABLE"
    return [f"{verb} {path} {_fmt(cur)}->{_fmt(frac)} ({size or 'unsized'} body length "
            f"{cm:.2f}cm->{got:.2f}cm, band {lo:.2f}-{hi:.2f}cm, slope +{adj:.2f}cm)"]


def clamp_design_for_size(design: dict, item: dict, size: str, wearer_yaml) -> list[str]:
    from drape.params import leaves, load_design, slice_schema

    tags = item.get("tags") or {}
    entry = {
        "size_normalized": size,
        "category": tags.get("category"),
        "fit": tags.get("fit"),
        "title": (item.get("listing") or {}).get("title"),
    }
    schema = slice_schema(load_design(), "upper")
    values = {p: n["v"] for p, n in leaves(design).items() if p in schema}
    body = yaml.safe_load(open(wearer_yaml).read())["body"]
    extra = tuple(t for t in (*(tags.get("style_tags") or []), tags.get("era")) if t)
    notes = clamp_body_length(values, schema, entry, body, extra)
    if notes and "shirt.length" in values:
        design["shirt"]["length"]["v"] = values["shirt.length"]
    return notes


def resize(body: dict[str, float], slot: str, size: str | None) -> dict[str, float]:
    row = CHART.get((slot, (size or "").upper()))
    if row is None:
        return dict(body)
    if slot == "top":
        chest, waist, _ = row
        k_bust = chest / body["bust"]
        k_waist = waist / body["waist"]
        k_hips = k_waist
    else:
        waist, hips, _ = row
        k_waist = waist / body["waist"]
        k_hips = hips / body["hips"]
        k_bust = k_waist
    scale = {
        "bust": k_bust, "underbust": k_bust, "back_width": k_bust, "shoulder_w": k_bust,
        "waist": k_waist, "waist_back_width": k_waist,
        "hips": k_hips, "hip_back_width": k_hips, "leg_circ": k_hips,
    }
    return {k: round(v * scale[k], 4) if k in scale else v for k, v in body.items()}


def build(wearer: str, slot: str, size: str | None, name: str) -> dict[str, float]:
    body = yaml.safe_load((BODIES / f"{wearer}.yaml").read_text())["body"]
    sized = resize(body, slot, size)
    (BODIES / f"{name}.yaml").write_text(yaml.safe_dump({"body": sized}, sort_keys=True))
    return sized


def main() -> None:
    ap = argparse.ArgumentParser(description="derive a size body from a wearer body")
    ap.add_argument("--wearer", required=True)
    ap.add_argument("--slot", default="top", choices=("top", "bottom"))
    ap.add_argument("--size", default=None, help="XS..XXL for tops, W26..W40 for bottoms")
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    size = (args.size or "").upper() or None
    name = args.name or f"size_{args.slot}_{size or 'wearer'}"
    before = yaml.safe_load((BODIES / f"{args.wearer}.yaml").read_text())["body"]
    after = build(args.wearer, args.slot, size, name)
    if (args.slot, size or "") not in CHART:
        print(f"no chart entry for {args.slot} {size}: using the wearer body unchanged")
    print(f"wrote {BODIES}/{name}.yaml")
    for key in after:
        if after[key] != before[key]:
            print(f"  {key:22s} {before[key]:8.2f} -> {after[key]:8.2f}")


if __name__ == "__main__":
    main()
