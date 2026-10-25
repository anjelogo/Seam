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
| Warp XPBD drape | RunPod RTX 3090 | done: 4 items, XS/M/XL, tee→hoodie layer, 7 control sims |
| Panel texturing + GLB export | RunPod + this mac | done, on the GPU sim objs |
| Morph binding (instant approximation) | RunPod | done on sim objs; redrape comparison done (below) |
| Viewer + screenshots | this mac | re-shot on the draped GLBs (16 + 3 control shots) |

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

## Numbers

- Claude params: ~4 s/item, ~5.2k in / ~200 out tokens, **~$0.017–0.02 per item** (prompt-cache aware).
- Pattern generation: 0.15–2.1 s/item.
- Box mesh generation (res 1.0): 1.6–3.2 s/item on the mac CPU, 4–9 s on the pod.
- Claude cost drivers: image + schema slice; retry rate 0/4.

### GPU run (RunPod RTX 3090, 2026-10-20)

Box: Secure Cloud RTX 3090 24 GB, EU-CZ-1, $0.50/h, CUDA 13.2 host driver, image
`runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` (nvcc 12.4). setup_gpu.sh ~10 min (warp
CUDA compile 107 s + link 11 s, warp-clang from packman LLVM 15.0.7); upstream smoke sim 117 s, ~75 s
of it first-run kernel JIT (cached after). run_poc.sh 526 s. Pod up 54 min incl. controls (~$0.45).
Numbers from runs/out/timings.json and the control dirs runs/out_*.

Main drapes on wearer_masc (175 cm), res 1.0, upstream default sim props:

| item | preset | sim s | frames | body / self isect | VRAM MB | upstream fails | reads as |
|---|---|---|---|---|---|---|---|
| sweats | default | 36.0 | 2399 (cap) | 0 / 8063 | 644 | static_eq, self | slid off the body (y −22…14 cm) |
| tee | soft | 35.2 | 2399 | 151 / 493 | 564 | static_eq, body, self | slid off the left shoulder |
| hoodie | soft_flexy | 53.9 | 2399 | 378 / 1230 | 666 | static_eq, body, self | the garment: hood, folds, cuffs |
| jeans | stiff | 37.6 | 2399 | 0 / 9079 | 660 | static_eq, self | slid off the body (y −28…16 cm) |

- 35–56 s/garment (paper: ~30 s on a 3090); peak VRAM 0.56–0.68 GB (nvidia-smi, incl. context), so
  24 GB is idle capacity and several sims could share one card.
- No main sim met upstream's static-equilibrium test inside the 2400-frame cap and all trip its
  self-intersection flag. The flags over-report: the hoodie trips all three and reads right.
- The GPU sim is not deterministic: the same tee spec, three runs: body isect 151 / 97 / 92, one
  settled at frame 2063.
- Bottoms: upstream holds the waist (`lower_interface`) attachment for `attachment_frames: 400`, then
  releases it, and both pants slide off our mannequin. Not only sizing (W32 size body waist 81.3 /
  hips 106.8 vs wearer 75.2 / 92.9 cm): the jeans also fall on wearer_heavy (waist 82.2 cm).
  Control with every attachment held for all frames (runs/out_ctrl_hold, shots `*_hold_tq.png`):
  sweats 26.2 s, y 11…105 cm; jeans 26.4 s, y 5…105 cm; both 0 body / 0 self isect, only the
  static_eq flag. They read as baggy cuffed track pants and wide-leg jeans, at least as well as the
  templates. The tee does not recover (36.8 s, 154 / 587, still off the shoulder): different cause, open.
- Layer test (tee draped, merged into the collision body, hoodie draped over it): the base tee settled
  (33.1 s, frame 2063); the hoodie took 88.1 s, 2731 body / 12957 self isect, and ended at y 0.81–1.26 m,
  i.e. it slid down over the tee with the hood off the head. Layering via a merged body does not work as is.
- Fixed in our scripts during the run: run_poc.sh lacked ~/.local/bin on PATH (uv not found in a
  non-login shell) and passed an unknown `--bodies` to drape.bind; drape.py's layer test read
  `<name>_layered_specification.json` (FileNotFoundError).

## Size experiment (D6)

Hoodie patterns at XS / M / XL from size bodies of the 175 cm masc wearer, all draped on
wearer_masc (175 cm). Size-body girths: XS bust 84 / waist 70 / hips 86, M 96 / 82 / 101, XL
112 / 98 / 121 (cm). The cached XS body had been derived from the 183 cm wearer while M/XL came from
the 175 cm one, so it was rebuilt before the run; the sizes now differ only in girth.

