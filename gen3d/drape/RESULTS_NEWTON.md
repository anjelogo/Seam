# Newton is the default drape engine: results

The drape sim now runs on Newton 1.7.0 over PyPI warp-lang 1.18.0, both Apache-2.0. The
NVIDIA-licensed warp fork is no longer installed by default; it sits behind
`drape/scripts/setup_fork.sh` for research comparisons only. Branch `anjelo/newton`; engine code as
of `905c083`. How the port stayed clean-room is in [CLEANROOM.md](CLEANROOM.md); the behaviour it
was written from is [SIM_SPEC.md](SIM_SPEC.md).

## Verdict per target

All targets were fixed before any Newton sim ran and were not changed afterwards. `drape/gates.json`
is byte-identical (sha256 `aa04a7a5…249cf0`).

| target | rule | result |
| --- | --- | --- |
| gates | fork-pass rows pass on Newton; fork-fail rows fail the same gates or fewer | 10 of 11 tops pass. **Miss:** `texture/grailed_109137061` adds `penetration` (0.103 % vs the 0.1 % limit) |
| shape | symmetric mean surface distance ≤ 2 × the fork's re-drape noise floor (0.1528 cm) = 0.3056 cm | 18 of 19 pass. **Miss:** `sweep_M/depop_954868283` at 0.3251 cm |
| bottoms | waist held for the whole sim; waistband top within 2 cm of the fork's | 8 of 8 held; every waistband within 0.1 cm |
| blind review | no item judged worse on Newton for slide, fit or penetration | 19 of 19 judged **equivalent** |
| cost | sim time ≤ 2 × the fork's per item; VRAM ≤ 4 GB | Newton 0.62–0.81 × the fork's sim time; VRAM 525–621 MB |
| license | default env has no NVIDIA Source Code License or non-commercial package; warp and newton resolve to PyPI wheels | 93 distributions, 0 flagged; `site-packages/warp` 1.18.0, newton 1.7.0 |

