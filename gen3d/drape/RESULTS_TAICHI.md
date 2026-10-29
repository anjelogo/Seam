# Taichi engine on the Intel Arc A770: spike results

A third drape engine, `drape.sim_taichi`, runs our clean-room XPBD loop (the Newton backend's step
order, ported kernel by kernel) on gstaichi over Vulkan. Both spike items run on the A770 and meet
Runs, Gates, Shape, Bottoms and the 5-minute speed gate against Newton's A40 drapes. Stage 2 (the
full 19-row set) and Stage 3 (Metal) were not run inside the 6 h budget; the 17 other scenes are
exported and ready. Branch `anjelo/arc-taichi`.

## Verdict per target

Targets were fixed before any Taichi drape existed and were not changed. `drape/gates.json` is
untouched.

| target | rule | result |
| --- | --- | --- |
| runs | full budget on `--arch vulkan`, no NaN/Inf, no exploded or separated panels, same fail tags | **pass** 2 of 2: 2399 frames, 0 NaN, 0 buffer overflow, fail tags `static_equilibrium` on both engines |
| gates | Newton-pass rows pass; Newton-fail rows fail the same gates or fewer | **pass** 2 of 2: tee `neck_drop, neck_ring` on both (incl. the gates.json `sim_time` gate, 33.1 s vs a 39.8 s budget); sweats has no top gates |
| shape | symmetric mean surface distance ≤ 2 × Newton's re-drape noise floor (0.283 cm) = 0.566 cm | **pass** 2 of 2: tee 0.399 cm, sweats 0.457 cm |
| bottoms | waist held the whole sim; waistband top within 2 cm of Newton's | **pass**: held, 104.3 / 104.3 cm |
| blind review | no item judged worse on Taichi for slide, fit or penetration | **pass** 2 of 2: tee judged better on Taichi (Newton side noisier), sweats equivalent |
| speed | ≤ 5 min per garment on the A770; report anything > 2 × the A40 time with a kernel profile | **pass**: 33.1 s and 64.4 s. Sweats is 3.2 × the A40 (profile below); tee 1.66 × |
| VRAM | report the peak | **not measured**: the Windows `GPU Process Memory` counter returned nothing for the process (see What still fails) |
| metal | Stage 3, only after Stages 1–2 pass | **not run**: Stage 2 not run in budget; commands below |
| license | Windows sim env lists only permissive packages | **pass**: 15 distributions, all MIT / BSD / Apache-2.0 / PSF / MIT-0 |

Noise floor: 0.283 cm is Newton-vs-Newton on the black tee M from RESULTS_NEWTON.md (A40), not
re-measured here: this machine has no CUDA, and Newton on CPU is bit-deterministic (two full CPU
re-drapes of the same garment differ by 0 cm), so it has no run-to-run noise to measure. For scale,
two Taichi re-drapes of the black tee on the A770 differ by **0.273 cm**.

## Parity table (spike items)

Reference: `runs/out_newton2` (Newton 1.7.0 on an A40), copied from the Mac. Taichi:
`runs/out_taichi`. Report: `runs/out_taichi/parity/parity.md` (built by the unchanged `drape.parity`
against `runs/out_newton_scene/ref`, which links the reference parts and carries the 0.283 cm floor).

| row | kind | shape cm (p95 / max) | gates failed Newton → Taichi | waistband cm Newton / Taichi | sim s A40 → A770 | ratio | body / self intersections Newton → Taichi |
| --- | --- | --- | --- | --- | --- | --- | --- |
| texture/depop_954868283 | top | 0.399 (1.47 / 5.10) | neck_drop, neck_ring → same | – | 19.92 → 33.07 | 1.66 | 0 / 21 → 0 / 11 |
| poc/depop_941190262 | bottom | 0.457 (1.55 / 3.28) | – | 104.3 / 104.3, held | 20.42 → 64.44 | 3.16 | 0 / 0 → 0 / 0 |

Paired sheets (Newton top row, Taichi bottom row):
[black tee](runs/out/shots/taichi/texture_depop_954868283.jpg) ·
[sweats](runs/out/shots/taichi/poc_depop_941190262.jpg).

