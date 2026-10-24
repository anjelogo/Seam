"""Fork-vs-Newton drape parity on identical patterns: surface distance, waist/shoulder, frozen gates, cost."""

import argparse
import hashlib
import json
import random
import re
import shutil
from pathlib import Path
from typing import NoReturn

import numpy as np
import trimesh
import yaml

from drape import collar as collar_mod
from drape import coverage as cov_mod
from drape import sheet as sheet_mod
from drape._repo import RUNS
from drape.bind import nearest_surface

TEXTURE = ("depop_936695379", "depop_945724547", "grailed_109046872", "depop_958674696",
           "depop_958854988", "depop_958141161", "depop_959308776", "grailed_109137061",
           "depop_953525988", "depop_957013558", "depop_959195954", "depop_954868283")
POC = ("depop_941190262", "grailed_108767954", "grailed_108843068", "depop_958293311")
SWEEP = ("depop_954868283",)
PARTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "texture": ("inputs_texture", TEXTURE),
    "poc": ("inputs", POC),
    "sweep_XS": ("inputs_texture", SWEEP),
    "sweep_M": ("inputs_texture", SWEEP),
    "sweep_XL": ("inputs_texture", SWEEP),
}
NOISE_PART = "texture"
NOISE_ITEMS = ("depop_954868283", "depop_959195954", "depop_936695379", "grailed_109137061")

SAMPLES = 20000
SEED = 20261023
WAIST_LABEL = "lower_interface"
HELD_FROM_FRAME = 100
HELD_TOL_CM = 2.0
SHAPE_NOISE_X = 2.0
WAIST_TOL_CM = 2.0
SIM_X = 2.0
VRAM_MAX_MB = 4096
FLOOR_FILE = "noise_floor.json"
DUMP_RE = re.compile(r"^dump_f(\d+)$")


def die(msg: str) -> NoReturn:
    raise SystemExit(f"parity: {msg}")


def part_inputs(part: str) -> Path:
    return RUNS / PARTS[part][0]


def spec_dir(run: Path, safe: str) -> Path | None:
    specs = sorted((run / safe / "sim").glob("*/*_specification.json"))
    return specs[0].parent if specs else None


def sim_obj(sdir: Path) -> Path:
    return sdir / f"{sdir.name}_sim.obj"


def labels_of(sdir: Path) -> dict:
    path = sdir / f"{sdir.name}_vertex_labels.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def kind_of(run: Path, safe: str, sdir: Path) -> str:
    panels = run / safe / "panels.json"
    if panels.exists():
        return "top" if json.loads(panels.read_text()).get("garment") == "upper" else "bottom"
    return "bottom" if WAIST_LABEL in labels_of(sdir) else "top"


def timing(run: Path, safe: str) -> dict:
    """The run's own record for this item; coverage takes the first match, so this does too."""
    path = run / "timings.json"
    if not path.exists():
        return {}
    for rec in json.loads(path.read_text()):
        if rec.get("item") == safe:
            return rec
    return {}


def sample_surface(mesh: trimesh.Trimesh, n: int, seed: int) -> np.ndarray:
    """Area-uniform: face drawn by area, then a uniform point inside it."""
    tri = np.asarray(mesh.triangles, float)
    area = trimesh.triangles.area(tri)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(tri), size=n, p=area / area.sum())
    u, v = rng.random((n, 1)), rng.random((n, 1))
    over = (u + v) > 1.0
    u[over], v[over] = 1.0 - u[over], 1.0 - v[over]
    a, b, c = tri[pick, 0], tri[pick, 1], tri[pick, 2]
    return a + u * (b - a) + v * (c - a)


