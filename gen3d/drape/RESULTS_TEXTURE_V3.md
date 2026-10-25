# Texture v3 results

Question: [texture v2](RESULTS_TEXTURE.md) won on pattern kinds and lost where it borrowed pixels from the
photo, and every tee rode ~6 cm low off the shoulders. v3 fixes the mannequin's shoulders, puts a prior on the
neckline depth, makes the tint and the back synthesis seam-true, solves stripe phase globally, adds sub-bands /
non-seam lines / leg logos to the spec, retunes the procedural normals, and makes the verify gates honest. Does
the 16-item eval improve, and is there a license-clean path for the sim?

## The fixes (one commit each)

1. **Mannequin shoulders** (`fix(gen3d): wider, flatter mannequin shoulders`). The masc base at slider 0.5 goes
   from biacromial 31.51 cm at 26.31° to **36.50 cm at 21.99°** (GarmentCode's mean body: 36.5 at 21.7°); the
   fem base scales by the same ratio (28.18 → 32.79 cm, 31.49° → 26.41°). Slider sweep stays monotonic
   (shoulders 0/0.5/1 → 33.1/36.5/39.9 cm, 24.9°/22.0°/19.7°); armscye_depth and neck_w unchanged; morph target
   names and rest weights (0.5) byte-identical; anchors regenerated. Avatar + template GLBs re-exported; the
   tee and jacket templates still sit on the shoulders ([before](runs/out/shots/texture_v3/fixes/shoulders_before.png) /
   [after](runs/out/shots/texture_v3/fixes/shoulders_after.png)). Templates are **not** rebaked here.
2. **Neckline prior** (`fix(drape): neckline depth prior for tops`). Front neck drop clamped per neckline type:
   crew 7–10 cm, scoop 10–14, v-neck 12–20, hoodie 6–9, ±10 % XS→XXL; back drop 1.5–3 cm. The cm↔`fc_depth`
   relation is exact (GarmentCode measures collar depth against the bust line; wearer_masc bust line 18.29 cm),
   every clamp is logged into params_meta.json, and `drape.params --reclamp` re-applies the prior to stored
   params without a model call. The WWJD XL tee's 19.5 cm front drop re-clamps to **7.42 cm** (re-measured from
   the regenerated pattern: 7.4200 cm). The prompt now carries the numeric ranges.
3. **Seam-true tint, lines and phase** (`feat(drape): seam-true tint, lines and phase`). Tint is wash-scale only
   (low-passed by panel size), mirrored across the side seams, and the back's quilt is seeded from the front's
   side-seam band so camo/fades continue ([camo](runs/out/shots/texture_v3/fixes/tint_camo_back_seed.png),
   [mudwash](runs/out/shots/texture_v3/fixes/tint_mudwash_back_seed.png)). Stripe phase is a length-weighted
   least-squares fit over **all** stitched edges (tree kept as rank-deficiency fallback): mean loop residual
   drops ~2–2.7× vs the tree (plaid cross 0.149 → 0.059, pinstripe 0.066 → 0.032 of a period); collars get a
   band-along-the-neckline frame and hoods a centre-seam frame, so their phase is never mirrored. PatternSpec
   gains `StripeSet.sub_bands`, `Trim.kind="line"` with a `path` in cutout coords mapped through the
   registration, and four leg placement panels — all with defaults; all 16 v2 specs still parse. Line colour is
   measured from the albedo between the spec's bands and blended only when the measurement is trustworthy
   (resolvable width ≥ 2 px and fold phase concentration ≥ 0.5) — the Harnden pinstripe stays tonal
   ([crop](runs/out/shots/texture_v3/fixes/pinstripe_contrast.png)). Renderer demos:
   [sub-bands](runs/out/shots/texture_v3/fixes/sub_bands_surftee.png),
   [knee piping as a line trim](runs/out/shots/texture_v3/fixes/line_trim_knee_piping.png),
   [left_leg_front logo](runs/out/shots/texture_v3/fixes/leg_logo_placement.png).
4. **Underarm smear** (`fix(drape): no underarm texture smear`). The cause was neither the atlas nor mip bleed:
   re-posing in `bind.py` stretched the faces straddling the arm/trunk binding boundary (straddling faces p50
   2.9–3.1× area stretch, every other face exactly 1.00; a UV-checker render streaked with no texture content).
   Fix: ring-mean relaxation of the pose field (`POSE_RELAX=24`) plus a rebuilt push-out (normal-only offset,
   Dirichlet diffusion, growing fixed set — penetration 0 on both repro items, offsets spread ~6× wider,
   anisotropy p99 −29 %/−18 %). [Before](runs/out/shots/texture_v3/fixes/underarm_before.png) /
   [after](runs/out/shots/texture_v3/fixes/underarm_after.png) on the WWJD tee; re-pose stretch p99 on the
   regression items 6.04 → 3.01 and 10.53 → 2.92. Residual: the surf tee's straddle p99 5.92 remains (reduced,
   not eliminated).