**Start-of-sim agreement.** Frame 0 on the A770 vs Newton's A40 frame-0 dump: max 0.005 cm (tee).
At frame 50 Taichi sits 0.060 cm (mean per vertex) from the A40, while Newton on CPU from the same
scene sits 0.069 cm from it, so the early divergence is the same size as Newton's own
device-to-device spread.

## Blind review, verbatim

A fresh reviewer saw only the four unlabelled sheets (A/B order random per item, seed 20261023) and
replied (the reviewer also flagged an unrelated injected tool-harness message, omitted here):

| item | verdict | slide | fit | penetration | notes |
|---|---|---|---|---|---|
| 1 | A worse | neither slid; both sit at shoulders/hem similar | B cleaner silhouette, flatter collar; A puffs at chest, noisier drape | neither penetrates body | A shows heavy micro-wrinkle noise, especially chest + top-down view |
| 2 | equivalent (slight edge B) | neither; waistband at same height | hem cuffs + leg length match; B marginally smoother on thighs | both show same leg-visible gap at crotch in center view — identical | differences are within sim noise |

> - Item 1 A: front panel has pronounced vertical crumpling and the collar bunches; B drapes as a smooth tee.
> - Item 1: sleeve length, hem height and shoulder seating are indistinguishable; only surface quality differs.
> - Item 2: crotch-gap "penetration" is identical between A and B — looks like a garment pattern issue, not a solver difference.
> - Item 2: creasing pattern on the thigh is the only separator; too close to call reliably.

Decoded (`runs/out_taichi/parity/blind_key.json`; `drape.parity` names the reference side "fork" and
the new side "newton", so "fork" = Newton A40 and "newton" = Taichi here): item 1 is the black tee
with **Taichi = B**, item 2 the sweats with **Taichi = A**. No item is judged worse on Taichi; on the
tee the reviewer preferred Taichi's drape.

## Scene file (T1)

`python -m drape.scene export` freezes a Newton build into `<name>_scene.npz` + `.json`
([SCENE_FORMAT.md](SCENE_FORMAT.md)); `drape.drape --engine newton --scene` and
`python -m drape.sim_taichi.run --scene` both start from it.

- Two exports of the same garment are byte-identical (sha256 of all 38 arrays).
- Newton from the scene vs Newton's normal path, same machine (WSL2 CPU), both items, frames 0 and
  50: **0.0000 cm** max difference. Two full-budget synthetic runs: 0 cm at every dump.
- Newton from the scene on CPU vs the A40 reference at frame 0: max 0.003 cm (tee), 0.019 cm
  (sweats, one vertex; mean 0.0000). That is CPU vs CUDA, not the loader.
- Exporting against a reference needs `--reuse-mesh`: pygarment's mesher on this WSL2 env writes the
  same topology as the pod but in a different vertex order for the tee (up to 67 cm apart per index),
  and differs in the last float digits elsewhere. Reusing the reference's box mesh makes all 19 scenes
  mesh-identical to `out_newton2`.

## Setup

| piece | version |
| --- | --- |
| OS | Windows 11 Pro 10.0.26300, native Python for the sim; WSL2 Ubuntu for export, Newton CPU, parity |
| GPU | Intel Arc A770 16 GB, driver 32.0.101.9034 (2026-09-29; not updated in this session), Vulkan 1.4.356 |
| Taichi | **gstaichi 4.6.0** (Genesis fork, Apache-2.0), `ti.init(arch=ti.vulkan, fast_math=False, default_fp=ti.f32)` |
| Python | 3.12.0 (`.venv-taichi`), numpy 2.5.4 |
| export side | newton 1.7.0, warp-lang 1.18.0 (CPU), pygarment `d449629`, Python 3.12 (`.venv-wsl`) |

**taichi vs gstaichi.** Upstream `taichi` 1.7.4 initialises Vulkan on the A770, but `to_numpy()`
returned the wrong field's data (one field read back another's values, a second read zeros) on this
GPU; element reads were right. gstaichi 4.6.0 passed the same probe, and its atomics return correct
disjoint blocks (1 M threads reserving 1–7 slots each). gstaichi keeps Vulkan, Metal, CUDA and CPU
and drops the GUI, AOT and C-API, none of which the engine uses. Pinned: `gstaichi==4.6.0`.

Wave 0 checks: `ti.init(arch=ti.vulkan)` logs `Found Vulkan Device 0 (Intel(R) Arc(TM) A770
Graphics)`; a 1 M-thread atomic kernel and a 64×64 XPBD hanging-cloth demo (600 frames × 10
substeps in 1.04 s) ran clean.

