# Taichi engine on the Intel Arc A770: spike results

A third drape engine, `drape.sim_taichi`, runs our clean-room XPBD loop (the Newton backend's step
order, ported kernel by kernel) on gstaichi over Vulkan. Stage 2 ran all 19 reference rows on the
A770 against Newton's A40 drapes with the Stage 1 targets unchanged. Runs, Bottoms, Blind review,
Speed and VRAM pass on all 19; Shape passes 18 of 19 and Gates 17 of 19. The three misses sit at
the bar and follow this engine's own run-to-run spread, not a defect we could find (below). Stage 3
(Metal) was not run. Branch `anjelo/arc-taichi`.

## Verdict per target (19 rows)

Targets were fixed before any Taichi drape existed and were not changed. `drape/gates.json` is
untouched. Run of record: `runs/out_taichi_s3` (why not `runs/out_taichi`: see Runs on this machine).

| target | rule | result |
| --- | --- | --- |
| runs | full budget on `--arch vulkan`, no NaN/Inf, no exploded or separated panels, same fail tags | **pass** 19 of 19: 2399 frames each, 0 NaN, 0 buffer overflow; fail tags equal Newton's on every row (`static_equilibrium` everywhere, plus `cloth_body_intersection` on the two stress bottoms on both engines). Needed engine fix 1 below |
| gates | Newton-pass rows pass; Newton-fail rows fail the same gates or fewer | **fail** 17 of 19. `poc/grailed_108767954` (hoodie) newly fails `armhole` (5.90 cm vs a 5.0 limit; Newton 4.74). `sweep_XS` adds `armhole` (5.02; Newton 4.75). Two rows fail fewer (`grailed_109137061` penetration, `depop_958293311` neck_drop) |
| shape | symmetric mean surface distance ≤ 0.566 cm | **fail** 18 of 19. `poc/depop_941190262` (sweats) 0.570 cm. Range of the rest 0.105–0.480 |
| bottoms | waist held the whole sim; waistband top within 2 cm of Newton's | **pass** 7 of 7: all held, waistband deltas ≤ 0.1 cm |
| blind review | no item judged worse on Taichi for slide, fit or penetration | **pass** 19 of 19: every item judged equivalent |
| speed | ≤ 5 min per garment on the A770; report the ratio to the A40 | **pass**: 31.2–43.9 s, ratio 1.01–2.27 (table). Every top also passes the gates.json `sim_time` gate |
| VRAM | a measured peak per row, ≤ 4 GB | **pass**: 335–736 MB above an idle baseline of 3.0–3.4 GB (adapter-wide counter) |
| metal | Stage 3, only after Stages 1–2 pass | **not run**: Stage 2 did not pass every target; commands below |
| license | Windows sim env lists only permissive packages | **pass**: unchanged from Stage 1, no new dependency |

Noise floor: 0.283 cm, Newton-vs-Newton on the black tee M from RESULTS_NEWTON.md (A40), not
re-measured here (this machine has no CUDA, and Newton on CPU is bit-deterministic).

## Parity table (run of record)

Reference: `runs/out_newton2` (Newton 1.7.0 on an A40) through `runs/out_newton_scene/ref`.
Taichi: `runs/out_taichi_s3`. Report: `runs/out_taichi_s3/parity/parity.md` and `parity.json`, built
by the unchanged `drape.parity` (20 000 samples, seed 20261023). p95 / max are the larger of the two
directions. VRAM is the peak above the idle baseline taken just before each run.

