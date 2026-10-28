import time
import traceback

from pygarment.meshgen.sim_config import PathCofig, SimConfig

from drape.sim_newton import StitchGeometryError

from .garment import Cloth


class FrameTimeout(RuntimeError):
    pass


class SimTimeout(RuntimeError):
    pass


def render_images(*args, **kwargs) -> None:
    """No renderer on the newton path; drape.py replaces this with a no-op anyway."""


def _record(stats: dict, tag: str, name: str) -> None:
    names = stats["fails"].setdefault(tag, [])
    if name not in names:
        names.append(name)


def run_sim(garment_name: str, props, paths: PathCofig, save_v_norms: bool = False, store_usd: bool = False,
            optimize_storage: bool = False, verbose: bool = False) -> None:
    config = SimConfig(props["sim"]["config"])
    stats = props["sim"]["stats"]
    start = time.time()
    cloth = None
    frame = -1
    success = False

    try:
        cloth = Cloth(garment_name, config, paths, caching=store_usd)
        for frame in range(config.max_sim_steps):
            frame_start = time.time()
            cloth.update(frame)
            if config.max_frame_time is not None:
                budget = config.max_frame_time * 2 if frame == 0 else config.max_frame_time
                if time.time() - frame_start > budget:
                    raise FrameTimeout(f"frame {frame} took longer than {budget}s")
            if time.time() - start > config.max_sim_time:
                raise SimTimeout(f"sim exceeded {config.max_sim_time}s at frame {frame}")
            if frame >= config.zero_gravity_steps and frame >= config.min_sim_steps:
                static, non_static = cloth.is_static()
                if verbose:
                    print(f"frame {frame}: {non_static} non-static, "
                          f"{cloth.count_self_intersections()} self intersections")
                if static:
                    break
        success = True
    except KeyboardInterrupt:
        raise
    except StitchGeometryError as exc:
        print(f"{garment_name}::ERROR::stitching geometry: {exc}")
        _record(stats, "gt_edges_creation", garment_name)
    except FrameTimeout as exc:
        print(f"{garment_name}::ERROR::{exc}")
        _record(stats, "frame_timeout", garment_name)
    except SimTimeout as exc:
        print(f"{garment_name}::ERROR::{exc}")
        _record(stats, "simulation_timeout", garment_name)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _record(stats, "crashes", garment_name)

    total = round(time.time() - start, 3)
    stats["sim_time"][garment_name] = total
    stats["spf"][garment_name] = total / frame if frame else total
    stats["fin_frame"][garment_name] = frame

    if success and cloth is not None:
        body_collisions = cloth.count_body_intersections()
        print(f"{garment_name}: {body_collisions} body intersections")
        self_collisions = cloth.count_self_intersections()
        stats["body_collisions"][garment_name] = body_collisions
        stats["self_collisions"][garment_name] = self_collisions
        if frame == config.max_sim_steps - 1:
            _record(stats, "static_equilibrium", garment_name)
            print(f"{garment_name}: ran the full frame budget, {cloth.is_static()[1]} non-static vertices")
        if total < 0.5:
            _record(stats, "fast_finish", garment_name)
        if body_collisions > config.max_body_collisions:
            _record(stats, "cloth_body_intersection", garment_name)
        if self_collisions > config.max_self_collisions:
            _record(stats, "cloth_self_intersection", garment_name)

    if cloth is not None:
        cloth.save_frame(save_v_norms=save_v_norms)
        if optimize_storage:
            _compress(paths)

    render_start = time.time()
    render_images(paths, props)
    props["render"]["stats"]["render_time"][garment_name] = round(time.time() - render_start, 3)


def _compress(paths: PathCofig) -> None:
    import igl

    for src, dst in ((paths.g_box_mesh, paths.g_box_mesh_compressed), (paths.g_sim, paths.g_sim_compressed)):
        if not src.exists():
            continue
        v, f = igl.read_triangle_mesh(str(src))
        igl.write_triangle_mesh(str(dst), v, f)
        src.unlink()
    for extra in (paths.g_texture_fabric, paths.g_mtl):
        if extra.exists():
            extra.unlink()