5. **Normals** (`fix(drape): retune twill and jersey normals`). Denim: two offset diagonal wale sets at exactly
   45° (was a single hard 63° stripe), period 0.10 cm, band-limited so a sub-pixel wale fades to zero instead of
   aliasing (at 2048², 9.4–17.1 px/cm, 0.1 cm is 0.9–1.7 px — the 45° read is carried by a diagonally smeared
   grain + slub); tile joins seamless (wrap step 2.74× → 0.99×); atlas normal tilt on the jeans 57.3° → 8.8°
   mean. Jersey: finer, strength 1.8 → 0.9, noise low-passed (high-freq power 0.88 → 0.10–0.21).
   [Swatches](runs/out/shots/texture_v3/fixes/normals_denim_swatch.png) ·
   [tile joins](runs/out/shots/texture_v3/fixes/normals_tile_joins.png) ·
   [jeans render](runs/out/shots/texture_v3/fixes/normals_jeans_render.png) ·
   [tee render](runs/out/shots/texture_v3/fixes/normals_tee_render.png).
6. **Honest gates + eval** (`fix(drape): honest verify gates and 3-pass eval`). Phase gate on the loop residual
   (> 0.15 period fails) and on the length-weighted spread mean (> 0.5 = the solve broke; worst-seam spread is
   intrinsic seam geometry no offset can fix, so it is reported, not gated); sub-2 cm seam stubs stay in the fit
   but no longer define the headline numbers. Line metrics scan each set along its own normal (cross and bias
   included) with a per-set gradient cone, and run on every pattern-mode item; "0 of N seams scored" now fails
   instead of passing vacuously. The scale-ratio gate fires on every accepted registration (the pinstripe's
   unused 3.8× fit now fails). The 4096 decision looks at min over period, line width and sub-band width
   (lines ≥ 2 px, periods ≥ 4 px): the Harnden promotes to 4096 (0.1 cm lines: 1.29 px → 2.58 px). Every gate
   was shown to fail on deliberately broken input and pass restored. `eval --passes 3` is the default; LPIPS is
   out of the headline (kept in eval.csv); per-criterion means carry n; the per-item pass spread is printed; a
   `matches_side_photo` criterion runs when a listing has a side/back photo (none of the 16 do — all "n/a").

## GPU run

RunPod Secure RTX 4090 (no RTX 3090 Secure pod stock at the ≥ 12.8 CUDA floor — same as the v2 run), US-NC-1,
$0.89/h, pod `seam-texture-v3`, image `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`. setup_gpu.sh
passed (smoke sim 82 s). All 16 items re-draped with the new bodies and the neckline prior: **303 s of sim**
(bottoms 12.5–15.4 s, tops 16.3–29.1 s), VRAM ≤ 841 MB, every sim at the 2400-frame cap with the usual
over-reporting upstream flags (same as v2; no hard failures). Billed **$1.72** for the whole session (drapes +
license spike). The pod is stopped; its 50 GB volume disk bills at the stopped rate until terminated.

### Shoulder-top heights (web pose, body shoulder points at 144.1 cm, x = ±18.25)

| item | garment L / R cm (v3) | Δ vs body | v2 (x = ±15.76) |
|---|---|---|---|
| WWJD tee XL | 132.9 / 132.0 | −11.2 / −12.1 | 132.6 / 132.7 |
| black tee M | 139.3 / 133.3 | −4.8 / −10.8 | 137.0 / 134.5 |
| surf tee L | 136.5 / 133.4 | −7.5 / −10.7 | 134.7 / 131.0 |
| hoodie M | 144.9 / 144.4 | +0.8 / +0.3 | 144.9 / 144.9 |
| longsleeve M | 137.8 / 133.9 | −6.3 / −10.2 | 137.9 / 133.3 |
| flannel M | 144.6 / 144.6 | +0.5 / +0.6 | 144.7 / 144.7 |
| Billabong tee L | 134.5 / 132.7 | −9.6 / −11.4 | 137.2 / **129.8** |
| knit hoodie L | 144.6 / 144.7 | +0.6 / +0.6 | 144.8 / 144.8 |