def one_way(src: trimesh.Trimesh, dst: trimesh.Trimesh) -> dict:
    pts = sample_surface(src, SAMPLES, SEED)
    close, _ = nearest_surface(np.asarray(dst.vertices), np.asarray(dst.faces), pts)
    d = np.linalg.norm(close - pts, axis=1)
    return {"n": SAMPLES, "mean_cm": round(float(d.mean()), 4), "p95_cm": round(float(np.percentile(d, 95)), 4),
            "max_cm": round(float(d.max()), 4)}


def shape(ref_obj: Path, new_obj: Path) -> dict:
    a, b = collar_mod.obj_mesh(ref_obj), collar_mod.obj_mesh(new_obj)
    fwd, back = one_way(a, b), one_way(b, a)
    return {"ref_to_new": fwd, "new_to_ref": back,
            "symmetric_mean_cm": round((fwd["mean_cm"] + back["mean_cm"]) / 2, 4),
            "verts": [len(a.vertices), len(b.vertices)], "faces": [len(a.faces), len(b.faces)]}


def dump_frames(sdir: Path) -> list[tuple[int, Path]]:
    """Dumps land in the sim dir's parent (drape.drape writes them next to the spec folder)."""
    for where in (sdir.parent, sdir):
        hits = [(int(m.group(1)), p) for p in where.glob("dump_f*.npy") if (m := DUMP_RE.match(p.stem))]
        if hits:
            return sorted(hits)
    return []


def waist_metrics(sdir: Path) -> dict:
    ids = labels_of(sdir).get(WAIST_LABEL) or []
    obj = sim_obj(sdir)
    out: dict = {"label": WAIST_LABEL, "n_label": len(ids), "top_cm": None, "held": None,
                 "max_dev_cm": None, "frames": 0}
    if not ids or not obj.exists():
        out["note"] = "no waist label or no sim obj"
        return out
    ids = np.asarray(ids, int)
    raw = collar_mod.to_cm(np.asarray(trimesh.load(obj, process=False, maintain_order=True).vertices), obj.name)
    if ids.max() >= len(raw):
        out["note"] = f"label index {ids.max()} past {len(raw)} verts"
        return out
    out["top_cm"] = round(float(raw[ids, 1].mean()), 3)
    frames = dump_frames(sdir)
    if not frames:
        out["note"] = "no dumps, held-whole-sim not measurable"
        return out
    ys = {}
    for frame, path in frames:
        arr = collar_mod.to_cm(np.load(path), path.name)
        if ids.max() >= len(arr):
            out["note"] = f"dump {path.name} has {len(arr)} verts, label index {ids.max()}"
            return out
        ys[frame] = float(arr[ids, 1].mean())
    final = ys[frames[-1][0]]
    watched = {f: y for f, y in ys.items() if f >= HELD_FROM_FRAME}
    dev = max((abs(y - final) for y in watched.values()), default=0.0)
    out.update(frames=len(frames), watched=len(watched), final_dump_cm=round(final, 3),
               max_dev_cm=round(dev, 3), held=bool(watched) and dev <= HELD_TOL_CM,
               from_frame=HELD_FROM_FRAME, tol_cm=HELD_TOL_CM)
    return out


def body_obj(sdir: Path, rec: dict) -> Path:
    name = rec.get("body")
    if not name:
        tag = collar_mod.ARM_TAG.search(sdir.name)
        name = f"wearer_masc_a{tag.group(1)}" if tag else "wearer_masc"
    return collar_mod.BODIES / f"{name}.obj"


def shoulder_metrics(sdir: Path, body: Path) -> dict:
    if not body.exists():
        return {"note": f"{body.name} missing"}
    mesh = collar_mod.obj_mesh(sim_obj(sdir))
    heights = collar_mod.shoulder_heights(mesh, collar_mod.body_shoulders(body), sdir.name)
    return {"body": body.name, **heights}