17 of the 19 parity rows pass every target. The two misses are below, under
[What still fails](#what-still-fails).

## Parity table (final run)

Reference: the fork's drapes in `runs/out_fork_ref` (19 rows: the 12-item texture set, the PoC four,
the black tee at XS/M/XL), on the same A40 pod type, same patterns (seeded from the fork run), same
box meshes (the Linux mesher reproduces the fork's byte for byte). Newton: `runs/out_newton2`.
Report: `runs/out_newton2/parity/parity.md`.

| row | kind | shape cm | gates failed: fork → newton | waistband cm fork / newton | sim s fork / newton | VRAM MB fork / newton | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| texture/depop_936695379 | bottom | 0.032 | – | 104.5 / 104.5, held | 28.7 / 23.2 | 637 / 589 | pass |
| texture/depop_945724547 | bottom | 0.118 | – | 104.1 / 104.1, held | 26.5 / 19.0 | 617 / 557 | pass |
| texture/grailed_109046872 | bottom | 0.157 | – | 102.6 / 102.5, held | 31.1 / 19.4 | 575 / 525 | pass |
| texture/depop_958674696 | bottom | 0.106 | – | 103.1 / 103.0, held | 31.9 / 20.1 | 575 / 525 | pass |
| texture/depop_958854988 | bottom | 0.007 | – | 104.4 / 104.4, held | 29.0 / 20.3 | 663 / 589 | pass |
| texture/depop_958141161 | top | 0.161 | neck_drop, neck_ring → same | – | 27.1 / 20.2 | 579 / 525 | pass |
| texture/depop_959308776 | top | 0.158 | neck_drop, neck_ring → same | – | 37.9 / 29.9 | 623 / 557 | pass |
| texture/grailed_109137061 | top | 0.189 | none → **penetration** | – | 35.7 / 27.1 | 611 / 557 | **fail** |
| texture/depop_953525988 | top | 0.302 | armhole, neck_ring, sleeve_hem → same | – | 35.0 / 25.3 | 627 / 557 | pass |
| texture/depop_957013558 | bottom | 0.046 | – | 104.5 / 104.5, held | 26.6 / 19.6 | 647 / 589 | pass |
| texture/depop_959195954 | top | 0.251 | armhole → same | – | 39.6 / 31.4 | 627 / 557 | pass |
| texture/depop_954868283 | top | 0.256 | neck_drop, neck_ring → same | – | 27.5 / 19.9 | 579 / 525 | pass |
| poc/depop_941190262 | bottom | 0.186 | – | 104.3 / 104.3, held | 27.7 / 20.4 | 651 / 589 | pass |
| poc/grailed_108767954 | top | 0.209 | none → none | – | 51.1 / 37.5 | 685 / 621 | pass |
| poc/grailed_108843068 | bottom | 0.068 | – | 104.3 / 104.3, held | 29.2 / 20.6 | 667 / 621 | pass |
| poc/depop_958293311 | top | 0.295 | neck_drop, neck_ring → same | – | 31.4 / 24.5 | 601 / 557 | pass |
| sweep_XS/depop_954868283 | top | 0.153 | armhole, neck_drop, neck_ring → neck_drop, neck_ring | – | 24.4 / 18.1 | 561 / 525 | pass |
| sweep_M/depop_954868283 | top | **0.325** | neck_drop, neck_ring → same | – | 27.7 / 19.6 | 579 / 525 | **fail** |
| sweep_XL/depop_954868283 | top | 0.266 | armhole, neck_ring, sleeve_hem → same | – | 33.1 / 26.2 | 611 / 557 | pass |

Shape is the mean of both one-way mean distances over 20 000 area-uniform samples (seed 20261023);
p95 and max per row are in the report. VRAM is the whole-GPU `nvidia-smi` peak, CUDA context
included, measured the same way on both engines. Every sim on both engines ran the full 2399-frame
budget and carries `static_equilibrium`, as on master.

## How parity moved

| run | engine code | rows passing | what changed |
| --- | --- | --- | --- |
| run 1 | `5dd33af` (Wave 2 + §10 conformance) | 16 / 19 | – |
| loop 1 | `b00905e` | – | self-contact buffers: one flat buffer per pass with a global counter (SIM_SPEC §6.27, §10.12) instead of a private 192-slot block per spring. Run 1 overflowed on every item (about 1 000–1 900 springs dropped per frame for the first 40–90 frames, and to the last frame on four items), because long sewing springs over open seams query wide boxes. Zero overflow since |
| loop 2 | `905c083` | – | the piercing survey's ray–triangle test is now warp's watertight test (Woop et al. 2013), as the reference uses. Stitched panel edges line up exactly in the flat layout, and the old Möller–Trumbore test missed crossings exactly on a triangle edge, so those particles were not exempted from self-contact. Frame-0 gap against the fork on the identical mesh: 0.313 → 0.054 cm (`depop_953525988`), 0.058 → 0.006 cm (`depop_954868283`) |
| run 2 | `905c083` | 17 / 19 | final |

The rows that changed between run 1 and run 2:

| row | run 1 | run 2 |
| --- | --- | --- |
| texture/depop_959308776 | fail: penetration 0.114 % | pass: 0.061 % |
| texture/depop_953525988 | fail: shape 0.362 cm, extra neck_drop (7.40 vs floor 7.42) | pass: shape 0.302 cm, neck_drop 7.59 |
| poc/grailed_108767954 | fail: armhole 5.53 cm (limit 5.0, fork 4.91) | pass: armhole 4.74 |
| texture/grailed_109137061 | pass: penetration 0.064 % | fail: penetration 0.103 % |
| sweep_M/depop_954868283 | pass: shape 0.275 cm | fail: shape 0.325 cm |

Fix loop 3 was not used. After loop 2 every self-contact rule that three further reader passes
could state (SIM_SPEC §10.14) matches the code. The shape miss sits inside the fork's own
run-to-run spread, and the penetration miss traces to a frame-0 residual that no stated rule
explains (below). A third loop would have been tuning against rounding, not porting a rule.

## Blind review, verbatim

A fresh reviewer saw the 38 unlabelled sheets (A/B order random per item, seed 20261023) and nothing
else. Its reply, unedited:

| item | verdict | slide | fit | penetration | notes |
|---|---|---|---|---|---|
| 1 | equivalent | none, both on shoulders | same hem at hip, same sleeve line, same open center-front slit | none; grey at neck/front slit only, identical in both | ragged sleeve-hem edges in both; A's placket gap marginally wider |
| 2 | equivalent | both held at waist, same waistband height | identical leg width, same cuff fold | none | B's wearer-left cuff slightly flatter — fold noise only |
| 3 | equivalent | none | same shoulder seat, sleeve length, hem | none | B has marginally more gathering down the front placket |
| 4 | equivalent | none | wide-leg hang and hem length match tile-for-tile | none | near-identical frames |
| 5 | equivalent | none | same taper, same gathered-ankle bunching | none | ankle gathers crumple the same way in both; B's right ankle bunches slightly more |
| 6 | equivalent | none | balloon volume, cuff height, crotch drape all match | none | — |
| 7 | equivalent | none | same boxy silhouette, hem, sleeve drop | none | heavy sawtooth noise at sleeve caps/hems in both; A loaded on one sleeve, B on both |
| 8 | equivalent | none | same harem volume and cuff knot | none | both produce the same small knotted cuff at the hem |
| 9 | equivalent | none | same flared hem, same open front | none; center-back channel is shading, no grey through | both show the identical vertical center-back crease |
| 10 | equivalent | hood stays up on head in both | same body length, sleeve length, hood seat | none | thin cloth sliver at the hood opening in both (a little more visible in B's 3/4 tile); no spikes |
| 11 | equivalent | none | silhouette, hem and neckline match | none | A carries heavier ruffle noise at the sleeve caps, B smoother — wrinkle noise, not structure |
| 12 | equivalent | none | same drape and hem | none | B's front vertical ridges slightly deeper |
| 13 | equivalent | none | identical wide-leg hang | none | — |
| 14 | equivalent | none | same cropped hem and leg flare | none | — |
| 15 | equivalent | none, both on shoulders | same sleeve length, hem, V depth | none; grey chest is the V opening, same in both | B's placket edge more crumpled with a small knot at the V apex; A's V edge cleaner |
| 16 | equivalent | none | identical | none | — |
| 17 | equivalent | hood up in both | same cropped hem, same sleeve | none | — |
| 18 | equivalent | none | same hem, sleeve and neck | none | ragged sleeve hems in both |
| 19 | equivalent | none | same hem, sleeve and neck | none | ragged sleeve hems in both |

> - All 19 pairs match in silhouette, hem height, sleeve position and waistband height; nothing slid down, off a shoulder, or off the body in either column.
> - No body-through-cloth penetration anywhere. Grey appears only at design openings (front plackets, V-necks, hood faces) and above waistbands on the bottoms-only items — identical on both sides.
> - Every difference I found is fold/wrinkle placement, concentrated at sleeve hems and front plackets, the kind a re-run of one simulator would also move.
> - Shared across both simulators: sawtooth sleeve-hem and armhole edges on the boxy short-sleeve tops (7, 9, 11, 12, 18, 19) and crumpled ankle gathers on tapered trousers (5, 8). Same character in A and B, so not a discriminator — but worth fixing in both.
> - No spikes, tears, exploded regions, separated panels, stretched seams or floating cloth in any of the 38 sheets.

Decoded (`runs/out_newton2/parity/blind_key.json`), with the side each minor note points at:

| item | row | Newton was | note points at |
| --- | --- | --- | --- |
| 1 | texture/depop_954868283 | B | fork (wider placket gap) |
| 2 | texture/depop_957013558 | B | Newton (flatter cuff) |
| 3 | texture/depop_959308776 | A | fork (more placket gathering) |
| 4 | poc/grailed_108843068 | B | – |
| 5 | texture/depop_958674696 | A | fork (ankle bunches more) |
| 6 | poc/depop_941190262 | B | – |
| 7 | sweep_XS/depop_954868283 | A | sleeve noise on one sleeve in Newton, both in the fork |
| 8 | texture/grailed_109046872 | A | – |
| 9 | sweep_XL/depop_954868283 | B | – |
| 10 | poc/grailed_108767954 | B | Newton (hood sliver a little more visible) |
| 11 | texture/depop_953525988 | A | Newton (heavier sleeve-cap ruffle) |
| 12 | poc/depop_958293311 | A | fork (deeper front ridges) |
| 13 | texture/depop_958854988 | B | – |
| 14 | texture/depop_945724547 | B | – |
| 15 | texture/grailed_109137061 | B | Newton (placket more crumpled, small knot at the V apex) |
| 16 | texture/depop_936695379 | A | – |
| 17 | texture/depop_959195954 | A | – |
| 18 | texture/depop_958141161 | B | – |
| 19 | sweep_M/depop_954868283 | B | – |

## Paired contact sheets

Fork on the top row, Newton on the bottom, five views each:
[texture/depop_936695379](runs/out/shots/newton/texture_depop_936695379.jpg) ·
[texture/depop_945724547](runs/out/shots/newton/texture_depop_945724547.jpg) ·
[texture/grailed_109046872](runs/out/shots/newton/texture_grailed_109046872.jpg) ·
[texture/depop_958674696](runs/out/shots/newton/texture_depop_958674696.jpg) ·
[texture/depop_958854988](runs/out/shots/newton/texture_depop_958854988.jpg) ·
[texture/depop_958141161](runs/out/shots/newton/texture_depop_958141161.jpg) ·
[texture/depop_959308776](runs/out/shots/newton/texture_depop_959308776.jpg) ·
[texture/grailed_109137061](runs/out/shots/newton/texture_grailed_109137061.jpg) ·
[texture/depop_953525988](runs/out/shots/newton/texture_depop_953525988.jpg) ·
[texture/depop_957013558](runs/out/shots/newton/texture_depop_957013558.jpg) ·
[texture/depop_959195954](runs/out/shots/newton/texture_depop_959195954.jpg) ·
[texture/depop_954868283](runs/out/shots/newton/texture_depop_954868283.jpg) ·
[poc/depop_941190262](runs/out/shots/newton/poc_depop_941190262.jpg) ·
[poc/grailed_108767954](runs/out/shots/newton/poc_grailed_108767954.jpg) ·
[poc/grailed_108843068](runs/out/shots/newton/poc_grailed_108843068.jpg) ·
[poc/depop_958293311](runs/out/shots/newton/poc_depop_958293311.jpg) ·
[sweep_XS](runs/out/shots/newton/sweep_XS_depop_954868283.jpg) ·
[sweep_M](runs/out/shots/newton/sweep_M_depop_954868283.jpg) ·
[sweep_XL](runs/out/shots/newton/sweep_XL_depop_954868283.jpg)

## Versions

| piece | version | source |
| --- | --- | --- |
| newton | 1.7.0 | PyPI wheel, Apache-2.0 (`newton-physics` is only a rename stub) |
| warp-lang | 1.18.0 | PyPI wheel, Apache-2.0, pulled in by newton |
| numpy | 1.26.4 | PyPI |
| Python | 3.12 | uv-managed venv |
| pygarment | 2.0.2 | `vendor/GarmentCode`, MIT; `setup_gpu.sh` clones its current HEAD (`d449629` here) |
| GPU | A40 48 GB, driver 595.91.07, host CUDA 13.2 | RunPod Secure EU-SE-1, image `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` |

`warp.sim` is not used (removed upstream in warp 1.10). Nothing is built from source.

## Solver choice

Our own XPBD substep loop (`drape/sim_newton/solver.py`) on Newton's `ModelBuilder`, `Model` and
`State`, calling Newton's own XPBD kernels for springs, bending and the delta application. Not
`SolverXPBD`, not `SolverVBD`.

The reference integrator is one XPBD iteration per substep, ten substeps per 60 fps frame, every
constraint adding into one shared delta buffer that a single capped application then writes back.
Its in-plane cloth response comes from springs alone: the triangle stiffness it is given is never
solved (SIM_SPEC §3.3, §4.8). Newton's `SolverXPBD` runs its own iteration and contact structure, and
`SolverVBD` (S2's pick in NEWTON_MAP.md) solves triangle membranes, which would switch on that
inert stiffness and change every drape. Re-creating the reference's loop on Newton's data model was
the only way to aim at 3 mm parity.

Units stay cm, y-up, gravity (0, −9.81, 0) from frame 10, dt 1/600 s. One CUDA graph per frame,
re-captured when gravity turns on, on body-smoothing frames and on attachment release.

## Built-ins vs ours

| piece | from | file |
| --- | --- | --- |
| model, state, particles, springs, bending edges, body mesh shape | Newton `ModelBuilder` / `Model` / `State` | `sim_newton/builder.py` |
| spring and bending constraints, capped delta application | Newton XPBD kernels (`solve_springs`, `bending_constraint`, `apply_particle_deltas`), imported | `sim_newton/solver.py` |
| BVH, closest-point, AABB and ray queries, atomics, CUDA graphs | warp builtins | all |
| frame loop, gravity window, graph re-capture, caps, fail tags, stats | ours, from SIM_SPEC §2 | `gc_sim/simulation.py` |
| scene build from pygarment's box mesh, masses, sewing springs, panel labels | ours (garment loader adapted from pygarment, MIT) | `gc_sim/garment.py`, `sim_newton/builder.py` |
| substep loop | ours, SIM_SPEC §4.1 | `sim_newton/solver.py` |
| integration with the reference's damping triple and velocity cap | ours, §4.2 / §10.9 | `sim_newton/integrate.py` |
| body contact registration and response | ours; response adapted from Newton's `solve_particle_shape_contacts` (Apache-2.0) with the §10.5 accumulation | `sim_newton/body.py` |
| point–triangle and edge–edge self-contact, piercing survey, intersection counters | ours, §4.5, §4.7, §5, §10.1–§10.3; ray–triangle test adapted from warp's watertight `intersect_ray_tri_woop` (Apache-2.0) | `sim_newton/self_contact.py` |
| attachments (equality and half-space) | ours, §3.6 / §10.8 | `sim_newton/attach.py` |
| body-part drag and panel assignment | ours, §3.4 / §4.6 / §10.6 | `sim_newton/panel_drag.py` |
| body smoothing | ours, §3.7 / §6.1 (scipy sparse solve) | `sim_newton/smoothing.py` |
| Seam's patches (neck hold, neck stiffness, dumps, stretch-on and arc neckbands, hold-the-waist, A-pose) | unchanged `drape.py` / `pattern.py` code; the fork-only monkeypatches moved to `engine_fork.py` | `drape.py` |

## Behaviour differences from the fork

Every difference known at the end of the run, largest first.

1. **Self-overlapping flat layouts at frame 0.** Some pattern pieces lie in the flat start layout as
   two exactly coplanar, overlapping layers (the collar backs of `grailed_109137061` at z = −10.0000,
   the hood panels of the two hoodies at x = ±8.8815). Each particle there sits inside a
   non-incident triangle of its own layer, so self-contact pushes it along the face normal from
   the first substep. After one frame, Newton's positions for those vertices differ from the
   fork's by up to 0.29 cm (`grailed_109137061`), 0.51 cm (`grailed_108767954`) and 0.19 cm
   (`depop_959195954`); every other vertex agrees within 0.01 cm. Three reader passes found no rule we
   differ on there (SIM_SPEC §10.14): survey marks, sidedness, the predictive band and the
   response all match, and the residual is identical on CPU and GPU. It is the likeliest source of
   the collar knot in blind-review item 15 and of that row's penetration miss.
2. **Overflow path.** On a self-contact buffer overflow the fork processes stale or empty pairs; ours
   marks the reserved slots filtered and drops the element. Moot in practice: the final run logged
   zero overflows.
3. **Stitch-geometry failure tag.** A stitch triangle that violates the triangle inequality is
   tagged `gt_edges_creation` by Newton; the fork tags it `crashes` (SIM_SPEC §2.5). No reference
   item triggers it.
4. **A particle exactly on its closest point.** The fork's predictive band test uses a zero
   direction there; ours uses the face normal. Identical at frame 0 (zero velocity); can differ
   only for an exactly coincident particle in motion.
5. **Survey broad phase.** The fork inflates each hierarchy box by 0.001 cm during traversal; ours
   queries the segment's exact box. The triangle test decides either way; no observed effect.
6. **Cost shape.** Detection now walks each element's box twice (count, then fill), and no longer
   drops contacts. Against run 1 that added 0–3 s on bottoms and 4–14 s on tops. Newton is still
   19–38 % faster than the fork on every row.
7. **Re-run noise.** Both engines accumulate with float atomics, so neither re-drapes bit-exactly.
   On the black tee M, fork vs fork is 0.181 cm (S3's noise pair) and 0.296 cm (the `texture` and
   `sweep_M` reference runs of the same garment and size); Newton vs Newton is 0.283 cm.
8. **Platform.** macOS meshes the black tee with 10 002 vertices where Linux gives the fork's 9 996.
   This predates the port (pygarment's mesher); parity ran on Linux, where the meshes are
   identical.

Seam's patches (neck hold, neck stiffness, dumps, stretch-on and arc neckbands, hold-the-waist,
A-pose) run unchanged on Newton: the reference rows use master's arc neckband and stretch-on,
held attachments and the 45° pose, and the 8 held waists hold.

## License report

The default env from a from-scratch `drape/scripts/setup_gpu.sh` on two fresh pods (identical
tables): 93 distributions, **0** flagged for NVIDIA, non-commercial, research-only or proprietary
terms.

```
python -c "import warp, newton; print(warp.__file__, warp.__version__, newton.__version__)"
/workspace/seam/gen3d/drape/.venv/lib/python3.12/site-packages/warp/__init__.py 1.18.0 1.7.0
```

| package | version | license |
| --- | --- | --- |
| newton | 1.7.0 | Apache-2.0 |
| warp-lang | 1.18.0 | Apache-2.0 |
| pygarment | 2.0.2 (GarmentCode `d449629`) | MIT |
| cgal | 6.0.1 | GPL-3.0-or-later |
| cairosvg | 2.9.1 | LGPL-3.0-or-later |
| psycopg, psycopg-binary, psycopg-pool | 3.3.x | LGPL-3.0-only |
| libigl | 2.6.3 | MPL-2.0 |
| docutils | 0.23 | public domain / BSD / GPL mix |
| pyglet | 2.1.19 | metadata says UNKNOWN (BSD upstream) |
| the other 82 | – | MIT, BSD, Apache-2.0, PSF, MPL-2.0 |

Nothing is non-commercial any more. The copyleft entries (cgal GPL-3.0+; cairosvg and psycopg
LGPL-3.0; libigl MPL-2.0) come from pygarment and the existing app, not from the port, and matter
only if the drape stack is ever distributed.

Outside `setup_fork.sh`, nothing in code, config or install steps references the fork. Its name
appears only in markdown records and in two raw logs from the earlier license spike
(`spike/fork_delta_raw.txt`, `spike/port.log`).

## Full chain on the Newton drapes

Every row went through `drape.texture` → `drape.bind` → `drape.texture --legacy` → `drape.export`
→ `drape.export --legacy` → `viewer/build_manifest.py` on the Mac; the three sweep rows got texture,
bind and export only. Then `drape.eval --passes 3` ran on the texture set and the PoC four (judge
`claude-sonnet-5-5`, judge cost $1.38 + $0.45). Every step exited 0.

| step | result |
| --- | --- |
| texture | 19 rows with the v3 atlas; legacy front projection on the 16 eval items |
| bind | 19 bound GLBs |
| export | 16 v3 and 16 legacy draped GLBs plus the 3 sweep GLBs, every one verified in bounds (`glb_report*.json`) |
| manifest | viewer manifests for both sets |
| eval | 12 + 4 items, 3 judge passes per variant |

Eval, mean rubric score per item (0–2):

| set | legacy | v3 |
| --- | --- | --- |
| texture (12) | 0.96 | 1.44 |
| PoC (4) | 1.10 | 1.02 |

Texture-set criteria, legacy → v3: stripes present 1.14 → 1.52, parallel to grain 1.54 → 2.00,
continuous across seams 0.70 → 1.04, count and spacing 1.12 → 0.79, side stripe 0.60 → 1.22, print
not mirrored 1.04 → 1.11, wrinkles not doubled 0.75 → 1.72. For reference, the last committed eval
([RESULTS_TEXTURE_V3.md](RESULTS_TEXTURE_V3.md): fork engine, older bodies and patterns) scored the
texture set 1.01 → 1.50 and the PoC four 1.28 → 1.07. Every Newton v3 item score is within 0.33 of
its v3 score there, inside the judge's own pass-to-pass spread (up to 1.0 on this run). Reports:
`runs/out_newton2/{texture,poc}/eval.json` and `eval.csv`.

**Viewer.** With the repo root served (`python3 -m http.server 8808`),
`/gen3d/drape/viewer/index.html?out=runs/out_newton2/texture` opened in Chromium through
Playwright: the track pants (draped), the black tee (bound, web pose) and the flannel (draped)
load and render with their v2 textures. The console holds one entry, a 404 for `favicon.ico`.
`drape.eval` renders all 16 items through the same viewer headlessly, without a failure. One
observation, not judged against the fork: the bound black tee shows small white patches at both
sleeve caps.

## Spend

RunPod billing reads, per pod:

| pod | life | ran | billed |
| --- | --- | --- | --- |
| `k70xgnp4cy17bm`, A40 Secure, EU-SE-1, $0.59/h | 2026-10-24 04:11Z to about 19:55Z | setup, fork baselines and noise re-drapes, Wave 2 checks, parity run 1, a fresh-install check; idle through long agent stretches; removed by RunPod when the account balance ran out | $9.39 (GPU 9.22, disk 0.17) |
| `pa64uuiprrhvq4`, same type | 20:09Z to 21:02Z, then stopped | a second fresh install, the loop 1 GPU check, parity run 2 | $0.53 (GPU 0.52, disk 0.01) |
| **total** | | | **$9.92** of the $25 budget |

`pa64uuiprrhvq4` is stopped with no volume, so it bills nothing; terminate it from the console when
it is no longer wanted.

## What still fails

- **`texture/grailed_109137061`, gates:** penetration 0.103 % against the 0.1 % limit (the fork
  measured 0.095 % here and 0.072 % on its own re-drape). Newton's frame-0 collar layers start as
  the coplanar overlap in difference 1, and the blind reviewer saw a small knot at the V apex on
  that side. Not fixed.
- **`sweep_M/depop_954868283`, shape:** 0.3251 cm against 0.3056 cm. The same garment at the same
  size is also the `texture/depop_954868283` row, which passes at 0.256 cm; the two fork runs of
  it differ from each other by 0.296 cm, the two Newton runs by 0.283 cm. Frame 0 matches the fork
  within 0.009 cm, so this is run-to-run divergence, not a rule difference. The target holds and
  this row misses it.
- **Shared with the fork, not caused by the port:** the oversized tees still miss armhole and
  sleeve_hem, the collarless tees still miss neck_ring and neck_drop (same failed sets as the fork),
  and every sim still runs its full frame budget.

## Re-running

```
# GPU box (RunPod A40, Secure): default install, newton + PyPI warp, no source build
cd gen3d/drape && bash drape/scripts/setup_gpu.sh
uv run --no-sync python -m drape.drape --inputs runs/inputs_texture --out runs/out_newton --only <item> --dump-every 50
# research-only comparison against the fork (builds .venv-fork; NVIDIA Source Code License)
bash drape/scripts/setup_fork.sh
UV_PROJECT_ENVIRONMENT=.venv-fork uv run --no-sync python -m drape.drape --engine fork --inputs runs/inputs_texture --out runs/out_fork --only <item>
# parity against a fork run (patterns seeded from the fork run first)
uv run --no-sync python -m drape.parity --ref runs/out_fork --new runs/out_newton --seed-patterns
uv run --no-sync python -m drape.panels --out runs/out_newton/<part>
uv run --no-sync python -m drape.bind --inputs runs/inputs_texture --out runs/out_newton/<part> --bodies runs/bodies
uv run --no-sync python -m drape.parity --ref runs/out_fork --new runs/out_newton --sheets --blind runs/out_newton/parity/blind
```