| row | kind | shape cm (p95 / max) | gates failed Newton → Taichi | waistband cm Newton / Taichi | sim s A40 → A770 | ratio | VRAM MB | body / self Newton → Taichi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| texture/depop_936695379 | bottom | 0.188 (0.71 / 2.50) | – | 104.5 / 104.5, held | 23.20 → 32.15 | 1.39 | 404 | 0 / 0 → 0 / 0 |
| texture/depop_945724547 | bottom | 0.105 (0.39 / 1.20) | – | 104.1 / 104.1, held | 19.01 → 31.23 | 1.64 | 365 | 0 / 0 → 0 / 0 |
| texture/grailed_109046872 | bottom | 0.280 (0.99 / 2.71) | – | 102.5 / 102.4, held | 19.35 → 43.86 | 2.27 | 406 | 119 / 17 → 116 / 29 |
| texture/depop_958674696 | bottom | 0.118 (0.59 / 3.45) | – | 103.0 / 103.1, held | 20.11 → 41.59 | 2.07 | 508 | 113 / 20 → 109 / 120 |
| texture/depop_958854988 | bottom | 0.169 (0.58 / 1.74) | – | 104.4 / 104.4, held | 20.34 → 33.07 | 1.63 | 508 | 0 / 0 → 0 / 0 |
| texture/depop_958141161 | top | 0.385 (1.27 / 3.93) | neck_drop, neck_ring → same | – | 20.17 → 33.69 | 1.67 | 736 | 0 / 27 → 0 / 27 |
| texture/depop_959308776 | top | 0.256 (0.94 / 2.60) | neck_drop, neck_ring → same | – | 29.87 → 34.14 | 1.14 | 458 | 0 / 14 → 0 / 9 |
| texture/grailed_109137061 | top | 0.233 (0.82 / 3.11) | penetration → none | – | 27.09 → 33.78 | 1.25 | 424 | 0 / 36 → 0 / 9 |
| texture/depop_953525988 | top | 0.480 (1.51 / 4.49) | armhole, neck_ring, sleeve_hem → same | – | 25.33 → 35.16 | 1.39 | 440 | 0 / 91 → 0 / 79 |
| texture/depop_957013558 | bottom | 0.198 (0.64 / 2.13) | – | 104.5 / 104.5, held | 19.56 → 32.23 | 1.65 | 426 | 0 / 0 → 0 / 2 |
| texture/depop_959195954 | top | 0.245 (0.91 / 2.33) | armhole → same | – | 31.44 → 37.15 | 1.18 | 513 | 0 / 14 → 0 / 216 |
| texture/depop_954868283 | top | 0.418 (1.38 / 3.65) | neck_drop, neck_ring → same | – | 19.92 → 33.50 | 1.68 | 348 | 0 / 21 → 0 / 14 |
| poc/depop_941190262 | bottom | **0.570 (2.29 / 5.19) FAIL** | – | 104.3 / 104.3, held | 20.42 → 33.09 | 1.62 | 459 | 0 / 0 → 0 / 3 |
| poc/grailed_108767954 | top | 0.359 (1.32 / 3.42) | **none → armhole FAIL** | – | 37.45 → 37.81 | 1.01 | 465 | 0 / 77 → 0 / 153 |
| poc/grailed_108843068 | bottom | 0.184 (0.62 / 1.20) | – | 104.3 / 104.3, held | 20.63 → 34.14 | 1.65 | 555 | 0 / 0 → 0 / 0 |
| poc/depop_958293311 | top | 0.465 (1.62 / 3.21) | neck_drop, neck_ring → neck_ring | – | 24.45 → 34.07 | 1.39 | 369 | 0 / 15 → 0 / 40 |
| sweep_XS/depop_954868283 | top | 0.305 (1.28 / 3.05) | **neck_drop, neck_ring → armhole, neck_drop, neck_ring FAIL** | – | 18.09 → 31.72 | 1.75 | 335 | 0 / 0 → 0 / 0 |
| sweep_M/depop_954868283 | top | 0.357 (1.28 / 3.97) | neck_drop, neck_ring → same | – | 19.59 → 32.84 | 1.68 | 354 | 0 / 37 → 0 / 21 |
| sweep_XL/depop_954868283 | top | 0.415 (1.32 / 3.99) | armhole, neck_ring, sleeve_hem → same | – | 26.17 → 34.25 | 1.31 | 391 | 0 / 49 → 0 / 22 |

The parity report's own row verdict also applies `sim ≤ 2 × fork`; that is not a Stage 2 target, and
it marks the two stress bottoms (2.27, 2.07) besides the three misses above. Self-intersection counts
are higher on two hooded/layered tops (`depop_959195954` 14 → 216, the hoodie 77 → 153); neither
crosses the `max_self_collisions` tag and the penetration gate passes on both.

