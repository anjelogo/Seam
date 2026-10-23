"""Listing photo + tags -> a complete GarmentCode design-params tree, via Claude."""

from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 4096
PHOTO_MAX = 1024
PRICE_IN, PRICE_OUT = 3.0 / 1e6, 15.0 / 1e6
RETRY_INVALID_FRAC = 0.2

PROMPTS = Path(__file__).resolve().parent / "prompts"
FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

SECTIONS = {
    "upper": ("meta", "shirt", "collar", "sleeve", "left"),
    "bottom": ("meta", "pants", "waistband"),
    "skirt": ("meta", "waistband", "skirt", "flare-skirt", "godet-skirt", "pencil-skirt", "levels-skirt"),
}
SLOT_RULE = {
    "upper": "set meta.upper, keep meta.bottom null, and set meta.wb only if this top has a separate waistband band.",
    "bottom": "set meta.bottom, keep meta.upper null; meta.wb adds a separate waistband band on top of the pants.",
    "skirt": "set meta.bottom to the skirt style, keep meta.upper null; meta.wb adds a separate waistband band.",
}
# slot -> (the meta path that must be non-null for the garment to assemble, fallback value)
MAIN = {"upper": ("meta.upper", "Shirt"), "bottom": ("meta.bottom", "Pants"), "skirt": ("meta.bottom", "PencilSkirt")}
NULLED = {"upper": ("meta.bottom",), "bottom": ("meta.upper",), "skirt": ("meta.upper",)}

# Neckline depth prior, in cm of front/back neck drop below the neck base.
NECK_CM = {"crew": (7.0, 10.0), "scoop": (10.0, 14.0), "vneck": (12.0, 20.0), "hoodie": (6.0, 9.0)}
BACK_NECK_CM = (1.5, 3.0)
SIZE_LADDER = ("XS", "S", "M", "L", "XL", "XXL")
VNECK_SHAPES = {"VNeckHalf", "TrapezoidNeckHalf"}
SCOOP_SHAPES = {"CurvyNeckHalf", "CircleArcNeckHalf", "Bezier2NeckHalf"}
WEARER = "wearer_masc"

ROLE_SLOT = {"hoodie": "upper", "tee": "upper", "sweats": "bottom", "jeans": "bottom"}
CATEGORY_SLOT = {
    "hoodie": "upper", "sweatshirt": "upper", "tee": "upper", "shirt": "upper", "longsleeve": "upper",
    "sweater": "upper", "knit": "upper", "top": "upper", "tank": "upper", "jacket": "upper", "coat": "upper",
    "pants": "bottom", "jeans": "bottom", "cargo": "bottom", "shorts": "bottom", "joggers": "bottom",
    "skirt": "skirt",
}


def slot_of(role: str | None, category: str | None) -> str:
    return ROLE_SLOT.get(role or "") or CATEGORY_SLOT.get(category or "") or "upper"


def schema_file() -> Path:
    from drape._repo import GC

    return GC / "assets" / "design_params" / "default.yaml"


def load_design() -> dict:
    import yaml

    return yaml.safe_load(schema_file().read_text())["design"]


def _is_leaf(node: Any) -> bool:
    return isinstance(node, dict) and "v" in node and isinstance(node.get("type"), str)


def leaves(tree: dict, prefix: str = "") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, node in tree.items():
        path = f"{prefix}{key}"
        if _is_leaf(node):
            out[path] = node
        elif isinstance(node, dict):
            out.update(leaves(node, path + "."))
    return out