| size | sim s | body / self isect | VRAM MB | hem y |
|---|---|---|---|---|
| XS | 49.0 | 616 / 942 | 628 | 0.862 m |
| M | 54.1 | 377 / 773 | 650 | 0.837 m |
| L (listed size, main drape) | 53.9 | 378 / 1230 | 666 | 0.830 m |
| XL | 56.4 | 251 / 1255 | 684 | 0.813 m |

Reads as intended (shots `grailed_108767954_size_*.png`, untextured sim meshes): XS is fitted, with
tight sleeves and the hem at the hip; XL is oversized, with fuller, longer sleeves, more folds and a
lower hem. Body contact falls monotonically with size and self-contact (bunching) peaks at XL. The 2D
hood self-intersection warning on M/L/XL did not break any sim.

## Instant approximation (D8 binding)

Nearest-triangle barycentric + the offset stored as a 3-vector in the triangle's rotating local
frame (the plain normal-only scalar leaves 0.8-1.2 cm mean error on the box meshes, 0.08-0.33 cm
mean / up to 3.0 cm max on the sim meshes; the frame version reconstructs exactly). Garment morph targets = binding applied to each of the mannequin's
8 morph deltas, exported with the exact avatar target names so web useBodyMorphs drives them
unchanged. binding.npz caches the ~12 s proximity pass; re-export is instant.

On the GPU sim objs (default drapes, so both bottoms are bound where they fell, by the feet):

| item | verts | recon @drape sliders | morph-blend identity | push h=0.8 mean/max | penetr. push / bind |
|---|---|---|---|---|---|
| sweats | 14719 | 0.000 cm | 0.004 / 0.036 cm | 0.45 / 0.83 cm | 0 / 0 (garment on the floor) |
| tee    |  9848 | 0.000 cm | 0.31 / 0.76 cm | 5.64 / 7.13 cm | 104 / 104 (1.06%) |
| hoodie | 16309 | 0.000 cm | 0.20 / 0.69 cm | 6.61 / 9.45 cm | 110 / 110 (0.67%) |
| jeans  | 15515 | 0.000 cm | 0.004 / 0.081 cm | 0.43 / 0.94 cm | 0 / 0 (garment on the floor) |

The binding itself stays exact and adds zero penetrations (counts identical at bind and after the
push); the morph-blend identity residual is 0.20–0.31 cm mean on the tops. All 4 bound GLBs verify:
8 targets, targetNames == slider names, UVs + textures, load in trimesh.

**Binding vs redrape** (hoodie, height slider 0.8 = 184.45 cm): the re-drape on that body took 29.4 s
and settled at frame 693. Binding-pushed vs re-drape: **mean 6.12 cm, max 13.16 cm**. Sim noise floor
(re-drape on the same body vs the original drape): 1.35 / 5.16 cm. The binding error is ~4.5x the
noise: binding stretches the garment with the body, as if it were re-cut for each wearer, while the
same physical garment rides up on a taller one. Fine for small girth tweaks; height buckets need
their own drape.

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
6. The warp fork tracks `tools/packman/packman` as mode 100644 and `build_llvm.py` execs it, so the
   Linux build dies with "Permission denied" after the CUDA compile — setup_gpu.sh chmods it first.
7. Upstream's `test_garment_sim.py` crashes after the sim in its headless pyrender pass (PyOpenGL
   ctypes ArgumentError in glGenTextures); the sim itself succeeds and setup_gpu.sh tolerates it.

## Viewer

`cd <repo root> && python3 -m http.server 8808` then open
http://localhost:8808/gen3d/drape/viewer/index.html
(left: current template pipeline; right: drape — toggles for bound-morph mode and hoodie XS/M/XL;
morph sliders drive avatar + bound garment by name). Regenerate the manifest after new artifacts:
`cd gen3d/drape && uv run --no-sync python viewer/build_manifest.py`.

Screenshots (committed): runs/out/shots/ — <safe>_{front,tq,back}.png per item (full-page = left
template vs right drape), plus grailed_108767954_size_{XS,M,XL}.png and depop_958293311_bound_h08.png,
all re-shot on the GPU-draped GLBs (camera azimuth 0 / 30 / 180°). `<safe>_hold_tq.png` (sweats,
jeans, tee) are the held-attachment controls, shot by pointing the page's in-memory manifest `draped`
URL at runs/out_ctrl_hold. The size GLBs are untextured trimesh exports of the sim_size objs.
Browser console clean (only a favicon 404).

## Cost projection — 200 items × 5 body buckets