Paired sheets, Newton top row and Taichi bottom row, all 19 in
[runs/out/shots/taichi/](runs/out/shots/taichi/) (JPEG, 93–149 KB each), e.g. the three misses:
[sweats](runs/out/shots/taichi/poc_depop_941190262.jpg) ·
[hoodie](runs/out/shots/taichi/poc_grailed_108767954.jpg) ·
[tee XS](runs/out/shots/taichi/sweep_XS_depop_954868283.jpg).

## The three misses: diagnosis

Fix loop 2 compared the dumps (every 50 frames) of two full Taichi runs of each failing row against
Newton's A40 dumps, with the passing black tee as a control (mean / max per vertex, cm):

| row | frame 0 Taichi–Newton | frame 100 Taichi–Newton | final Taichi–Newton (run of record) | final Taichi–Taichi (two runs) |
| --- | --- | --- | --- | --- |
| hoodie `grailed_108767954` | 0.005 / 0.16 | 0.61 / 3.43 | 0.86 / 6.02 | 0.84 / 6.21 |
| sweats `depop_941190262` | 0.004 / 0.13 | 0.51 / 3.30 | 0.98 / 7.85 | 0.78 / 7.51 |
| tee XS | 0.006 / 0.16 | 0.42 / 3.66 | 0.54 / 5.56 | 0.31 / 3.18 |
| tee M (passes) | 0.005 / 0.16 | 0.57 / 4.43 | 0.83 / 5.43 | 0.43 / 3.17 |

Start states agree to 0.005 cm, the failing rows drift from Newton on the same curve as the passing
tee, and two Taichi runs of the same garment end about as far from each other as from Newton. A
localised engine defect would show as both Taichi runs agreeing and missing Newton together; that is
not what the dumps show. The same rows across runs:

| row / metric (bar) | Stage 1 | contaminated run (`out_taichi_s2`) | run of record (`out_taichi_s3`) | Newton |
| --- | --- | --- | --- | --- |
| sweats shape (≤ 0.566) | 0.457 | 0.406 | 0.570 | – |
| hoodie armhole (≤ 5.0) | – | 4.71 | 5.90 | 4.74 |
| tee XS armhole (≤ 5.0) | – | 5.12 | 5.02 | 4.75 |

Both armhole rows sit within 0.26 cm of the limit on Newton itself, and `armhole` is a per-vertex
maximum, so it moves with the drape's spread. No change was made: making the engine quieter here
would mean changing physics parameters to hit a target, which the rules forbid. These rows stay
**fails**, and only the run of record counts; the contaminated run is shown for spread, not as a
substitute.

## Engine fixes in Stage 2

1. **Edge–edge buffers over Vulkan's dispatch limit** (`c5252b8`). Three rows
   (`texture/depop_958854988`, `poc/grailed_108767954`, `poc/grailed_108843068`) crashed at init with
   `GfxRuntime::launch_kernel Dispatch error: RhiResult(not_supported)` at `ee_filtered.fill(1)`.
   Their edge–edge slot buffers (`ee_per_spring × springs`) are 8.45 M, 9.30 M and 8.56 M; every row
   that ran was ≤ 8.10 M, and one launch is capped at 65 535 workgroups × 128 = 8 388 480 threads on
   the A770. The fill, `_solve_ee` and the edge–edge loop in the fused substep now launch at most
   that many threads and stride the rest. Below the cap every slot still gets its own thread, so the
   16 rows that ran are on the same code path. Before: 3 crashes (`frames -1`, `crashes` tag). After:
   all 3 run 2399 frames, shape 0.169 / 0.359 / 0.184 cm.
2. **macOS `._*` files copied into the run** (`79a7e3a`). The exported `sweep_XL` scene dir carries
   AppleDouble files; `_copy_siblings` copied `._…_specification.json`, which `drape.panels` then
   read as the spec (`UnicodeDecodeError`). The copy now skips `._*` files. Sim results unaffected.

