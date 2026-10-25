# Cloth sim license spike

Report-only spike (T7). Nothing in the main pipeline changed; no engine switch was made.
**This is a licensing finding, not legal advice.**

## Verdict

The cloth **sim** engine we run is non-commercial-only and there is no drop-in permissive
replacement. The blocker is real, and the escape is a **feature port, not a swap**: every
GarmentCodeData cloth feature `pygarment` depends on is absent from upstream warp — about
**3,300 changed lines across 13 files plus a 326-line new module, including 112 lines of
CUDA/C++** that force a from-source warp build (prebuilt wheels ship no `native/mesh.h`).

Scope is narrower than feared, though: **pattern generation is already license-clean.**
GarmentCode/pygarment is MIT and never imports warp for the pattern stage — under an upstream-warp
override both items produced patterns successfully (`pattern rc=0`, specs + SVG + PNG in
`runs/out_spike_port/`). Only the drape/sim stage is blocked.

Recommended target if we pursue this: **Newton 1.7.0 (Apache-2.0)**, not upstream warp 1.9.1.
Rationale in [Port target decision](#port-target-decision) — warp.sim is end-of-life.

## 1. License ground truth

| Component | Path / source | License | Commercial use |
| --- | --- | --- | --- |
| Sim engine we run | `vendor/NvidiaWarp-GarmentCode` @ `63baf6855efdd89b2834b74640f84b3bb0d86b50` (2024-09-02), origin [maria-korosteleva/NvidiaWarp-GarmentCode](https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode) | NVIDIA Source Code License for Warp | **BLOCKED** |
| Upstream warp | [NVIDIA/warp](https://github.com/NVIDIA/warp) | Apache-2.0 **from v1.7.0** (see §4) | OK |
| Newton | [newton-physics/newton](https://github.com/newton-physics/newton), PyPI `newton` 1.7.0 | Apache-2.0 | OK |
| GarmentCode + pygarment | `vendor/GarmentCode` | MIT, "Copyright (c) 2024 Maria Korosteleva" | OK |

The fork's `LICENSE.md` is "NVIDIA Source Code License for Warp". §3.3, verbatim from the file on disk:

> **3.3 Use Limitation.** The Work and any derivative works thereof only may be used or intended
> for use non-commercially. Notwithstanding the foregoing, NVIDIA and its affiliates may use the
> Work and any derivative works commercially. As used herein, "non-commercially" means for research
> or evaluation purposes only.

§3.2 additionally makes the limitation sticky — derivative works may carry your own terms only if
those terms keep §3.3 applying:

> **3.2 Derivative Works.** You may specify that additional or different terms apply to the use,
> reproduction, and distribution of your derivative works of the Work ("Your Terms") only if
> (a) Your Terms provide that the use limitation in Section 3.3 applies to your derivative works…

So "fork it and change the license" is not available. `vendor/GarmentCode/LICENSE` is MIT,
"Copyright (c) 2024 Maria Korosteleva".

## 2. Fork delta vs upstream

The vendored fork is a shallow clone (one commit, `63baf68 typo README.md`), so the delta came from
diffing it against upstream `v1.0.0-beta.6` — the base its `VERSION.md` declares and its README
confirms ("fork of NVIDIA Warp based on Warp v.1.0.0-beta.6").

Fork README, changes introduced for GarmentCodeData — all in the XPBD solver:

- **Self-collisions** — point-triangle and edge-edge detection/resolution for cloth.
- **Attachment** — equality and inequality attachment constraints (e.g. fixing a skirt at the waist).
- **Body-part drag** — drags intersecting garment panels toward their body parts until collisions resolve (initialization fix).
- **Body model collision constraint** — pushes cloth found inside the body back out.
- **Edge-based ray intersection** — new native `mesh_query_edge()` builtin (+ `adj_mesh_query_edge()` placeholder).
- **Fix** — `apply_particle_deltas()` applies `max_velocity` to position for stability.

Measured delta (`diff -u`, changed lines incl. both sides):

| File | Changed lines | Kind |
| --- | --- | --- |
| `warp/sim/model.py` | 728 | Python |
| `warp/sim/collide.py` | 699 | Python |
| `warp/sim/integrator_euler.py` | 530 | Python |
| `warp/sim/integrator_xpbd.py` | 524 | Python |
| `warp/stubs.py` | 328 | Python (generated) |
| `warp/collision/panel_assignment.py` | 326 (new file) | Python |
| `warp/native/mesh.h` | 109 | **CUDA/C++** |
| `warp/sim/utils.py` | 93 | Python |
| `warp/builtins.py` | 32 | Python |
| `warp/native/exports.h` | 3 | **CUDA/C++** |
| `warp/sim/particles.py` | 4 | Python |
| **Total tree diff** | **3,307** | |

Also differing but not sim-relevant: `README.md`, `.gitattributes`, `warp/tests/test_mesh_query_point.py`,
two `warp/fem/` files, plus build artifacts (`*.o`) committed into the fork.

## 3. pygarment API surface

Only three files under `vendor/GarmentCode/pygarment` touch warp: `meshgen/garment.py`,
`meshgen/simulation.py`, `data_config.py`. The import block in `garment.py` is the port contract:

```python
import warp as wp
import warp.sim.render
from warp.sim.utils import implicit_laplacian_smoothing
import warp.collision.panel_assignment as assign
from warp.sim.collide import count_self_intersections, count_body_cloth_intersections
from warp.sim.integrator_xpbd import replace_mesh_points
```

Plus `wp.sim.ModelBuilder` / `XPBDIntegrator` / `Mesh` / `Model` / `collide`, four fork-only
`ModelBuilder` methods, and ~12 fork-only `Model` fields. The surface is small in call count but
every interesting call is fork-only — see the gap table in §5.

## 4. warp.sim upstream status

Two independent boundaries decide the viable window. Both measured, not assumed.

**License boundary** (`git show <tag>:LICENSE.md`, first line):

| Tag | License |
| --- | --- |
| v1.0.0-beta.6 (fork base) | NVIDIA Source Code License for Warp |
| v1.0.0 – v1.6.0 | NVIDIA Software License Agreement |
| **v1.7.0 and later** | **Apache License 2.0** |

The fork's own base is pre-relicense, so the fork's non-commercial terms are not an extra
restriction the fork author added — upstream was non-commercial then too.

**`warp.sim` availability** (pip install each wheel into an isolated target, `import warp.sim`):

| Version | Result |
| --- | --- |
| 1.18.0 | `ModuleNotFoundError: No module named 'warp.sim'` |
| 1.15.0 | `ModuleNotFoundError` |
| 1.12.0 | `ModuleNotFoundError` |
| 1.10.1 | `ModuleNotFoundError` |
| **1.9.1** | **OK** — ModelBuilder, XPBDIntegrator, Mesh, collide, Model all present; emits `DeprecationWarning: warp.sim … will be removed in v1.10. Please transition to … Newton` |
| 1.8.1 | OK, same deprecation warning |
| 1.7.2 | OK, no deprecation warning |

**Viable window = warp-lang 1.7.0 – 1.9.1** (Apache-2.0 *and* has `warp.sim`). Newest is **1.9.1**,
and it is already deprecated with removal shipped at 1.10.

## 5. Port attempt

**Approach.** Prepend an upstream warp wheel to `PYTHONPATH` so `import warp` resolves to upstream
1.9.1 instead of the editable fork, then run the unmodified pipeline. Nothing under
`vendor/`, `.venv/` or `drape/` was touched. Verified the override took effect:

```
=== engine identity under PYTHONPATH override ===
1.9.1 /workspace/spike/wp/1.9.1/warp/__init__.py
=== engine identity WITHOUT override (fork) ===
1.0.0-beta.6 /workspace/seam/gen3d/drape/vendor/NvidiaWarp-GarmentCode/warp/__init__.py
=== license metadata of overridden engine ===
License: Apache-2.0
```

Spike code is 241 lines total, all in `spike/`: `gap_probe.py` 59, `render_compare.py` 80,
`run_port.sh` 41, `probe_versions.sh` 26, `run_base.sh` 23, `probe_one.py` 12. No shim was written
beyond the path override — the attempt failed before a shim could matter.

**Result: the port fails at import, on both items, identically.**

```
File "/workspace/seam/gen3d/drape/drape/drape.py", line 15, in <module>
  import pygarment.meshgen.simulation as sim_mod
File ".../pygarment/meshgen/simulation.py", line 29, in <module>
  from pygarment.meshgen.garment import Cloth
File ".../pygarment/meshgen/garment.py", line 10, in <module>
  from warp.sim.utils import implicit_laplacian_smoothing
ImportError: cannot import name 'implicit_laplacian_smoothing' from 'warp.sim.utils'
            (/workspace/spike/wp/1.9.1/warp/sim/utils.py)
```

`drape rc=1`, wall 10 s each. This is the *first* missing symbol, not the only one.

**Gap table** — what `pygarment` needs vs upstream warp 1.9.1 (Apache-2.0):

| Needed by pygarment | Upstream 1.9.1 | Fork |
| --- | --- | --- |
| `warp.sim.utils.implicit_laplacian_smoothing` | MISSING | present |
| `warp.sim.collide.count_self_intersections` | MISSING | present |
| `warp.sim.collide.count_body_cloth_intersections` | MISSING | present |
| `warp.sim.integrator_xpbd.replace_mesh_points` | MISSING | present |
| `warp.collision.panel_assignment` (module) | MISSING | present (326 lines) |
| `ModelBuilder.add_attachment` | MISSING | present |
| `ModelBuilder.add_cloth_mesh_sewing_spring` | MISSING | present |
| `ModelBuilder.add_cloth_reference_labels` | MISSING | present |
| `ModelBuilder.add_cloth_reference_shape_mesh` | MISSING | present |
| `Model.attachment_constraint` | MISSING | present |
| `Model.cloth_reference_{drag,k,margin,watertight_whole_shape_index}` | MISSING | present |
| `Model.global_viscous_damping` | MISSING | present |
| `Model.enable_{edge_edge,triangle_particle,particle_particle}_collisions` | MISSING | present |
| `Model.particle_self_intersection_count` | MISSING | present |
| `Model.body_cloth_intersection_count` | MISSING | present |
| `mesh_query_edge` native builtin | MISSING (`builtins.py`: 0 hits; wheel ships no `native/mesh.h`) | present (`builtins.py` 1, `native/mesh.h` 2) |
| `ModelBuilder.add_cloth_mesh`, `add_shape_mesh`, `Model.particle_max_velocity` | present | present |

Two corrections to the raw probe output in `spike/port.log`, both verified and both the probe's
fault, not upstream's:

- It reports `warp.collision.panel_assignment` as **OK** under the override. False positive — the
  module resolved from the *fork* tree
  (`vendor/NvidiaWarp-GarmentCode/warp/collision/panel_assignment.py`) via namespace-path merging.
  The upstream wheel has no `warp/collision` directory at all (`ls`: No such file or directory).
- It reports `wp.mesh_query_edge` MISSING via `hasattr`, which is not a trustworthy check here:
  on 1.9.1 even `wp.mesh_query_point` reads False after `wp.init()`, because builtins are not
  exposed as module attributes in 1.9.x the way they were in beta.6. The `mesh_query_edge` row
  above rests on source-level evidence instead.

## 6. Results

Both items, same bodies, RTX 4090, `resolution_scale` 1.0. Fork numbers from
`runs/out_spike_base/timings.json`; VRAM cross-checked against `nvidia-smi` sampling
(`spike/vram_base_*.log`) and agrees exactly.

| Item | Engine | Sim s | Meshgen s | Peak VRAM | Frames | Fails |
| --- | --- | --- | --- | --- | --- | --- |
| `depop_958293311` tee, size L, A-pose, body `wearer_masc_a45` | fork beta.6 (non-commercial) | **23.25** | 3.05 | **730 MB** | 2399 | `static_equilibrium`, `cloth_body_intersection` |
| `depop_958293311` | upstream 1.9.1 (Apache-2.0) | — | 4.51 (pattern OK) | — | — | **ImportError at import, rc=1** |
| `depop_941190262` sweats, W32, body `wearer_masc` | fork beta.6 (non-commercial) | **14.28** | 4.31 | **812 MB** | 2399 | `static_equilibrium` |
| `depop_941190262` | upstream 1.9.1 (Apache-2.0) | — | 2.97 (pattern OK) | — | — | **ImportError at import, rc=1** |

The fork `fails` entries are pre-existing pipeline behavior on these bodies, unchanged by this
spike — recorded for honesty, not introduced here. Fork run also reported 159 body collisions /
2 self-collisions (tee) and 0 / 3 (sweats). Device `cuda:0` throughout.

Screenshots — fork result beside the port's failure, same body, same camera:

- `spike/compare_depop_958293311.png` — tee
- `spike/compare_depop_941190262.png` — sweats

## 7. Port target decision

Upstream warp **1.9.1** is the smallest *shaped* target: `pygarment` is written against
`warp.sim`, so the module layout matches and only the GarmentCodeData physics is missing. But
`warp.sim` is removed at 1.10 — porting onto it means landing ~3,300 lines of work on a module
that upstream already deleted, with no upgrade path.

**Newton 1.7.0** (PyPI `newton`, `License-Expression: Apache-2.0`) is the better destination. It is
the maintained successor the deprecation warning itself points at, and it has moved toward what we
need: `ModelBuilder`, `SolverXPBD`, `SolverVBD`, `add_cloth_mesh`, `add_shape_mesh`,
`add_shape_collision_filter_pair`, `add_attachment_particle_body`, and self-contact handling
exercised in its XPBD/VBD solver tests. It still has none of GarmentCodeData's specifics
(`implicit_laplacian_smoothing`, `panel_assignment`, `count_self_intersections` — 0 hits each),
and its API differs from `warp.sim`, so `garment.py` would need rewriting rather than patching.

Note: PyPI `newton-physics` is a rename stub whose `__init__.py` only raises
`ImportError("The 'newton-physics' package has been renamed to 'newton'")`. The installable
package is `newton`.

**Effort estimate.** Hand-port surface ≈ **2,900 Python lines + 112 CUDA/C++ lines + the 326-line
`panel_assignment` module** (`stubs.py`'s 328 lines are generated, not hand-written). The native
change is the sharp edge: adding `mesh_query_edge` means building warp/Newton from source, so
"pip install the engine" stops being an option and we own a CUDA toolchain in CI. Against Newton,
add a rewrite of `garment.py`'s sim driver on top, offset by Newton's native self-collision and
attachment primitives possibly replacing parts of the fork's work outright.

**What remains** (not attempted here): decide Newton vs staying non-commercial; if Newton, spike
`garment.py` against `newton.SolverXPBD` with one panel to see whether its attachments and
self-contact substitute for the fork's; confirm whether `mesh_query_edge` is avoidable using
Newton's existing collision queries, since that single builtin is what forces the source build.

## 8. Reproduce

Pod-side, isolated env under `/workspace/spike/` (own venv/targets; `vendor/` and `.venv` untouched):

```sh
/workspace/spike/probe_versions.sh   # warp.sim availability per wheel  -> spike/probe.log
/workspace/spike/run_base.sh         # fork baseline, both items        -> spike/base.log
/workspace/spike/run_port.sh         # upstream-warp override attempt   -> spike/port.log
```

Baseline commands as run:

```sh
cd /workspace/seam/gen3d/drape
uv run --no-sync python -m drape.pattern --inputs runs/inputs --only <item> --bodies runs/bodies --out runs/out_spike_base
uv run --no-sync python -m drape.drape   --inputs runs/inputs --only <item> --bodies runs/bodies --out runs/out_spike_base
```

Artifacts: `spike/` (PNGs, logs, probe + render code), `runs/out_spike_base/` (fork sim objs +
`timings.json`), `runs/out_spike_port/` (patterns only — sim never ran).