def gate_row(run: Path, part: str, safe: str, ref_run: Path, marks: dict) -> dict:
    # no v3 run exists here, so the sim_time gate budgets against the fork's own sim_s
    cov_mod.V3_RUNS = (ref_run,)
    try:
        row = cov_mod.measure(run, safe, part_inputs(part), marks)
    except SystemExit as exc:
        return {"error": str(exc)}
    out = {k: {"pass": bool(v["pass"]), "value": v["value"], "limit": v["limit"]} for k, v in row["gates"].items()}
    return {"gates": out, "failed": sorted(k for k, v in out.items() if not v["pass"]),
            "penetration_pct": row["penetration_pct"], "spec": row["spec"]}


def cost_row(rec: dict) -> dict:
    return {"sim_s": rec.get("sim_s"), "vram_mb": rec.get("vram_mb"), "frames": rec.get("frames"),
            "body_collisions": rec.get("body_collisions"), "self_collisions": rec.get("self_collisions"),
            "fails": rec.get("fails"), "device": rec.get("device"), "meshgen_s": rec.get("meshgen_s"),
            "name": rec.get("name"), "body": rec.get("body")}


def side(run: Path, part: str, safe: str, ref_run: Path, marks: dict, want_gates: bool) -> dict:
    sdir = spec_dir(run / part, safe)
    if sdir is None:
        return {"present": False}
    obj = sim_obj(sdir)
    if not obj.exists():
        return {"present": False, "note": f"{obj.name} missing"}
    rec = timing(run / part, safe)
    kind = kind_of(run / part, safe, sdir)
    out = {"present": True, "kind": kind, "spec": sdir.name, "obj": str(obj),
           "cost": cost_row(rec), "body": body_obj(sdir, rec).stem}
    if kind == "bottom":
        out["waist"] = waist_metrics(sdir)
    else:
        out["shoulder"] = shoulder_metrics(sdir, body_obj(sdir, rec))
    if want_gates and kind == "top":
        out["coverage"] = gate_row(run / part, part, safe, ref_run / part, marks)
    return out


def gate_verdict(ref: dict, new: dict) -> dict:
    rg, ng = (ref.get("coverage") or {}), (new.get("coverage") or {})
    if "gates" not in rg or "gates" not in ng:
        return {"pass": None, "note": rg.get("error") or ng.get("error") or "gates not measured"}
    rf, nf = set(rg["failed"]), set(ng["failed"])
    ok = not nf if not rf else nf <= rf
    rule = "ref passes all -> new must pass all" if not rf else "new failed set must be a subset of ref's"
    return {"pass": bool(ok), "rule": rule, "ref_failed": sorted(rf), "new_failed": sorted(nf),
            "extra": sorted(nf - rf)}


def shape_verdict(dist: dict | None, floor: float) -> dict:
    if not dist:
        return {"pass": None, "note": "no shape distance"}
    limit = round(SHAPE_NOISE_X * floor, 4)
    return {"pass": dist["symmetric_mean_cm"] <= limit, "value": dist["symmetric_mean_cm"],
            "limit": limit, "rule": f"symmetric mean <= {SHAPE_NOISE_X:g} x noise floor {floor:.4f} cm"}


def bottom_verdict(ref: dict, new: dict) -> dict:
    if ref.get("kind") != "bottom":
        return {"pass": None, "note": "not a bottom"}
    rw, nw = ref.get("waist") or {}, new.get("waist") or {}
    if rw.get("top_cm") is None or nw.get("top_cm") is None:
        return {"pass": None, "note": "waist top not measurable"}
    delta = round(abs(nw["top_cm"] - rw["top_cm"]), 3)
    held = nw.get("held")
    return {"pass": None if held is None else bool(held and delta <= WAIST_TOL_CM),
            "waist_top_ref_cm": rw["top_cm"], "waist_top_new_cm": nw["top_cm"], "delta_cm": delta,
            "limit_cm": WAIST_TOL_CM, "held_whole_sim": held, "max_dev_cm": nw.get("max_dev_cm"),
            "ref_held_whole_sim": rw.get("held")}


