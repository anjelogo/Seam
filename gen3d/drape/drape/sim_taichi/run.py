from __future__ import annotations

import argparse
import json
import shutil
import time
import traceback
from pathlib import Path

import numpy as np

from .io import Scene, load_scene, write_dump, write_sim_obj
from .solver import Sim
from .vram import VramSampler


class FrameTimeout(RuntimeError):
    pass


class SimTimeout(RuntimeError):
    pass


def _fail(fails: dict[str, list[str]], tag: str, name: str) -> None:
    names = fails.setdefault(tag, [])
    if name not in names:
        names.append(name)


def _is_static(current: np.ndarray, previous: np.ndarray | None, scene: Scene) -> tuple[bool, int]:
    if previous is None:
        return False, len(current)
    config = scene.sim
    moved = np.abs(current - previous).sum(axis=1) > np.float32(config["static_threshold"])
    count = int(moved.sum())
    limit = len(current) * 0.01 * float(config["non_static_percent"])
    if count == 0 or count < limit:
        print(f"\nStatic with {count} non-static vertices out of {len(current)}")
        return True, count
    return False, count


def _append_timing(path: Path, record: dict) -> None:
    with path.open(encoding="utf-8") as handle:
        records = json.load(handle)
    records.append(record)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


# parity, coverage and sheet read the spec, labels and box mesh next to the sim obj
def _copy_siblings(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    for path in src.iterdir():
        if path.is_file() and "_scene." not in path.name and not path.name.endswith("_sim.obj"):
            shutil.copy2(path, dst / path.name)


def _base_record(scene: Scene) -> dict:
    record = dict(scene.meta.get("record") or {})
    record.update(
        item=scene.meta.get("item", ""),
        name=scene.meta.get("name", ""),
        body=scene.meta.get("body", ""),
        resolution_scale=record.get("resolution_scale"),
        meshgen_s=record.get("meshgen_s"),
    )
    return record


def run_scene(
    scene_path: Path,
    arch: str,
    out: Path,
    dump_every: int | None,
    timings: Path | None,
    max_steps: int | None,
) -> dict:
    started = time.time()
    scene = load_scene(scene_path)
    name = str(scene.meta.get("name", scene_path.stem.removesuffix("_scene")))
    fails: dict[str, list[str]] = {}
    overflow = {"soft_contact": 0, "point_triangle": 0, "edge_edge": 0}
    frame = -1
    sim = None
    current = None
    previous = None
    success = False
    init_s = 0.0
    body_collisions = None
    self_collisions = None
    el = out / name
    el.mkdir(parents=True, exist_ok=True)
    _copy_siblings(Path(scene_path).parent, el)

    with VramSampler(arch) as vram:
        try:
            if scene.meta.get("build_error") is not None:
                _fail(fails, str(scene.meta["build_error"]), name)
            else:
                sim = Sim(scene, arch)
                init_s = sim.init_s
                current = sim.positions()
                config = scene.sim
                frame_budget = int(config["max_sim_steps"] if max_steps is None else max_steps)
                every = config.get("dump_every") if dump_every is None else dump_every
                for frame in range(frame_budget):
                    frame_started = time.time()
                    sim.step_frame(frame)
                    dropped = sim.read_overflow()
                    if dropped:
                        print(f"frame {frame}: contact buffer overflow, elements dropped {dropped}")
                        for key, value in dropped.items():
                            overflow[key] += value
                    previous, current = current, sim.positions()
                    if every and frame >= 0 and frame % int(every) == 0:
                        write_dump(out, scene.arrays["faces"], current, frame)
                    elapsed = time.time() - frame_started
                    frame_limit = config.get("max_frame_time")
                    if frame_limit is not None:
                        limit = float(frame_limit) * (2 if frame == 0 else 1)
                        if elapsed > limit:
                            raise FrameTimeout(f"frame {frame} took longer than {limit}s")
                    if time.time() - started > float(config["max_sim_time"]):
                        raise SimTimeout(f"sim exceeded {config['max_sim_time']}s at frame {frame}")
                    if frame >= int(config["zero_gravity_steps"]) and frame >= int(config["min_sim_steps"]):
                        static, _ = _is_static(current, previous, scene)
                        if static:
                            break
                success = True
        except KeyboardInterrupt:
            raise
        except FrameTimeout as exc:
            print(f"{name}::ERROR::{exc}")
            _fail(fails, "frame_timeout", name)
        except SimTimeout as exc:
            print(f"{name}::ERROR::{exc}")
            _fail(fails, "simulation_timeout", name)
        except Exception:
            traceback.print_exc()
            _fail(fails, "crashes", name)

        wall_s = time.time() - started
        if success and sim is not None:
            body_collisions = sim.count_body_intersections()
            print(f"{name}: {body_collisions} body intersections")
            self_collisions = sim.count_self_intersections()
            budget = int(scene.sim["max_sim_steps"] if max_steps is None else max_steps)
            if frame == budget - 1:
                _fail(fails, "static_equilibrium", name)
                if current is not None:
                    print(f"{name}: ran the full frame budget, {_is_static(current, previous, scene)[1]} non-static vertices")
            if wall_s < 0.5:
                _fail(fails, "fast_finish", name)
            if body_collisions > int(scene.sim["max_body_collisions"]):
                _fail(fails, "cloth_body_intersection", name)
            if self_collisions > int(scene.sim["max_self_collisions"]):
                _fail(fails, "cloth_self_intersection", name)
        if sim is not None:
            current = sim.positions()
            write_sim_obj(scene.arrays["boxmesh_obj"].tobytes(), current, el / f"{name}_sim.obj")

        nan_count = 0 if current is None else int((~np.isfinite(current).all(axis=1)).sum())
        stats_time = round(max(0.0, wall_s - init_s), 3)
        record = _base_record(scene)
        record.update(
            sim_s=round(max(0.0, wall_s - init_s), 2),
            init_s=round(init_s, 3),
            spf=round(stats_time / frame if frame else stats_time, 3),
            frames=frame,
            body_collisions=body_collisions,
            self_collisions=self_collisions,
            fails=fails,
            device=arch,
            nan_count=nan_count,
            overflow=overflow,
            arch=arch,
            engine="taichi",
        )
        record.update(vram.fields())

    (el / "sim_record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if timings is not None:
        if timings.exists():
            _append_timing(timings, record)
        else:
            timings.write_text(json.dumps([record], indent=2), encoding="utf-8")
    print(f"DRAPE {name}: sim {record['sim_s']}s, frames {frame}, fails {fails or 'none'}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--arch", choices=("vulkan", "metal", "cuda", "cpu"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dump-every", type=int)
    parser.add_argument("--timings", type=Path)
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args()
    if args.dump_every is not None and args.dump_every <= 0:
        parser.error("--dump-every must be positive")
    if args.max_steps is not None and args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    run_scene(args.scene, args.arch, args.out, args.dump_every, args.timings, args.max_steps)


if __name__ == "__main__":
    main()