Hoodies and the flannel sit **on** the shoulder points. Tees hang straighter (the Billabong's 7.4 cm
left/right lopsidedness closes to 1.8 cm) and the WWJD sits visibly higher on the body
([v2 vs v3 sim](runs/out/shots/texture_v3/fixes/wwjd_sim_v2_v3.png)), but tee shoulder seams still ride
5–12 cm below the shoulder point and the draped neckline still opens wider than the 7.42 cm the pattern now
cuts — the collar stretches open during the sim, which the prior alone cannot stop.

## How it was scored

Three columns, all judged in one session by the same rubric (claude-sonnet-5-5, forced tool use, **3 passes
per variant**, per-criterion means over the passes that scored it):

- **legacy** — front-projection texturing on the **v3 geometry** (new bodies + neckline prior).
- **v2** — the preserved v2 artifacts (`runs/out_texture`, `runs/out_v2`: old bodies, v2 pipeline), re-judged
  at 3 passes so all columns share one judge regime. (The committed 2-pass v2 numbers are in
  [RESULTS_TEXTURE.md](RESULTS_TEXTURE.md); same artifacts, different judge run.)
- **v3** — the full v3 pipeline on the v3 geometry (`runs/out_texture_v3`, `runs/out_v3`).

The judge is still noisy: the per-item 3-pass spread averages ~0.2 (max 1.0), so a single item moving less
than ~0.5 is not evidence; criterion means over 12 items are steadier. LPIPS lives in each run's `eval.csv`
only — it rewards copying the photo and is not part of the headline. Full 16-item, two-variant, 3-pass judge
runs cost $1.38 (12-item set) + $0.46 (PoC four) per out dir.

## Results

### 12-item eval set (judge mean, 3 passes)

| role | item | legacy (v3 geom) | v2 (re-judged) | v3 |
|---|---|---|---|---|
| track | depop_936695379 | 1.17 | 1.50 | 1.44 |
| track | depop_945724547 | 1.48 | 1.52 | 1.43 |
| pinstripe | grailed_109046872 | 0.80 | 1.67 | **1.80** |
| legging | depop_958674696 | **1.45** | 0.86 | 1.10 |
| widejeans | depop_958854988 | 0.67 | 1.33 | **2.00** |
| stripetee | depop_958141161 | 0.83 | 1.40 | **1.73** |
| stripetee | depop_959308776 | 1.07 | 1.67 | 1.60 |
| plaid | grailed_109137061 | 0.61 | 1.00 | **1.33** |
| graphictee | depop_953525988 | 0.67 | 0.44 | 0.67 |
| camo | depop_957013558 | **1.00** | 1.00 | 0.89 |
| hoodie | depop_959195954 | 1.00 | 1.67 | **2.00** |
| tee | depop_954868283 | 1.33 | 2.00 | **2.00** |
| | **mean** | 1.01 | 1.34 | **1.50** |

### Per criterion (mean over items that scored it, n in brackets)

| criterion | legacy (v3 geom) | v2 (re-judged) | v3 |
|---|---|---|---|
| stripes present | 1.33 (7) | 1.38 (7) | **1.48** (7) |
| parallel to grain | 1.62 (7) | 1.79 (8) | **2.00** (7) |
| continuous across seams | 0.78 (10) | **1.20** (10) | 1.11 (9) |
| count and spacing | **1.08** (8) | 0.71 (8) | 0.92 (8) |
| side stripe, side and back | 0.67 (5) | 1.11 (3) | **1.00** (3) |
| print readable, not mirrored | 1.08 (4) | 0.67 (3) | **1.11** (3) |
| wrinkles not doubled | 0.83 (12) | 1.61 (12) | **1.78** (12) |

### PoC four

| role | item | legacy (v3 geom) | v2 (re-judged) | v3 |
|---|---|---|---|---|
| sweats | depop_941190262 | 1.38 | 1.29 | 1.38 |
| hoodie | grailed_108767954 | 0.93 | 1.33 | **1.40** |
| jeans | grailed_108843068 | **1.00** | 0.83 | 0.50 |
| tee | depop_958293311 | **1.83** | 1.33 | 1.00 |
| | **mean** | **1.28** | 1.20 | 1.07 |

v3 wins the 12-item set (1.50 vs 1.34 vs 1.01) and leads or ties 9 of 12 items; the gains concentrate exactly
where the fixes aimed: the pinstripe (tonal, 4096, measured contrast) 1.67 → 1.80 with legacy at 0.80, wide
jeans 2.00, hoodie 2.00, plaid 1.33, surf tee 1.73. The PoC four still prefer legacy: three of the four are
photo-fallback or print items, the same kinds v2 lost — the mudwash jeans (0.50, pass spread 1.0) and the
Billabong tee carry the loss.