def cost_verdict(ref: dict, new: dict) -> dict:
    rs, ns = (ref.get("cost") or {}).get("sim_s"), (new.get("cost") or {}).get("sim_s")
    vram = (new.get("cost") or {}).get("vram_mb")
    if rs is None or ns is None:
        return {"pass": None, "note": "sim_s missing on one side"}
    budget = round(SIM_X * float(rs), 2)
    sim_ok = float(ns) <= budget
    vram_ok = None if vram is None else int(vram) <= VRAM_MAX_MB
    return {"pass": None if vram_ok is None else bool(sim_ok and vram_ok), "sim_s_ref": rs, "sim_s_new": ns,
            "sim_budget_s": budget, "sim_pass": sim_ok, "vram_mb_new": vram, "vram_limit_mb": VRAM_MAX_MB,
            "vram_pass": vram_ok}


def row_verdict(parts: dict, kind: str) -> str:
    need = ("shape", "cost", "gates" if kind == "top" else "bottoms")
    vals = [(parts.get(k) or {}).get("pass") for k in need]
    if any(v is False for v in vals):
        return "FAIL"
    return "PASS" if all(v is True for v in vals) else "PARTIAL"


def load_floor(ref: Path) -> float:
    path = ref / FLOOR_FILE
    if not path.exists():
        die(f"{path} missing - run --noise first; the shape target is 2 x the measured noise floor")
    floor = json.loads(path.read_text()).get("floor_cm")
    if not isinstance(floor, (int, float)) or floor <= 0:
        die(f"{path} has no usable floor_cm")
    return float(floor)


def spec_sha(run: Path, part: str, safe: str) -> dict:
    out = {}
    for spec in sorted((run / part / safe / "pattern").glob("*/*_specification.json")):
        out[spec.parent.name] = hashlib.sha256(spec.read_bytes()).hexdigest()
    return out


def seed_patterns(ref: Path, new: Path, only: str | None) -> None:
    for part, (_, items) in PARTS.items():
        for safe in items:
            if only and safe != only:
                continue
            src = ref / part / safe / "pattern"
            if not src.is_dir():
                print(f"  seed {part}/{safe}: no pattern dir in ref")
                continue
            dst = new / part / safe / "pattern"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  seed {part}/{safe} -> {dst}")


def noise(ref: Path, only: str | None) -> dict:
    items, floors = {}, []
    for safe in NOISE_ITEMS:
        if only and safe != only:
            continue
        a, b = spec_dir(ref / NOISE_PART, safe), spec_dir(ref / "noise" / NOISE_PART, safe)
        if a is None or b is None:
            die(f"noise {safe}: run 1 {'ok' if a else 'missing'}, run 2 {'ok' if b else 'missing'}")
        sa = spec_sha(ref, NOISE_PART, safe)
        sb = spec_sha(ref / "noise", NOISE_PART, safe)
        dist = shape(sim_obj(a), sim_obj(b))
        rec = {"run1": str(sim_obj(a)), "run2": str(sim_obj(b)), **dist,
               "spec_sha256": {"run1": sa, "run2": sb, "identical": sa == sb and bool(sa)},
               "sim_s": [timing(ref / NOISE_PART, safe).get("sim_s"),
                         timing(ref / "noise" / NOISE_PART, safe).get("sim_s")]}
        if not rec["spec_sha256"]["identical"]:
            print(f"  WARNING {safe}: specification.json differs between the two runs")
        items[safe] = rec
        floors.append(dist["symmetric_mean_cm"])
        print(f"  {safe:18s} sym mean {dist['symmetric_mean_cm']:.4f} cm  "
              f"r1->r2 mean {dist['ref_to_new']['mean_cm']:.4f} p95 {dist['ref_to_new']['p95_cm']:.4f} "
              f"max {dist['ref_to_new']['max_cm']:.4f}  spec {'same' if rec['spec_sha256']['identical'] else 'DIFFERS'}")
    if not floors:
        die("no noise pairs measured")
    out = {"ref": str(ref), "samples": SAMPLES, "seed": SEED, "items": items, "n_items": len(floors),
           "floor_cm": round(float(np.mean(floors)), 4)}
    (ref / FLOOR_FILE).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nnoise floor {out['floor_cm']:.4f} cm over {len(floors)} item(s) -> {ref / FLOOR_FILE}")
    return out


