"""Check every warp symbol pygarment needs against whichever warp is on sys.path. Spike-only."""

import importlib

import warp as wp

MODULES = ["warp.sim", "warp.sim.utils", "warp.sim.collide", "warp.sim.integrator_xpbd",
           "warp.sim.render", "warp.collision.panel_assignment"]
FUNCS = [("warp.sim.utils", "implicit_laplacian_smoothing"),
         ("warp.sim.collide", "count_self_intersections"),
         ("warp.sim.collide", "count_body_cloth_intersections"),
         ("warp.sim.integrator_xpbd", "replace_mesh_points")]
BUILDER = ["add_cloth_mesh", "add_shape_mesh", "add_attachment", "add_cloth_mesh_sewing_spring",
           "add_cloth_reference_labels", "add_cloth_reference_shape_mesh"]
MODEL_ATTRS = ["attachment_constraint", "cloth_reference_drag", "cloth_reference_k",
               "cloth_reference_margin", "cloth_reference_watertight_whole_shape_index",
               "global_viscous_damping", "global_collision_filter", "enable_edge_edge_collisions",
               "enable_triangle_particle_collisions", "enable_particle_particle_collisions",
               "particle_self_intersection_count", "body_cloth_intersection_count",
               "particle_max_velocity"]
BUILTINS = ["mesh_query_edge", "mesh_query_ray"]


def main() -> None:
    print(f"warp {wp.config.version} from {wp.__file__}")
    print("\n-- modules --")
    mods = {}
    for m in MODULES:
        try:
            mods[m] = importlib.import_module(m)
            print(f"  OK      {m}")
        except Exception as e:
            print(f"  MISSING {m}  ({type(e).__name__}: {e})")
    print("\n-- module functions --")
    for mod, fn in FUNCS:
        obj = mods.get(mod)
        state = "MISSING (module absent)" if obj is None else ("OK" if hasattr(obj, fn) else "MISSING")
        print(f"  {state:8} {mod}.{fn}")
    print("\n-- ModelBuilder methods --")
    sim = mods.get("warp.sim")
    for name in BUILDER:
        if sim is None:
            print(f"  MISSING (warp.sim absent) ModelBuilder.{name}")
            continue
        print(f"  {'OK' if hasattr(sim.ModelBuilder, name) else 'MISSING':8} ModelBuilder.{name}")
    print("\n-- Model attributes (source scan) --")
    if sim is not None:
        import inspect

        src = inspect.getsource(importlib.import_module("warp.sim.model"))
        for a in MODEL_ATTRS:
            print(f"  {'OK' if f'self.{a}' in src or f'{a}=' in src else 'MISSING':8} Model.{a}")
    print("\n-- native builtins --")
    for b in BUILTINS:
        print(f"  {'OK' if hasattr(wp, b) else 'MISSING':8} wp.{b}")


if __name__ == "__main__":
    main()