No other engine change. Patches to third-party code: none.

## VRAM sampler (S1)

`drape/sim_taichi/vram.py` (`4aac92a`) reads `\GPU Adapter Memory(*)\Dedicated Usage` through PDH
via ctypes (no new dependency), locks onto the busiest adapter instance (the A770,
`luid_…_0x0000D63A`; the Parsec virtual adapter reads 0), takes a min-of-4 idle baseline just
before the sim, then samples every 0.25 s. The record gains `vram_peak_mb` (= `vram_mb`, peak minus
baseline), `vram_baseline_mb`, `vram_peak_raw_mb`, `vram_samples`. Proof it moves: a 1 GiB gstaichi
field allocation read as +1163.3 MB (baseline 3207.2, peak 4370.5, 24 samples at 4.5 Hz). In the run
of record each row got 111–147 samples (~3.5 Hz). The counter is adapter-wide: any other GPU program
running at the same time lands in the number, which is why the contaminated run is not used for it.

## Runs on this machine

- `runs/out_taichi`: Stage 1 (2 rows) plus Stage 2 batch 1 (17 rows, pre-fix: 3 crashes). Kept.
- `runs/out_taichi_vram`: the 2 Stage 1 rows re-run for a VRAM number in batch 1. Kept.
- `runs/out_taichi_w0`: Wave 0 drift check, black tee: shape 0.409 cm vs Stage 1 0.399 (Δ 0.010,
  limit 0.05), same gates, 33.5 s.
- `runs/out_taichi_s2`: all 19 after fix 1, but with two games (Roblox 18.5 % and CS2 24.9 % of the
  A770 by `\GPU Engine` utilisation) running. Times 40–103 s; every top then failed `sim_time` and
  one VRAM peak read 2930 MB. Shape passed 19 of 19, Gates failed on `sweep_XS` armhole and on
  `sim_time`. Not used for any verdict.
- `runs/out_taichi_s3`: **run of record**, all 19 with the GPU idle (checked before start; CS2 closed,
  Roblox open but at 0 % GPU). Declared the run of record before its results existed.

## Blind review, verbatim

Reviewer input followed [REVIEW_PROVENANCE.md](REVIEW_PROVENANCE.md): the 38 unlabelled sheets
(A/B random per item, seed 20261023) copied to a `%TEMP%` folder with no README / AGENTS.md above
it, a fresh opencode `general` agent (not a `sisyphus`/`atlas` key, so the skill-reminder hook does
not arm), and only the rubric. Its tool log in `opencode.db` holds exactly 38 `read` calls and every
result is `Image read successfully` plus the image: no injected text this time. Full prompt:
`runs/out_taichi_s3/parity/blind/prompt.md`; reply: `reply.md` beside it.