def _fmt(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render_schema(schema: dict[str, dict]) -> str:
    lines = []
    for path, node in schema.items():
        t = node["type"]
        if t.startswith("select"):
            lines.append(f"{path}: select one-of [{', '.join(_fmt(o) for o in node['range'])}] default {_fmt(node['v'])}")
        elif t == "bool":
            lines.append(f"{path}: bool default {_fmt(node['v'])}")
        else:
            lo, hi = node["range"][0], node["range"][-1]
            lines.append(f"{path}: {t} [{_fmt(lo)}, {_fmt(hi)}] default {_fmt(node['v'])}")
    return "\n".join(lines)


def slice_schema(design: dict, slot: str) -> dict[str, dict]:
    keep = SECTIONS[slot]
    return leaves({k: v for k, v in design.items() if k in keep})


def _as_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and val in (0, 1):
        return bool(val)
    if isinstance(val, str) and val.strip().lower() in ("true", "false", "yes", "no", "1", "0"):
        return val.strip().lower() in ("true", "yes", "1")
    raise ValueError("not a boolean")


def _as_null(val: Any) -> bool:
    return val is None or (isinstance(val, str) and val.strip().lower() in ("null", "none", ""))


def validate(raw: dict[str, Any], schema: dict[str, dict]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Returns the usable values plus the clamp and invalid log lines; anything invalid keeps its default."""
    values: dict[str, Any] = {}
    clamps: list[str] = []
    invalid: list[str] = []
    for path, val in raw.items():
        node = schema.get(path)
        if node is None:
            invalid.append(f"INVALID {path}: not a parameter of this garment")
            continue
        t = node["type"]
        try:
            if t in ("float", "int"):
                lo, hi = float(node["range"][0]), float(node["range"][-1])
                num = float(val)
                clamped = min(max(num, lo), hi)
                clamped = int(round(clamped)) if t == "int" else float(clamped)
                if abs(float(clamped) - num) > 1e-9:
                    clamps.append(f"CLAMP {path} {_fmt(num)}->{_fmt(clamped)}")
                values[path] = clamped
            elif t == "bool":
                values[path] = _as_bool(val)
            else:
                opts = node["range"]
                v = None if _as_null(val) else val
                if v not in opts:
                    raise ValueError(f"not one of {[_fmt(o) for o in opts]}")
                values[path] = v
        except (TypeError, ValueError) as e:
            invalid.append(f"INVALID {path}={val!r}: {e}")
    return values, clamps, invalid


def size_factor(size: str | None) -> float:
    try:
        i = SIZE_LADDER.index((size or "").strip().upper())
    except ValueError:
        return 1.0
    return 0.9 + 0.2 * i / (len(SIZE_LADDER) - 1)


@lru_cache(maxsize=None)
def bust_line(wearer: str = WEARER) -> float:
    """cm the collar depth fractions are measured against (GarmentCode body_params.py:25-29)."""
    import yaml

    from drape._repo import RUNS

    path = RUNS / "bodies" / f"{wearer}.yaml"
    if not path.exists():
        path = schema_file().parent.parent / "bodies" / "mean_all.yaml"
    body = yaml.safe_load(path.read_text())["body"]
    if "vert_bust_line" in body:
        return (1 - 1 / 3) * body["vert_bust_line"] + 1 / 3 * body["bust_line"]
    return float(body["bust_line"])


def _current(values: dict[str, Any], schema: dict[str, dict], path: str) -> Any:
    return values[path] if path in values else (schema[path]["v"] if path in schema else None)


def neckline_kind(values: dict[str, Any], schema: dict[str, dict], entry: dict) -> str:
    style = str(_current(values, schema, "collar.component.style") or "")
    tags = f"{entry.get('role') or ''} {entry.get('category') or ''}".lower()
    if "hood" in style.lower() or "hoodie" in tags:
        return "hoodie"
    shape = _current(values, schema, "collar.f_collar")
    if shape in VNECK_SHAPES:
        return "vneck"
    if shape in SCOOP_SHAPES:
        return "scoop"
    return "crew"


def clamp_neckline(values: dict[str, Any], schema: dict[str, dict], slot: str, entry: dict) -> list[str]:
    """Hold the neck drop inside the prior for this neckline and size, working in cm."""
    if slot != "upper" or "collar.fc_depth" not in schema:
        return []
    bl = bust_line()
    kind = neckline_kind(values, schema, entry)
    size = (entry.get("size_normalized") or "").strip().upper()
    scale = size_factor(size)
    notes = []
    for path, band, side, scaled in (
        ("collar.fc_depth", NECK_CM[kind], "front", True),
        ("collar.bc_depth", BACK_NECK_CM, "back", False),
    ):
        node = schema[path]
        lo, hi = (band[0] * scale, band[1] * scale) if scaled else band
        cur = float(_current(values, schema, path))
        cm = cur * bl
        if lo - 1e-3 <= cm <= hi + 1e-3:
            continue
        want = min(max(cm, lo), hi)
        frac = round(min(max(want / bl, float(node["range"][0])), float(node["range"][-1])), 6)
        got = frac * bl
        values[path] = frac
        verb = "CLAMP" if abs(got - want) <= 1e-3 else "UNREACHABLE"
        notes.append(f"{verb} {path} {_fmt(cur)}->{_fmt(frac)} ({kind} {size or 'unsized'} {side} "
                     f"{cm:.2f}cm->{got:.2f}cm, band {lo:.2f}-{hi:.2f}cm)")
    return notes


def enforce_slot(values: dict[str, Any], slot: str) -> list[str]:
    """The composition the slot demands, whatever the model said."""
    forced = []
    for path in NULLED[slot]:
        if values.get(path) is not None:
            forced.append(f"FORCE {path} {_fmt(values.get(path))}->null")
        values[path] = None
    path, fallback = MAIN[slot]
    if values.get(path) is None:
        forced.append(f"FORCE {path} null->{fallback}")
        values[path] = fallback
    return forced


def merge(design: dict, values: dict[str, Any]) -> dict:
    out = copy.deepcopy(design)
    for path, val in values.items():
        node = out
        *parents, last = path.split(".")
        for key in parents:
            node = node[key]
        node[last]["v"] = val
    return out


def _flatten_response(data: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in data.items():
        path = f"{prefix}{key}"
        if isinstance(val, dict) and not _is_leaf(val):
            out.update(_flatten_response(val, path + "."))
        elif isinstance(val, dict):
            out[path] = val.get("v")
        else:
            out[path] = val
    return out


def parse_json(text: str) -> dict[str, Any]:
    body = text.strip()
    fenced = FENCE.search(body)
    if fenced:
        body = fenced.group(1).strip()
    else:
        start, end = body.find("{"), body.rfind("}")
        if start >= 0 and end > start:
            body = body[start : end + 1]
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return _flatten_response(data)


def photo_block(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((PHOTO_MAX, PHOTO_MAX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
    data = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _style_tags(d: Path) -> list[str]:
    try:
        tags = json.loads((d / "item.json").read_text()).get("tags") or {}
    except (OSError, ValueError):
        return []
    extra = [tags.get("era"), tags.get("pattern")]
    return [t for t in [*(tags.get("style_tags") or []), *extra] if t]


def user_prompt(entry: dict, slot: str, schema: dict[str, dict], tags: list[str]) -> str:
    fields = {
        "ROLE": entry.get("role") or "unknown",
        "CATEGORY": entry.get("category") or "unknown",
        "TITLE": (entry.get("title") or "").strip() or "untitled",
        "FIT": entry.get("fit") or "unknown",
        "MATERIAL": entry.get("material") or "unknown",
        "SIZE": entry.get("size_normalized") or "unknown",
        "STYLE_TAGS": ", ".join(tags) or "none",
        "SLOT": slot,
        "SLOT_RULE": SLOT_RULE[slot],
        "SCHEMA": render_schema(schema),
    }
    text = (PROMPTS / "user.md").read_text()
    for key, val in fields.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def ask(entry: dict, item_dir: Path, design: dict) -> dict:
    import anthropic

    slot = slot_of(entry.get("role"), entry.get("category"))
    schema = slice_schema(design, slot)
    prompt = user_prompt(entry, slot, schema, _style_tags(item_dir))
    system = (PROMPTS / "system.md").read_text()
    messages: list[dict] = [{"role": "user", "content": [photo_block(item_dir / "photo.jpg"), {"type": "text", "text": prompt}]}]

    client = anthropic.Anthropic()
    start = time.perf_counter()
    in_tok = out_tok = 0
    text, values, clamps, invalid, retried = "", {}, [], [], False
    for attempt in (0, 1):
        msg = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages)
        text = "".join(b.text for b in msg.content if b.type == "text")
        # the gateway auto-caches: billed input also lives in the cache counters
        u = msg.usage
        in_tok += u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
        out_tok += u.output_tokens
        try:
            raw = parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            raw, errors = None, [f"Your reply was not a single JSON object ({e})."]
        if raw is not None:
            values, clamps, invalid = validate(raw, schema)
            if not invalid or len(invalid) / max(len(raw), 1) <= RETRY_INVALID_FRAC:
                break
            errors = invalid
        if attempt:
            if raw is None:
                raise RuntimeError("model did not return parseable JSON after one retry")
            break
        retried = True
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "These parameters were rejected:\n" + "\n".join(errors)
             + "\n\nReturn the corrected flat JSON object again, complete, using only listed paths, types and ranges. JSON only."},
        ]

    clamps += enforce_slot(values, slot)
    clamps += clamp_neckline(values, schema, slot, entry)
    return {
        "slot": slot, "values": values, "clamps": clamps, "invalid": invalid, "raw": text, "retried": retried,
        "input_tokens": in_tok, "output_tokens": out_tok, "wall_seconds": round(time.perf_counter() - start, 2),
    }


def process(entry: dict, inputs: Path, design: dict) -> dict:
    item_dir = inputs / entry["safe"]
    result = ask(entry, item_dir, design)
    (item_dir / "raw_response.txt").write_text(result["raw"])
    (item_dir / "params.json").write_text(json.dumps(merge(design, result["values"]), indent=2))
    meta = {
        "model": MODEL, "slot": result["slot"], "overrides": len(result["values"]),
        "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"],
        "wall_seconds": result["wall_seconds"], "clamps": result["clamps"], "invalid": result["invalid"],
        "retried": result["retried"],
    }
    (item_dir / "params_meta.json").write_text(json.dumps(meta, indent=2))
    result["cost"] = result["input_tokens"] * PRICE_IN + result["output_tokens"] * PRICE_OUT
    return result


def _set(tree: dict, path: str, val: Any) -> None:
    node = tree
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    node[last]["v"] = val


def reclamp(entry: dict, inputs: Path, design: dict) -> dict | None:
    """Re-apply the neckline prior to an existing params.json, without calling the model."""
    item_dir = inputs / entry["safe"]
    path = item_dir / "params.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    tree = doc["design"] if "design" in doc else doc
    slot = slot_of(entry.get("role"), entry.get("category"))
    schema = slice_schema(design, slot)
    if slot != "upper" or "collar" not in tree or tree["meta"]["upper"]["v"] is None:
        return None
    values = {p: n["v"] for p, n in leaves(tree).items() if p in schema}
    bl = bust_line()
    front, back = "collar.fc_depth", "collar.bc_depth"
    kind = neckline_kind(values, schema, entry)
    meta_path = item_dir / "params_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    was = {p: float(values[p]) for p in (front, back)}
    notes = clamp_neckline(values, schema, slot, entry)
    # an earlier run injected a Turtle rib band into collarless tops; undo it where the log says we did
    if values.get("collar.component.style") == "Turtle" and any(
            n.startswith("NECKBAND") for n in meta.get("clamps") or []):
        depth = schema["collar.component.depth"]["v"]
        notes.append(f"STRIP NECKBAND collar.component.style Turtle->null, "
                     f"depth {_fmt(values.get('collar.component.depth'))}->{_fmt(depth)}")
        values["collar.component.style"] = None
        values["collar.component.depth"] = depth
    for p in (front, back, "collar.component.style", "collar.component.depth"):
        if p in values:
            _set(tree, p, values[p])
    path.write_text(json.dumps(doc, indent=2))

    meta["clamps"] = (meta.get("clamps") or []) + notes
    meta["reclamped"] = True
    meta_path.write_text(json.dumps(meta, indent=2))
    return {
        "safe": entry["safe"], "kind": kind, "size": (entry.get("size_normalized") or "").upper(),
        "front_before_cm": was[front] * bl, "front_after_cm": float(values[front]) * bl,
        "back_before_cm": was[back] * bl, "back_after_cm": float(values[back]) * bl, "notes": notes,
    }


def assemble(name: str, design: dict) -> tuple[int, bool]:
    from assets.bodies.body_params import BodyParameters
    from assets.garment_programs.meta_garment import MetaGarment
    from drape._repo import GC

    body = BodyParameters(str(GC / "assets" / "bodies" / "mean_all.yaml"))
    pattern = MetaGarment(name, body, design).assembly()
    spec = pattern.spec if hasattr(pattern, "spec") else pattern()
    panels = len(spec["pattern"]["panels"])
    return panels, bool(pattern.is_self_intersecting())


def main() -> None:
    from drape._repo import bootstrap

    bootstrap()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", default="runs/inputs", help="directory holding manifest.json (default: runs/inputs)")
    p.add_argument("--only", metavar="SAFE", help="process just this manifest item")
    p.add_argument("--assemble", action="store_true", help="dry-run MetaGarment on each result")
    p.add_argument("--reclamp", action="store_true", help="re-apply the neckline prior to existing params.json, no model call")
    a = p.parse_args()

    inputs = Path(a.inputs)
    entries = json.loads((inputs / "manifest.json").read_text())["items"]
    if a.only:
        entries = [e for e in entries if e["safe"] == a.only or e["id"] == a.only]
        if not entries:
            raise SystemExit(f"no manifest item matches {a.only!r}")

    design = load_design()
    if a.reclamp:
        rows = [r for r in (reclamp(e, inputs, design) for e in entries) if r]
        print(f"{'safe':<20}{'neckline':<9}{'size':<6}{'front cm':<18}{'back cm':<18}")
        for r in rows:
            print(f"{r['safe']:<20}{r['kind']:<9}{r['size'] or '?':<6}"
                  f"{r['front_before_cm']:.2f} -> {r['front_after_cm']:<9.2f}"
                  f"{r['back_before_cm']:.2f} -> {r['back_after_cm']:<9.2f}")
            for note in r["notes"]:
                print(f"  {note}")
        print(f"ok: reclamped {len(rows)} items -> {inputs}/<safe>/params.json (bust_line {bust_line():.4f} cm)")
        return

    total = 0.0
    for e in entries:
        r = process(e, inputs, design)
        total += r["cost"]
        line = (f"{e['safe']} | {e['role']} | {len(r['values'])} overrides | {len(r['clamps'])} clamps | "
                f"{r['wall_seconds']:.1f}s | ${r['cost']:.4f}")
        if r["retried"]:
            line += " | retried"
        print(line)
        for note in r["clamps"] + r["invalid"]:
            print(f"  {note}")
        if a.assemble:
            panels, bad = assemble(e["safe"], json.loads((inputs / e["safe"] / "params.json").read_text()))
            print(f"  assembly: {panels} panels | self_intersecting={bad}")
    print(f"ok: {len(entries)} items -> {inputs}/<safe>/params.json | ${total:.4f} total")


if __name__ == "__main__":
    main()