## Engine notes: f32, atomics, broad phase

- **f32 only.** No f64 in any kernel. The piercing survey's watertight ray–triangle test took its
  2D edge functions in float64 on Newton; here they are exact-sign f32 products via mantissa
  splitting and TwoSum (robust to driver FMA contraction). 1 M random rays: 0 hit mismatches against
  the f64 test; 3 000 rays aimed exactly at shared edges of coplanar triangles: 9 mismatches on
  Vulkan, 2 on CPU.
- **Atomics.** Plain `ti.atomic_add` on f32 components and i32 counters; one global buffer per pass
  with whole-block reservation and an overflow counter, as in sim_newton. Overflow on both items: 0.
- **Body.** A flat BVH (median split, one triangle per leaf, skip pointers) built once in numpy and
  traversed in kernels; closest point, sign by angle-weighted pseudo-normal, first-hit ray with sign
  and any-hit, ported from warp 1.18 (Apache-2.0). Against an f64 brute force: 0 sign, 0 any-hit and
  1 inside-vote mismatch over 1 070 adversarial points; closest-point ties differ only in which of
  two equidistant faces is named (distance agrees to 4e-6 cm).
- **Self-contact broad phase.** A uniform hash grid over triangle AABBs, rebuilt at each frame start
  (count, chunked scan, fill), returning each overlapping triangle exactly once (0 mismatches vs brute
  force on 40 k triangles). Edge–edge de-duplication uses the precomputed neighbour face across each
  edge instead of rescanning the slot block (Newton's O(n²) scan cost 354 ms/frame on the A770); for
  boxes over 512 cells (open seams in the first frames) the pass scans faces linearly. Both pick the
  same surviving copy of a shared edge up to which face's copy is kept, which is geometrically the
  same constraint.
- **Launches.** All per-substep passes run as one fused kernel (10 launches a frame instead of ~110).
  A full 10-substep unroll did not compile in gstaichi within 20 min. Fusion changed only launch
  structure; float-atomic ordering makes runs differ from each other either way.
- **Vulkan vs CPU.** Same code path; on a two-layer test cloth 30 of 198 396 edge–edge candidate slots
  flip at the band threshold between the two backends (1-ulp differences in `_seg_seg`).

## Speed and profile

| item | A40 Newton | A770 Taichi | steady state (frames > 300) | first 100 frames |
| --- | --- | --- | --- | --- |
| black tee | 19.9 s | 33.1 s | ~10 ms/frame | ~4.5 s for frame 0 (kernel cache load), then 20–32 ms/frame |
| sweats | 20.4 s | 64.4 s | ~15 ms/frame (synced profile) | dominated by open sewing seams |

Sweats is over 2 × the A40. Top three costs per frame at steady state (synchronised timing, so each
includes a launch): `Body.generate` 3.5 ms (closest-point BVH query per particle), the fused substep
0.43 ms × 10 = 4.3 ms, `SelfContact.detect_edge_edge` 2.2 ms; then `detect_point_triangle` 1.1 ms.
In the first frames the long open-seam springs make `detect_edge_edge` and the piercing survey the
cost, one GPU thread scanning thousands of triangles.

## Metal (Stage 3): not run

Not run: Stage 2 did not run inside the budget, so Stage 3's precondition was not met. On the Mac
(Apple Silicon), from `gen3d/drape` with this branch checked out and the two scenes copied from
`runs/out_newton_scene/{texture,poc}`:

```
bash drape/scripts/setup_taichi.sh
for s in runs/out_newton_scene/texture/depop_954868283 runs/out_newton_scene/poc/depop_941190262; do
  part=$(basename $(dirname $s)); safe=$(basename $s)
  .venv-taichi/bin/python -m drape.sim_taichi.run --scene $(ls $s/sim/*/*_scene.npz) --arch metal \
    --out runs/out_taichi_metal/$part/$safe/sim --timings runs/out_taichi_metal/$part/timings.json
done
# then, in the drape env: panels, bind, parity against runs/out_newton_scene/ref
```

## License report

`pip-licenses` over `.venv-taichi` (the whole Windows sim env):

| package | version | license |
| --- | --- | --- |
| gstaichi | 4.6.0 | Apache-2.0 |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pydantic, pydantic_core, annotated-types, typing-inspection | 2.14.1, 2.50.1, 0.8.0, 0.4.4 | MIT |
| rich, markdown-it-py, mdurl | 15.0.0, 4.2.0, 0.1.2 | MIT |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.12 | BSD-3-Clause |
| Pygments | 2.21.0 | BSD-2-Clause |
| colorama, dill | 0.4.6, 0.4.1 | BSD |
| typing_extensions | 4.16.0 | PSF-2.0 |

No copyleft, no NVIDIA, no non-commercial terms. New dependency: gstaichi (Apache-2.0). No vendored
code was edited and no patch to third-party code was needed.

Clean-room: every implementer brief carried CLEANROOM.md's rules; all reports ended with "I did not
open any NvidiaWarp-GarmentCode file, pre-1.7 warp, warp/sim, or pygarment/meshgen/simulation.py".
Adapted Apache-2.0 code carries a one-line attribution (`constraints.py` from Newton's XPBD kernels,
`body.py` from warp 1.18 mesh queries, the f32 port of warp's watertight ray test).

## Spend

$0. No pods or paid APIs; the blind review used a local reviewer agent. Nothing to stop.

## What still fails or is unverified

- **Stage 2 not run.** The 17 other rows have scenes exported (`runs/out_newton_scene/<part>/<safe>`,
  all mesh-identical to the reference) but were not simulated or compared.
- **Metal not run** (above).
- **VRAM not measured.** The `typeperf "\GPU Process Memory(pid_<pid>*)\Dedicated Usage"` sampler
  returned no rows on this machine; `vram_mb` is null in both records.
- **Sweats speed** is 3.2 × the A40 (inside the 5 min gate). The early open-seam frames and the
  per-particle body query are where the time goes.
- **Shape headroom.** Both items pass, but at 0.40 and 0.46 cm against a 0.566 cm bar: closer than
  Newton-vs-fork was (0.26 and 0.19 cm). Taichi-vs-Taichi on the tee is 0.27 cm, so the gap is within
  a re-drape or two of this engine's own spread; the 17-row run would show whether any row crosses.
- **Edge cases of the f32 ray test** (9 / 3 000 adversarial shared-edge rays on Vulkan) are the same
  family as the coplanar-layout residual in RESULTS_NEWTON.md difference 1.

## Recommendation

A Vulkan engine is viable for local baking: on a consumer Arc card it reproduces Newton's drapes
within the same bar Newton met against the fork, in 0.5–1 min per garment, with only gstaichi and
numpy on the GPU host. To make it production-grade: run the 19-row set and Metal; measure VRAM with
a working counter (or Level Zero sysman); cut the first-frame cost (cache warm-up and the open-seam
broad phase, e.g. split long springs' queries across threads); parallelise `Body.generate`'s
closest-point query better; and pin a driver version in the setup script.

## Re-running

```
# WSL2 / Linux / Mac drape env: export scenes against a reference run (copy its pattern/ and sim/<name>/ first)
.venv-wsl/bin/python -m drape.scene export --inputs runs/inputs_texture --only depop_954868283 \
  --out runs/out_newton_scene/texture --dump-every 50 --reuse-mesh
# Newton from a scene
.venv-wsl/bin/python -m drape.drape --engine newton --scene <name>_scene.npz --out <run>/<part>/<safe>/sim
# Windows: sim env, then the Taichi run
powershell -ExecutionPolicy Bypass -File drape/scripts/setup_taichi.ps1
.venv-taichi\Scripts\python.exe -m drape.sim_taichi.run --scene <name>_scene.npz --arch vulkan `
  --out runs/out_taichi/<part>/<safe>/sim --timings runs/out_taichi/<part>/timings.json
# drape env: panels, bind, parity (reference root links out_newton2 and carries noise_floor.json)
.venv-wsl/bin/python -m drape.panels --out runs/out_taichi/<part> --only <safe>
.venv-wsl/bin/python -m drape.bind --inputs <inputs> --out runs/out_taichi/<part> --bodies runs/bodies --only <safe>
.venv-wsl/bin/python -m drape.parity --ref runs/out_newton_scene/ref --new runs/out_taichi --sheets --blind runs/out_taichi/parity/blind
```