| item | verdict | slide | fit | penetration | note |
|---|---|---|---|---|---|
| 1 | equivalent | A on shoulders; B on shoulders | A same hem and sleeves as B; B same as A | A none seen; B none seen | within sim noise (A has slightly more ragged sleeve edges) |
| 2 | equivalent | A waistband held; B waistband held | A cuffs at ankle; B cuffs at ankle, same waist height | A none; B none | within sim noise |
| 3 | equivalent | A on shoulders; B on shoulders | A long sleeves and hem same as B; B same as A | A none; B none | within sim noise |
| 4 | equivalent | A waist held; B waist held | A straight legs, same hem as B; B same as A | A none; B none | within sim noise |
| 5 | equivalent | A waist held; B waist held | A bunched hems at ankle; B the same | A none; B none | within sim noise (both crumple at the ankles) |
| 6 | equivalent | A waist held; B waist held | A cuffs and leg volume same as B; B same as A | A none; B none | within sim noise |
| 7 | equivalent | A on shoulders; B on shoulders | A hem and sleeves same as B; B same as A | A none; B none | within sim noise |
| 8 | equivalent | A waist held; B waist held | A tied ankles, same as B; B same as A | A none; B none | within sim noise |
| 9 | equivalent | A on shoulders; B on shoulders | A boxy hem, same as B; B same as A | A none; B none | within sim noise (both have heavy front creasing) |
| 10 | equivalent | A hood and shoulders held; B the same | A hem and sleeves same as B; B same as A | A none; B none | within sim noise (hood folds differ slightly) |
| 11 | equivalent | A on shoulders; B on shoulders | A wide sleeves and hem same as B; B same as A | A none; B none | within sim noise (both have crinkly sleeves) |
| 12 | equivalent | A on shoulders; B on shoulders | A hem and sleeves same as B; B same as A | A none; B none | within sim noise |
| 13 | equivalent | A waist held; B waist held | A wide legs, same hem as B; B same as A | A none; B none | within sim noise |
| 14 | equivalent | A high waist held; B the same | A wide legs, same as B; B same as A | A none; B none | within sim noise |
| 15 | equivalent | A on shoulders; B on shoulders | A V-neck and hem same as B; B same as A | A small dark spot at neck; B small dark spot at neck | within sim noise |
| 16 | equivalent | A high waist held; B the same | A wide legs, same as B; B same as A | A none; B none | within sim noise |
| 17 | equivalent | A hood and shoulders held; B the same | A cropped hem, same as B; B same as A | A none; B none | within sim noise |
| 18 | equivalent | A on shoulders; B on shoulders | A neckline slightly higher than B; B slightly lower | A none; B none | within sim noise |
| 19 | equivalent | A on shoulders; B on shoulders | A hem and sleeves same as B; B same as A | A none; B none | within sim noise |

Decoded (`runs/out_taichi_s3/parity/blind_key.json`; `drape.parity` calls the reference side "fork"
and the new side "newton", so "newton" = **Taichi** here):

| item | row | Taichi | item | row | Taichi |
| --- | --- | --- | --- | --- | --- |
| 1 | texture/depop_954868283 | B | 11 | texture/depop_953525988 | A |
| 2 | texture/depop_957013558 | B | 12 | poc/depop_958293311 | A |
| 3 | texture/depop_959308776 | A | 13 | texture/depop_958854988 | B |
| 4 | poc/grailed_108843068 | B | 14 | texture/depop_945724547 | B |
| 5 | texture/depop_958674696 | A | 15 | texture/grailed_109137061 | B |
| 6 | poc/depop_941190262 | B | 16 | texture/depop_936695379 | A |
| 7 | sweep_XS/depop_954868283 | A | 17 | texture/depop_959195954 | A |
| 8 | texture/grailed_109046872 | A | 18 | texture/depop_958141161 | B |
| 9 | sweep_XL/depop_954868283 | B | 19 | sweep_M/depop_954868283 | B |
| 10 | poc/grailed_108767954 | B | | | |

All 19 equivalent, including the three metric misses (items 6, 7, 10): the reviewer saw no slide,
fit or penetration difference on the sweats, the tee XS or the hoodie.

## Provenance of the Stage 1 "injected tool-harness message"

Full write-up: [REVIEW_PROVENANCE.md](REVIEW_PROVENANCE.md). The text was a `[Category+Skill
Reminder]` block (skill list plus a `task(category="visual-engineering", …)` suggestion) from the
oh-my-openagent plugin's `category-skill-reminder` hook. The hook arms on the third work-tool call of
a `sisyphus*`/`atlas*` agent and was appended to the reviewer's `read` result for `2_A.jpg`. It names
no garment, engine or side; the reviewer flagged it as a prompt injection and ignored it, so it could
not have steered a verdict. A second leak in the same session: `directory-readme-injector` appended
the project README to the `1_A.jpg` read (project context, nothing about which side is which). The
images themselves are bare JFIF with no embedded text. Both sources were avoided in Stage 2 as above.

## Scene file (T1)

`python -m drape.scene export` freezes a Newton build into `<name>_scene.npz` + `.json`
([SCENE_FORMAT.md](SCENE_FORMAT.md)); `drape.drape --engine newton --scene` and
`python -m drape.sim_taichi.run --scene` both start from it. Two exports of the same garment are
byte-identical; Newton from the scene matches Newton's normal path to 0.0000 cm on the same machine.
Exporting against a reference needs `--reuse-mesh` (pygarment's mesher on WSL2 orders the tee's
vertices differently from the pod); with it all 19 scenes are mesh-identical to `out_newton2`.

