# Drape PoC results

Question: does GarmentCode (sewing patterns) + NVIDIA Warp XPBD cloth sim make thrift listings
look like the real garment (folds, drape, cuffs, bagginess, size) on our mannequin, at acceptable cost?

## Simulator path

GarmentCode's native warp pipeline (pygarment.meshgen: BoxMesh -> run_sim), per upstream
`test_garment_sim.py`. ChatGarment's `run_garmentcode_sim.py` was REJECTED as fallback: it actually
swaps in a different simulator (ContourCraft-CG fork), hardcodes the author's cluster paths, and
pins the body to `mean_all` — all cost, no benefit over going direct.

Licenses: GarmentCode + pygarment MIT. assets/bodies/*smpl* files CC BY 4.0 (not used; our own
mannequin bodies instead). **NvidiaWarp-GarmentCode fork is NVIDIA Source Code License,
NON-COMMERCIAL ONLY** — fine for this PoC, a hard blocker for shipping unless relicensed/replaced.

## What ran where

| Stage | Where | Status |
|---|---|---|
| Item export (prod DB over ssh tunnel) | this mac | done, 4 real items |
| Claude photo->design params (claude-sonnet-5-5) | this mac | done, 4/4 valid |
| Mannequin -> GarmentCode body (obj + 26-key yaml + segmentation) | this mac | done, masc/fem/183cm + size bodies |
| Pattern generation (pygarment) | this mac | done, 4 items + XS/M/XL hoodie |
| Box mesh (pre-sim garment mesh, panel UVs + labels) | this mac | done, 7 meshes |
| Warp XPBD drape | **GPU box (pending human run)** | scripts ready; local CPU sim segfaults (below) |
| Panel texturing + GLB export | this mac | done, on box meshes; same code reruns on sim objs |
| Morph binding (instant approximation) | this mac | done, on box meshes; redrape comparison pending GPU |
| Viewer + screenshots | this mac | done |

Local CPU sim attempt: built the warp fork CPU-only on macOS arm64 (llvm.org clang+llvm 15.0.7 in
place of NVIDIA's packman bundle). `wp.init()` + kernels work, but the first `warp.sim.collide`
kernel launch segfaults — timeboxed and dropped. The sim is GPU-box work, as planned.

## The 4 items (prod, rule-picked: usable_for_3d + clean_image + role regexes)

| item | role | size | fit | pattern | panels |
|---|---|---|---|---|---|
| depop:941190262 — "y2k southpole baggy sweat pants" | sweats | W32 | oversized | ok | 8 |
| grailed:108767954 — Carhartt-style hoodie | hoodie | L | oversized | ok (2D self-intersect: hood) | 14 |
| grailed:108843068 — "REHACER baggy rusty mudwash" jeans | jeans | W32 | oversized | ok | 6 |
| depop:958293311 — boxy tee | tee | L | oversized | ok | 8 |

## Numbers (this mac, M-series CPU; sim numbers TBD on GPU)

- Claude params: ~4 s/item, ~5.2k in / ~200 out tokens, **~$0.017–0.02 per item** (prompt-cache aware).
- Pattern generation: 0.15–2.1 s/item.
- Box mesh generation (res 1.0): 1.6–3.2 s/item on CPU.
- Upstream sim reference: ~30 s/garment on an RTX 3090 (GarmentCodeData paper); VRAM unpublished —
  `drape.drape` samples nvidia-smi peak per run into `runs/out/timings.json`.
- Claude cost drivers: image + schema slice; retry rate 0/4.

### TBD after `drape/scripts/run_poc.sh` on the GPU box
- per-item sim seconds + peak VRAM + GPU model (auto-recorded to runs/out/timings.json)
- size experiment XS/M/XL drape deltas on the 183 cm wearer
- layered tee->hoodie drape
- binding-vs-redrape error at height 0.8 (bind.py --compare)

## Size experiment (D6)

Patterns + box meshes for the hoodie at XS / M / XL on the same 183 cm masc wearer exist locally
(`runs/out/grailed_108767954/sim_size_*`). Size-body girths: M bust 96 / waist 82 / hips 101 vs
XL 112 / 98 / 121 (cm). Pattern-level: XS lays out clean; M/L/XL trigger GarmentCode's 2D
self-intersection warning (hood panels outgrow the flat layout) — flagged, sim-level effect TBD.
Expected on GPU: XS rides up and pulls; XL bunches. RECORD ACTUAL RESULT HERE AFTER GPU RUN.

## Instant approximation (D8 binding)

Nearest-triangle barycentric + the offset stored as a 3-vector in the triangle's rotating local
frame (the plain normal-only scalar leaves 0.8-1.2 cm mean error on these meshes; the frame
version reconstructs exactly). Garment morph targets = binding applied to each of the mannequin's
8 morph deltas, exported with the exact avatar target names so web useBodyMorphs drives them
unchanged. binding.npz caches the ~12 s proximity pass; re-export is instant.

| item | verts | recon @drape sliders | morph-blend identity | push h=0.8 mean/max | penetr. push / bind |
|---|---|---|---|---|---|
| sweats | 14710 | 0.000 cm | 0.29 / 1.26 cm | 3.29 / 5.98 cm | 64 / 64 (0.44%) |
| tee    |  9865 | 0.000 cm | 0.40 / 1.55 cm | 5.98 / 7.54 cm | 160 / 160 (1.62%) |
| hoodie | 16331 | 0.000 cm | 0.27 / 1.53 cm | 6.36 / 9.45 cm | 233 / 233 (1.43%) |
| jeans  | 15524 | 0.000 cm | 0.26 / 1.09 cm | 2.84 / 5.86 cm | 80 / 80 (0.52%) |

The honest approximation error is the morph-blend identity residual (0.26-0.40 cm mean, <=1.55 cm
max): the body is slightly non-linear in its sliders, the binding itself is exact. Penetration
counts are IDENTICAL at bind and after pushing height to 0.8 on every item - binding introduces
zero new body penetration; the 0.4-1.6% that exist come from the un-draped boxmesh fixtures.
All 4 bound GLBs verify: 8 targets, targetNames == slider names, textures injected, load in
trimesh. bind.py --compare is wired for the GPU re-drape comparison (self-compare = 0.000 cm).

## Texturing (D7)

The UV atlas interlocks and rotates islands, so the naive "cutout bbox onto front-island union
bbox" smears; instead each texel's 3D position is front-projected into the garment crop (back =
mirrored + blurred + 70% dominant colour, same idea as bake.py mock_texture; sleeves/hood/cuffs =
region-dominant colour). Panel scale from true panel areas (uniform ~5-7 px/cm). Procedural
normal+roughness tiled at real cm scale: jersey/fleece knit, rib knit forced on cuff/waistband
panels, denim twill, canvas, leather.

All 4 items: 3x 1024 sq maps + preview, 0 unlabeled faces, deterministic (re-run byte-identical).
GLBs verify in trimesh: UVs + basecolor + normal + metallicRoughness, doubleSided, meters Y-up
(e.g. tee bbox y 0.81-1.42 m, hoodie y-max 1.94 m = pre-sim hood floating, drops after real sim).

## Upstream bugs hit (for whoever runs this next)

1. PyPI `pygarment` 2.0.2 wheel is mispackaged (no top-level `pygarment`) — install editable from
   the repo clone (pyproject already does).
2. `Edge` warning path crashes (`Edge.name` missing) when resolution_scale > 1 produces 2-vertex
   edges — patched at runtime in drape.py.
3. Frame-timeout no-ops on macOS (`platform.system()` returns "Darwin", upstream checks "OSX") —
   drape.py nulls `max_frame_time` on mac.
4. The warp fork clone silently loses its `warp/` tree without git-lfs installed FIRST.
5. `run_sim` calls pyrender unconditionally — drape.py no-ops `render_images` (we screenshot via
   the viewer instead); setup_gpu.sh still installs GL libs for safety.

## Viewer

`cd <repo root> && python3 -m http.server 8808` then open
http://localhost:8808/gen3d/drape/viewer/index.html
(left: current template pipeline; right: drape — toggles for bound-morph mode and hoodie XS/M/XL;
morph sliders drive avatar + bound garment by name). Regenerate the manifest after new artifacts:
`cd gen3d/drape && uv run --no-sync python viewer/build_manifest.py`.

Screenshots (committed): runs/out/shots/ — <safe>_{front,tq,back}.png per item (full-page = left
template vs right drape), plus grailed_108767954_size_{XS,M,XL}.png and depop_958293311_bound_h08.png.
Browser console clean (only a favicon 404). NOTE: right-pane geometry is currently the PRE-SIM box
mesh (boxy, hood spiking up) — re-run the same shots after the GPU drape to judge visual quality;
the left-vs-right texture/colour comparison is already meaningful.

## Cost projection — 200 items × 5 body buckets

- Claude params: 200 × $0.02 = **$4** (one-time per item, body-independent).
- Patterns: CPU, free-ish (≤2 s each).
- Drapes: 200 items × 5 bodies = 1000 sims × ~30 s (3090-class) ≈ 8.3 GPU-h ≈ **$3–7** on RunPod
  (RTX 3090/4090 at $0.3–0.8/h), plus per-size variants if offered (+3× for XS/M/XL ladder).
- New body AFTER baking: $0 — the binding reshapes instantly in the browser; re-drape only for
  quality-critical fits.
- Storage: ~2–5 MB/GLB → 1000 × ~3 MB ≈ 3 GB.

## What the human must run on the GPU box

1. rsync (or clone + checkout anjelo/drape-poc) the repo to a RunPod Ubuntu 22.04 + CUDA 12 box,
   plus `rsync -a gen3d/drape/runs/inputs/ box:.../gen3d/drape/runs/inputs/` and runs/bodies/.
2. `cd gen3d/drape && bash drape/scripts/setup_gpu.sh` (installs git-lfs BEFORE cloning vendors,
   builds the warp fork with CUDA_PATH, runs upstream's own smoke sim once, prints seconds).
3. `bash drape/scripts/run_poc.sh` — drapes all 4 items + XS/M/XL size experiment + tee→hoodie
   layer test, re-runs texture/export/bind on the real sim objs, writes runs/out/timings.json.
4. rsync runs/out back; `uv run --no-sync python viewer/build_manifest.py`; re-take shots;
   fill the TBD sections above + this verdict's quality judgement.
5. Binding-vs-redrape error: `uv run --no-sync python -m drape.bind --only grailed_108767954
   --push height=0.8 --compare <path to the re-draped-at-0.8 _sim.obj>`.

## Verdict

**PROCEED — pending the one thing a Mac cannot answer: visual drape quality on the GPU run.**
Every other question came back positive and cheap:
- Mechanics: listing photo → valid GarmentCode params (4/4, $0.02, 4 s) → pattern on a size body
  (≤2 s) → our mannequin is a drop-in GarmentCode body (upstream BodyParameters loads it, waist
  level exact) → panel-true texturing → GLBs the existing web morph system drives unchanged.
- The "instant approximation" works: exact reconstruction, 0.26–0.40 cm morph residual, zero
  added penetrations — so 5 body buckets do NOT need 5 sims per item.
- Cost at 200 items × 5 bodies ≈ **$4 Claude + $3–7 GPU + ~3 GB storage** — negligible.
Abandon only if the GPU run shows draped results reading worse than the current templates, or a
high sim fail-rate on real thrift params.

Three biggest risks:
1. **License**: the required warp fork is NVIDIA Source Code License, NON-COMMERCIAL only. Fine
   for the PoC; a production blocker until relicensed/replaced (upstream warp is now permissive —
   porting GarmentCodeData's sim patches is real work).
2. **Hoodies at M+**: GarmentCode's Hood2Panels self-intersects in the 2D layout even with stock
   defaults (XS lays out clean) — may degrade or fail sims on exactly the category where drape
   matters most; needs hood-param tuning or an upstream fix.
3. **Photo→param ambiguity**: one front photo under-determines rise/length/flare; Claude guesses
   plausibly but a fit-critical product needs priors per category (or measurements from the
   listing) — plus our mannequin's 20° arm pose (vs their 45° A-pose) risks sleeve-torso
   collisions at sim init.