- Claude params: 200 × $0.02 = **$4** (one-time per item, body-independent).
- Patterns: CPU, free-ish (≤2 s each).
- Drapes: 200 items × 5 bodies = 1000 sims × ~45 s measured (RTX 3090) ≈ 12.5 GPU-h ≈ **~$6** at
  the $0.50/h Secure 3090 rate paid here, plus per-size variants if offered (+3× for XS/M/XL ladder).
  Each sim peaks under 0.7 GB VRAM, so packing several per GPU should cut that (not measured).
- New body AFTER baking: $0 — the binding reshapes instantly in the browser, but it is ~6 cm off a
  real re-drape for a +5% height change (above): fine for girth, not a substitute for height buckets.
- Storage: ~2–5 MB/GLB → 1000 × ~3 MB ≈ 3 GB.

## Re-running the GPU stage

Done once on 2026-10-20 (above); gen3d/drape/GPU_RUN.md has the exact pod + rsync commands.

1. rsync (or clone + checkout anjelo/drape-poc) the repo to a RunPod Ubuntu 22.04 + CUDA 12 box,
   plus `rsync -a gen3d/drape/runs/inputs/ box:.../gen3d/drape/runs/inputs/` and runs/bodies/.
2. `cd gen3d/drape && bash drape/scripts/setup_gpu.sh` (installs git-lfs BEFORE cloning vendors,
   builds the warp fork with CUDA_PATH, runs upstream's own smoke sim once, prints seconds).
3. `bash drape/scripts/run_poc.sh` — drapes all 4 items + XS/M/XL size experiment + tee→hoodie
   layer test, re-runs texture/export/bind on the real sim objs, writes runs/out/timings.json.
4. rsync runs/out back; export the hoodie size GLBs (`<safe>_size_{XS,M,XL}.glb`: plain trimesh
   exports of sim_size_*/*_sim.obj, cm -> m); `uv run --no-sync python viewer/build_manifest.py`;
   re-take shots.
5. Binding-vs-redrape: `uv run --no-sync python -m drape.body --base masc --name wearer_masc_h08
   --sliders height=0.8`, drape the hoodie on it (`-m drape.drape --only grailed_108767954 --wearer
   wearer_masc_h08 --size L --out runs/out_redrape08`), then `-m drape.bind --only
   grailed_108767954 --push height=0.8 --compare <that _sim.obj>`.

## Verdict

**PROCEED, with two fixes before it is product-grade.** The GPU run answered the open question:
when the garment stays on the body, the drape reads like the real garment, better than the
templates, and the size ladder reads right.
- Works: the hoodie (hood, folds, ribbed cuffs, hem at the hip) and both bottoms once the waist
  attachment is held for the whole sim (baggy cuffed track pants, wide-leg jeans); XS → XL reads
  fitted → oversized; 35–56 s and < 0.7 GB VRAM per sim.
- Mechanics from the Mac stage hold: listing photo → valid GarmentCode params (4/4, $0.02, 4 s) →
  pattern on a size body (≤2 s) → our mannequin as a GarmentCode body → panel-true texturing →
  GLBs the existing web morph system drives unchanged.
- Cost at 200 items × 5 bodies ≈ **$4 Claude + ~$6 GPU + ~3 GB storage** — negligible.
- Against the abandon criteria: with upstream defaults 3/4 items read worse than the templates
  (both bottoms slide off, the tee slides off a shoulder); held attachments bring that to 1/4 (the
  tee). Every sim trips upstream's own fail flags, but they over-report (the hoodie trips all three).

Must fix before scaling:
1. Hold the waist attachment for the whole sim on bottoms. It is one sim-props value
   (`attachment_frames`); drape.py does not set it yet, the control used 100000.
2. Find why the tee slides off a shoulder (it still does with held collar attachments); the
   neckline vs our mannequin's narrower shoulders and 20° arm pose are the first suspects.

Two hopes that did not hold: layering via a merged collision body collapses the hoodie, and the
binding is ~6 cm off a real re-drape for a +5% height change, so height buckets each need a sim
(still cheap at ~45 s).

Three biggest risks:
1. **License**: the required warp fork is NVIDIA Source Code License, NON-COMMERCIAL only. Fine
   for the PoC; a production blocker until relicensed/replaced (upstream warp is now permissive —
   porting GarmentCodeData's sim patches is real work).
2. **Tops sliding off the shoulders**: 1 of the 2 tops (the tee) slides off with default and with
   held attachments, cause unknown. (The earlier hood risk did not materialize: the M/L/XL hood 2D
   self-intersection warning broke no sim.)
3. **Photo→param ambiguity**: one front photo under-determines rise/length/flare; Claude guesses
   plausibly but a fit-critical product needs priors per category (or measurements from the
   listing) — plus our mannequin's 20° arm pose (vs their 45° A-pose) risks sleeve-torso
   collisions at sim init.