## Setup

| piece | version |
| --- | --- |
| OS | Windows 11 Pro 10.0.26300, native Python for the sim; WSL2 Ubuntu for export, Newton CPU, parity |
| GPU | Intel Arc A770 16 GB, driver 32.0.101.9034 (unchanged since Stage 1), Vulkan 1.4.356 |
| Taichi | **gstaichi 4.6.0** (Genesis fork, Apache-2.0), `ti.init(arch=ti.vulkan, fast_math=False, default_fp=ti.f32)` |
| Python | 3.12.0 (`.venv-taichi`), numpy 2.5.4 |
| export side | newton 1.7.0, warp-lang 1.18.0 (CPU), pygarment `d449629`, Python 3.12 (`.venv-wsl`) |

**taichi vs gstaichi.** Upstream `taichi` 1.7.4 initialises Vulkan on the A770, but `to_numpy()`
returned the wrong field's data on this GPU; gstaichi 4.6.0 passed the same probe and its atomics
return correct disjoint blocks. Pinned: `gstaichi==4.6.0`.

## Engine notes: f32, atomics, broad phase

- **f32 only.** The piercing survey's watertight ray–triangle test uses exact-sign f32 products via
  mantissa splitting and TwoSum (Newton used float64). 1 M random rays: 0 mismatches against f64;
  3 000 rays aimed at shared edges of coplanar triangles: 9 mismatches on Vulkan, 2 on CPU.
- **Atomics.** Plain `ti.atomic_add` on f32 components and i32 counters; one global buffer per pass
  with whole-block reservation and an overflow counter. Overflow on all 19 rows: 0. Float-atomic
  ordering makes two runs of the same scene differ; that is the spread in the diagnosis above.
- **Body.** Flat BVH built once in numpy, closest point with angle-weighted pseudo-normal sign,
  ported from warp 1.18 (Apache-2.0).
- **Self-contact broad phase.** Uniform hash grid over triangle AABBs rebuilt each frame;
  edge–edge de-duplication via the precomputed neighbour face; boxes over 512 cells scan faces
  linearly. Slot buffers over the dispatch cap are strided (fix 1).
- **Launches.** All per-substep passes run as one fused kernel (10 launches a frame).

## Speed and profile

With the GPU idle every row takes 31–44 s on the A770 (A40: 18–37 s), ratio 1.01–2.27. The two rows
over 2 × are the stress bottoms (43.9 s and 41.6 s), the only rows with ~110 body contacts at the
end. They were not re-profiled; Stage 1's synchronised profile of the sweats has `Body.generate`
(per-particle closest-point BVH query, 3.5 ms/frame) as the top cost, then the fused substep
(4.3 ms/frame) and `detect_edge_edge` (2.2 ms). Stage 1's sweats time (64.4 s, 3.2 ×) is now 33.1 s
with no engine speed change, so that Stage 1 number was probably also taken under other GPU load. A
GPU shared with a game roughly doubles every time (contaminated run: 40–103 s).

## Metal (Stage 3): not run

Not run: Stage 2 did not pass every target. On the Mac (Apple Silicon), from `gen3d/drape` with this
branch checked out and the scenes copied from `runs/out_newton_scene/<part>`:

```
bash drape/scripts/setup_taichi.sh
for s in runs/out_newton_scene/{texture,poc,sweep_XS,sweep_M,sweep_XL}/*; do
  part=$(basename $(dirname $s)); safe=$(basename $s)
  .venv-taichi/bin/python -m drape.sim_taichi.run --scene $(ls $s/sim/*/*_scene.npz) --arch metal \
    --out runs/out_taichi_metal/$part/$safe/sim --timings runs/out_taichi_metal/$part/timings.json
done
# then, in the drape env: panels, bind, parity against runs/out_newton_scene/ref
```