def frames_for(meshes: list[trimesh.Trimesh]) -> tuple[tuple, tuple]:
    """One frame for both engines of an item, from the union of their bounds, so the pair compares straight across."""
    pts = np.vstack([np.asarray(m.vertices) for m in meshes])
    lo, hi = pts.min(0), pts.max(0)
    centre = np.array([0.0, (lo[1] + hi[1]) / 2, 0.0])
    half = float(max(hi - lo)) / 2 * 1.1
    return (centre, half), (np.array([0.0, hi[1] - 6.0, 0.0]), 33.0)


def engine_tiles(obj: Path, body: Path, parts_cache: dict, full: tuple, detail: tuple, label: str | None):
    if body.name not in parts_cache:
        parts_cache[body.name] = cov_mod.body_parts(body)[1]
    layers = sheet_mod.body_layers(parts_cache[body.name], None)
    mesh = collar_mod.obj_mesh(obj)
    layers = layers + [(np.asarray(mesh.vertices), np.asarray(mesh.faces), sheet_mod.GARMENT_RGB)]
    views = [(v, full, sheet_mod.FULL[v]) for v in sheet_mod.FULL] + [("detail", detail, sheet_mod.SHOULDER)]
    tiles = []
    for name, box, (az, el) in views:
        img = sheet_mod.render(layers, box, az, el, lift=sheet_mod.LIFT)
        tiles.append(sheet_mod.tag(img, f"{label} {name}") if label else img)
    return tiles


def grid(rows: list[list], header: str | None):
    from PIL import Image

    cols = max(len(r) for r in rows)
    top = sheet_mod.LABEL if header else 0
    img = Image.new("RGB", (cols * sheet_mod.TILE, top + len(rows) * sheet_mod.TILE), sheet_mod.BG)
    if header:
        img.paste(sheet_mod.strip(header, cols * sheet_mod.TILE), (0, 0))
    for r, line in enumerate(rows):
        for c, tile in enumerate(line):
            img.paste(tile, (c * sheet_mod.TILE, top + r * sheet_mod.TILE))
    return img


def make_sheets(rows: dict, out_dir: Path, blind: Path | None) -> None:
    parts_cache: dict = {}
    pairs = [(key, r) for key, r in rows.items() if r["ref"].get("present") and r["new"].get("present")]
    if not pairs:
        print("sheets: no item has both sides")
        return
    order = list(range(1, len(pairs) + 1))
    rng = random.Random(SEED)
    rng.shuffle(order)
    key_map: dict = {}
    for n, (name, r) in zip(order, pairs):
        ref_obj, new_obj = Path(r["ref"]["obj"]), Path(r["new"]["obj"])
        ref_body = collar_mod.BODIES / f"{r['ref']['body']}.obj"
        new_body = collar_mod.BODIES / f"{r['new']['body']}.obj"
        full, detail = frames_for([collar_mod.obj_mesh(ref_obj), collar_mod.obj_mesh(new_obj)])
        if blind is None:
            img = grid([engine_tiles(ref_obj, ref_body, parts_cache, full, detail, "fork"),
                        engine_tiles(new_obj, new_body, parts_cache, full, detail, "newton")],
                       f"{name}  fork (top row) vs newton (bottom row)")
            path = out_dir / f"{name.replace('/', '_')}.jpg"
            print(f"  {name} -> {path} ({sheet_mod.save(img, path) / 1024:.0f}KB)")
            continue
        engines = ["fork", "newton"]
        rng.shuffle(engines)
        side_obj = {"fork": (ref_obj, ref_body), "newton": (new_obj, new_body)}
        for slot, engine in zip(("A", "B"), engines):
            obj, body = side_obj[engine]
            img = grid([engine_tiles(obj, body, parts_cache, full, detail, None)], None)
            sheet_mod.save(img, blind / f"{n}_{slot}.jpg")
        key_map[str(n)] = {"item": name, "A": engines[0], "B": engines[1]}
        print(f"  blind {n} <- {name} (A={engines[0]}, B={engines[1]})")
    if blind is not None:
        key = blind.parent / f"{blind.name}_key.json"
        key.write_text(json.dumps({"seed": SEED, "items": key_map}, indent=2) + "\n")
        print(f"blind key -> {key}")


