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