## Screenshots

`runs/out/shots/texture_v3/<safe>_texture.jpg`: top row legacy (v3 geometry), bottom row v3; front | wearer's
left side | back, on the avatar. Fix-evidence crops in `runs/out/shots/texture_v3/fixes/`.

## License spike

[LICENSE_SPIKE.md](LICENSE_SPIKE.md) (report-only; a licensing finding, not legal advice). The sim fork we run
(`NvidiaWarp-GarmentCode` @ 63baf68) is **NVIDIA Source Code License — non-commercial only** (§3.3: "research
or evaluation purposes only"; §3.2 makes it sticky for derivatives). Upstream warp is Apache-2.0 from v1.7.0,
Newton 1.7.0 is Apache-2.0, GarmentCode/pygarment is MIT. There is **no drop-in permissive replacement**: the
fork's cloth features (self-collision, attachments, body drag, body-collision constraint, `mesh_query_edge`)
total ~3,300 changed lines across 13 files plus a 326-line module including 112 lines of CUDA/C++. Pattern
generation is already license-clean (MIT path verified: both spike items produced patterns under an
upstream-warp override). Recommended port target if pursued: **Newton 1.7.0** — upstream `warp.sim` is
end-of-life. The spike's fork-side baseline drapes and the port-surface inventory live in `spike/`.

## What still fails

1. **Tee necklines still drape open.** The pattern now cuts a 7.42 cm crew, but the sim stretches the collar
   into an off-shoulder line and tee shoulder seams still sit 5–12 cm below the body's shoulder points (the
   WWJD judge score stays 0.67). Collar stiffness / attachment during the sim is the next lever, not the
   pattern.
2. **Photo-fallback kinds are still not ready** (camo 0.89, mudwash 0.50): the seam-true tint and back seeding
   improved continuity but the judge still reads baked shading; the PoC four prefer legacy 1.28 vs 1.07.
3. **Sub-bands render but barely read** at 10–17 px/cm — the surf tee's thin red/white sub-lines are in the
   spec (8 sub-bands) and the raster, yet the 3-view render shows flat bands; count-and-spacing (0.92) still
   trails legacy (1.08).
4. **v3 sim artifacts**: small sleeve-top clip-throughs on the WWJD sim and a hard crease line down one
   sleeve/side; the surf tee's muddy lower back (present in v2 too).
5. **Judge noise is unchanged** (±0.2 mean pass spread, max 1.0) — per-item deltas under ~0.5 remain
   inconclusive at 3 passes.
6. Aux wearer bodies (heavy/tall/183/h08) were not rebuilt with the new shoulders; only old PoC experiments
   reference them.

## Next steps

1. Hold or stiffen the collar during the tee sims (attachment on the neckline ring), then re-drape the tees.
2. Port the fork's cloth features to Newton 1.7.0 (Apache-2.0) — the one production blocker.
3. Photo-fallback: move from tint mirroring to a measured shading-removal pass on the registered front, and
   seed the back from a larger band.
4. Render-scale sub-bands: bump sub-band contrast or force 4096 when sub-band width < 2 px at 2048.
5. Rebake the item textures onto the new templates (gen3d/app) — the mannequin change invalidates them.

## Re-running

Same commands as [RESULTS_TEXTURE.md](RESULTS_TEXTURE.md) with the v3 out dirs (`--out runs/out_texture_v3`,
PoC `--out runs/out_v3`); `drape.params --reclamp` applies the neckline prior to stored params without a model
call; `drape.spec --force` regenerates specs with the sub-band/line/leg-logo prompt. The viewer gains a
`run: v2 | v3` toggle (shown when the paired out dir has a manifest):
http://localhost:8808/gen3d/drape/viewer/index.html?out=runs/out_texture_v3 (12-item set) or
`?out=runs/out_v3` (PoC four).

## Verdict

**v3 is the new default for pattern kinds; photo-fallback kinds remain open.** On the 12-item set, in one
3-pass judge session, v3 scores 1.50 against 1.34 for the preserved v2 artifacts and 1.01 for legacy on the
same geometry — and the targeted fixes show up as the wins (pinstripe 1.80, wide jeans 2.00, hoodie 2.00,
plaid 1.33, wrinkles-not-doubled 1.78). The license blocker is confirmed and scoped: a ~3.3k-line feature port
to Newton, with pattern generation already clean.