def md_table(rows: dict) -> list[str]:
    head = ("item", "kind", "sym mean cm", "shape", "gates ref", "gates new", "gates",
            "waist cm r/n", "held", "shoulder err r/n", "sim s r/n", "vram new", "verdict")
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, r in rows.items():
        ref, new, v = r["ref"], r["new"], r.get("verdicts") or {}
        if not ref.get("present") or not new.get("present"):
            miss = "ref missing" if not ref.get("present") else "new missing"
            out.append(f"| {name} | - | - | - | - | - | - | - | - | - | - | - | **{miss.upper()}** |")
            continue
        d = r.get("shape") or {}
        rg = (ref.get("coverage") or {}).get("failed")
        ng = (new.get("coverage") or {}).get("failed")

        def gl(f):
            return "n/a" if f is None else ("pass" if not f else ",".join(f))

        w = v.get("bottoms") or {}
        waist = (f"{w['waist_top_ref_cm']:.1f}/{w['waist_top_new_cm']:.1f}"
                 if w.get("waist_top_ref_cm") is not None else "-")
        held = "-" if w.get("held_whole_sim") is None else ("yes" if w["held_whole_sim"] else "NO")
        sh = ""
        if ref.get("kind") == "top":
            rs, ns = ref.get("shoulder") or {}, new.get("shoulder") or {}
            if "left" in rs and "left" in ns:
                sh = (f"{rs['left']['error_cm']:+.1f}/{rs['right']['error_cm']:+.1f} -> "
                      f"{ns['left']['error_cm']:+.1f}/{ns['right']['error_cm']:+.1f}")
        c = v.get("cost") or {}
        sim = f"{c.get('sim_s_ref')}/{c.get('sim_s_new')}" if c.get("sim_s_ref") is not None else "-"
        out.append(f"| {name} | {ref.get('kind')} | {d.get('symmetric_mean_cm', '-')} "
                   f"| {flag((v.get('shape') or {}).get('pass'))} | {gl(rg)} | {gl(ng)} "
                   f"| {flag((v.get('gates') or {}).get('pass'))} | {waist} | {held} | {sh or '-'} "
                   f"| {sim} | {c.get('vram_mb_new', '-')} | **{r['verdict']}** |")
    return out


def flag(val) -> str:
    return "-" if val is None else ("pass" if val else "FAIL")


def detail_lines(rows: dict) -> list[str]:
    out = ["", "## Per-item surface distance (cm)", "",
           "| item | ref->new mean | p95 | max | new->ref mean | p95 | max | verts r/n |",
           "|---|---|---|---|---|---|---|---|"]
    for name, r in rows.items():
        d = r.get("shape")
        if not d:
            continue
        f, b = d["ref_to_new"], d["new_to_ref"]
        out.append(f"| {name} | {f['mean_cm']} | {f['p95_cm']} | {f['max_cm']} | {b['mean_cm']} "
                   f"| {b['p95_cm']} | {b['max_cm']} | {d['verts'][0]}/{d['verts'][1]} |")
    return out