## License report

`pip-licenses` over `.venv-taichi`: gstaichi 4.6.0 (Apache-2.0), numpy (BSD-3-Clause and permissive
bundles), pydantic family, rich, markdown-it-py, mdurl (MIT), cffi (MIT-0), pycparser (BSD-3-Clause),
Pygments (BSD-2-Clause), colorama, dill (BSD), typing_extensions (PSF-2.0). No new dependency in
Stage 2 (the VRAM sampler uses Windows' `pdh.dll` through the standard library's ctypes). No vendored
code was edited and no patch to third-party code was needed.

Clean-room: CLEANROOM.md's rules held for every brief; no NvidiaWarp-GarmentCode file, pre-1.7 warp,
warp/sim, or pygarment/meshgen/simulation.py was opened. Adapted Apache-2.0 code carries a one-line
attribution (`constraints.py` from Newton's XPBD kernels, `body.py` from warp 1.18 mesh queries).

## Spend

$0. No pods or paid APIs; the blind review used a local reviewer agent. Nothing to stop.

## What still fails or is unverified

- **Shape on the sweats** (`poc/depop_941190262`): 0.570 cm against 0.566 in the run of record
  (0.457 in Stage 1, 0.406 in the contaminated run).
- **Armhole gate on the hoodie and the tee XS**: 5.90 and 5.02 cm against 5.0, where Newton is at
  4.74 and 4.75. Both are rows Newton itself passes by under 0.3 cm.
- **The engine's run-to-run spread** (two Taichi runs end 0.3–0.8 cm mean apart per vertex) is about
  the size of its distance to Newton, so near-bar rows pass or fail by draw.
- **Metal not run.** **The two stress bottoms** were not re-profiled at 2.07–2.27 × the A40.
- **VRAM is adapter-wide**, so it is only meaningful with the GPU otherwise idle (the run of record
  was).

## Recommendation

On a consumer Arc card the Vulkan engine gives the same drape as Newton by eye on all 19 rows (blind
review 19/19 equivalent), holds every waist, runs each garment in 31–44 s within 0.75 GB of VRAM,
and crashes on nothing after fix 1. It misses three fixed bars by small margins (0.004 cm of shape,
0.02 and 0.90 cm of armhole), and the evidence puts those on its float-atomic run-to-run spread
rather than a modelling difference. Good enough for local previews and baking where a re-drape is
acceptable; not yet a drop-in for Newton as the reference engine. Next: make the solve order
deterministic (sorted contact slots, or integer fixed-point accumulation for the atomic sums) and
re-measure Taichi-vs-Taichi spread before re-running the 19 rows; then Metal; then the
`Body.generate` query for the stress bottoms; and pin the driver in the setup script.

## Re-running

```
# WSL2 / Linux / Mac drape env: export scenes against a reference run (copy its pattern/ and sim/<name>/ first)
.venv-wsl/bin/python -m drape.scene export --inputs runs/inputs_texture --only depop_954868283 \
  --out runs/out_newton_scene/texture --dump-every 50 --reuse-mesh
# Windows, GPU otherwise idle: the Taichi run (VRAM sampled automatically on vulkan)
powershell -ExecutionPolicy Bypass -File drape/scripts/setup_taichi.ps1
.venv-taichi\Scripts\python.exe -m drape.sim_taichi.run --scene <name>_scene.npz --arch vulkan `
  --out runs/out_taichi_s3/<part>/<safe>/sim --timings runs/out_taichi_s3/<part>/timings.json
# drape env: panels, bind, parity (reference root links out_newton2 and carries noise_floor.json)
.venv-wsl/bin/python -m drape.panels --out runs/out_taichi_s3/<part> --only <safe>
.venv-wsl/bin/python -m drape.bind --inputs <inputs> --out runs/out_taichi_s3/<part> --bodies runs/bodies --only <safe>
.venv-wsl/bin/python -m drape.parity --ref runs/out_newton_scene/ref --new runs/out_taichi_s3 --sheets --blind runs/out_taichi_s3/parity/blind
```