def report(ref: Path, new: Path, only: str | None, floor: float, want_sheets: bool, blind: Path | None) -> dict:
    marks: dict = {}
    rows: dict = {}
    for part, (_, items) in PARTS.items():
        for safe in items:
            if only and safe != only:
                continue
            name = f"{part}/{safe}"
            r = {"part": part, "safe": safe,
                 "ref": side(ref, part, safe, ref, marks, True),
                 "new": side(new, part, safe, ref, marks, True)}
            if r["ref"]["present"] and r["new"]["present"]:
                r["shape"] = shape(Path(r["ref"]["obj"]), Path(r["new"]["obj"]))
                r["verdicts"] = {"gates": gate_verdict(r["ref"], r["new"]),
                                 "shape": shape_verdict(r["shape"], floor),
                                 "bottoms": bottom_verdict(r["ref"], r["new"]),
                                 "cost": cost_verdict(r["ref"], r["new"])}
                r["verdict"] = row_verdict(r["verdicts"], r["ref"]["kind"])
            else:
                r["verdict"] = "REF MISSING" if not r["ref"]["present"] else "NEW MISSING"
            rows[name] = r
            print(f"{name:28s} {r['verdict']}")

    lines = [f"# Drape parity: {ref} vs {new}", "",
             f"noise floor {floor:.4f} cm, shape target <= {SHAPE_NOISE_X * floor:.4f} cm; "
             f"waist tol {WAIST_TOL_CM:g} cm; sim <= {SIM_X:g}x fork; vram <= {VRAM_MAX_MB} MB; "
             f"{SAMPLES} samples, seed {SEED}", ""]
    lines += md_table(rows) + detail_lines(rows)
    out_dir = new / "parity"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "parity.md").write_text("\n".join(lines) + "\n")
    payload = {"ref": str(ref), "new": str(new), "floor_cm": floor, "samples": SAMPLES, "seed": SEED,
               "targets": {"shape_x_noise": SHAPE_NOISE_X, "waist_tol_cm": WAIST_TOL_CM,
                           "sim_x": SIM_X, "vram_max_mb": VRAM_MAX_MB,
                           "held_from_frame": HELD_FROM_FRAME, "held_tol_cm": HELD_TOL_CM},
               "gates_json": cov_mod.GATES, "items": rows}
    (out_dir / "parity.json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print("\n".join([""] + lines[3:]))
    print(f"\n-> {out_dir / 'parity.md'}  {out_dir / 'parity.json'}")
    if want_sheets:
        make_sheets(rows, out_dir / "sheets", None)
    if blind is not None:
        blind.mkdir(parents=True, exist_ok=True)
        make_sheets(rows, out_dir / "sheets", blind)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="fork vs newton drape parity over the fixed reference layout")
    ap.add_argument("--ref", type=Path, required=True, help="fork reference run root, e.g. runs/out_fork_ref")
    ap.add_argument("--new", type=Path, default=None, help="newton run root, e.g. runs/out_newton")
    ap.add_argument("--only", default=None, help="this safe id only")
    ap.add_argument("--sheets", action="store_true", help="paired labelled fork|newton sheets")
    ap.add_argument("--blind", type=Path, default=None, help="unlabelled A/B sheets here, key written beside it")
    ap.add_argument("--seed-patterns", action="store_true", help="copy ref pattern/ dirs into --new")
    ap.add_argument("--noise", action="store_true", help="fork run 1 vs fork run 2, writes noise_floor.json")
    args = ap.parse_args()

    if not args.ref.is_dir():
        die(f"{args.ref} is not a directory")
    if args.noise:
        noise(args.ref, args.only)
        return
    if args.new is None:
        die("--new is required unless --noise")
    if args.seed_patterns:
        seed_patterns(args.ref, args.new, args.only)
    if not args.new.is_dir():
        die(f"{args.new} is not a directory")
    report(args.ref, args.new, args.only, load_floor(args.ref), args.sheets, args.blind)


if __name__ == "__main__":
    main()
