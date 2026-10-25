# Texture v2 results (pattern-space texturing)

Question: the drape PoC ([RESULTS.md](RESULTS.md)) got the shape right but textured by front-projecting every
texel into the flat-lay photo. Side panels smeared, outseam stripes vanished (in a flat lay the outseam is the
outline), tapered legs misregistered, the back was the front mirrored, and photographed wrinkles were baked on top
of the simulated folds. Does texturing each sewing-pattern panel in its own cm space fix that?

## Pipeline

```
photos ──► spec.py (Claude) ──► spec.json: PatternSpec in cm, calibrated by the listed size, FFT-checked
cutout ──► delight.py ──► albedo.png (shading and broad wrinkles removed, hue kept) + wrinkle score
pattern json ──► panels.py ──► panels.json + .svg: per-panel cm outline, grain, labelled edges, flat-lay layout
synth.py ──► one cm raster per panel: ground + low-frequency tint, repeats, trims, placements / fallback
atlas.py ──► exact UV-island fit, 2048² (4096² if a period < 4 px), box filter, periods < 2 px collapse
texture.py ──► basecolor + normal + roughness ──► export.py ──► GLB          (old projection: --legacy)
eval.py ──► orthographic front/side/back renders, LPIPS vs the cutout, Claude rubric
```

- **spec.py** (X1): claude-sonnet-5-5 (the model id in api/app/llm/curate.py) gets every listing photo (≤ 8), the
  title, the tags and the listed size; forced tool use with the schema inlined (the gateway answers 500 to
  `messages.parse`), pydantic validation, one retry. Calibration: the garment's real flat width from its size
  (W32 waist flat ≈ 40.6 cm; tops chest/2 from drape/size_body.py). Stripe periods are re-measured by a 1D FFT
  across the grain of the albedo between the outseams, searched within ⅓×–3× of the model's period (drape folds
  win otherwise); > 30 % disagreement means the FFT wins, logged in spec_meta.json. $0.025–0.083 per item
  ($0.66 for all 16), no retries needed.
- **PatternSpec / StripeSet / Trim / Placement**: a local copy in drape/patternspec.py until garments-v3 lands them in
  shared/schema.
- **delight.py** (X3): guided filter at ~6 % of the garment width inside the alpha mask, rescaled to the median;
  mean hue shift 0.2–1.2°, wrinkle score 28–81 % lower.
- **panels.py** (X2): every edge of every panel labelled on all 16 items (44–78 edges each, 0 unlabelled), boxmesh
  deviation 0.00 cm. Grain is intrinsic to the panel (sleeves: square to the hem/cuff edge), so it does not turn
  with the sim arm pose.
- **synth.py** (X4): 24 px/cm rasters. Repeats live in panel cm along grain/cross/bias, so a tapered leg shows fewer
  stripes at the same pitch. Their phase is set by walking the stitch graph from a root panel, which matches the
  seams on that tree; one offset per panel cannot close every loop, so along curved seams the phase still drifts
  by 0.16–0.43 of a period and the seams that close a loop (the second side seam, the inseam) miss by up to 0.50
  of a period on the plaid and 0.24 on the pinstripe. Trims are bands at a distance from their labelled edges: an
  outseam stripe is centred on the seam, half on each panel, with gap and band order kept and `extent` cutting at
  the knee; widths come out exact. Backs use a back photo when the listing has one, else patch synthesis from the
  albedo, never a mirror. Rib panels keep the rib normal map.
- **Registration** (X4 + fix): photo pixels reach the pattern only through placements and the fallback
  (graphic/camo/floral/other). The torso is fitted on torso landmarks only (neck, shoulder, armpit, hem corners)
  as an upright similarity, a left/right pair is kept or dropped together, and the fit is then stretched
  vertically between the torso's hem row and the top of its central band, because the simulated torso is
  1.2–1.8× wider for its height than the photographed one. Sleeves get their own map along the sleeve's armhole →
  cuff axis. A lay whose torso band disagrees with the photo's scale by more than ~3× is not registered at all
  (the crumpled longsleeve renders from its spec alone). `--verify` checks every print area: rotation ≤ 3° on tops
  (6° on bottoms, which lie at the seller's angle), ≥ 50 % on its own panels, chest height for chest prints. WWJD
  tee: 0.0°, centred at (−2, 125) cm, 64 % on its panels; Billabong tee: 0.0°, (−1, 120) cm, 100 %.
- **atlas.py** (X6): each UV island is exactly `uv = s·cm + offset` (residual ~1e-13 cm). Faces belong to the panel
  of their UV island: the old vertex-label vote put all-stitch corner faces on the wrong panel (145 cm errors on
  the sweats). All 16 atlases are 2048² at 9.4–17.1 px/cm; the finest real stripe is 25 px per period, so none
  needed 4096². A scratch copy with a 0.25 cm grain set went to 4096² (29.4 px/cm, 7.4 px per period, no moiré)
  and a 0.06 cm set collapsed to its average colour.
- **texture.py / export.py** (X6): v2 is the default; `--legacy` keeps the old projection in `texture_legacy/` and
  exports `<safe>_draped_legacy.glb` / `<safe>_bound_legacy.glb` for the comparison.

## Drape fixes (X5)

- Bottoms hold the waist attachment for the whole sim (the PoC control's fix): all 8 bottoms now hang from the
  waist (top at 103–105 cm, body waist 106.5 cm) instead of sliding to the floor.
- Tops drape in a 45° A-pose (`_a45` bodies from drape/body.py) and drape/bind.py maps them back onto the 20° web
  pose: rebind error 0.000 cm, penetration 4.58 % → 0.02 % after the push-out (157–469 armpit vertices lifted per
  top, 0–2 left).
- The tee still sits low. The A-pose alone drapes it lopsided (shoulder tops at 140.7 / 129.9 cm); holding the
  collar attachments makes it symmetric (132.8 / 129.4 cm) but ~6 cm low on both shoulders. Our mannequin's
  shoulders are narrower and steeper than GarmentCode's mean body (31.5 cm at 26.3° vs 36.5 cm at 21.7°), which
  lives in gen3d/app, outside this branch.
- The legging and pinstripe roles drape with narrow, low-flare pants params (`_stress` sims) so the taper case is
  real.

## GPU run

RunPod Secure RTX 4090, EU-RO-1, $0.89/h (no RTX 3090 Secure stock at any CUDA floor, so GPU_RUN.md's fallback),
image `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`. setup_gpu.sh passed (upstream smoke sim 110 s).
16 drapes in 384 s (the PoC four: 113 s): bottoms 11.3–15.0 s and tops 17.6–26.3 s per sim, every sim at the
2400-frame cap. Pod stopped after ~1.5 h (~$1.37); its volume disk bills at the stopped rate until terminated.

## Eval set

`python -m drape.inputs --set texture` picks 12 real items from Postgres by regex + tags (1–2 per role, flat lays
preferred):

| role | item | listing | stresses |
|---|---|---|---|
| track | depop_936695379 | burgundy track pants, double white side stripe, W26 | stripe on the outseam = the flat-lay outline |
| track | depop_945724547 | adidas black 3-stripe track pants, W26 | same, plus a small logo |
| pinstripe | grailed_109046872 | Paul Harnden Lancashire trousers, W30 | fine tonal pinstripe on a tapered (stress) leg |
| legging | depop_958674696 | adidas tapered joggers, khaki, 3 stripes, L | taper + outseam stripes (stress) |
| widejeans | depop_958854988 | Ridgecut baggy carpenter jeans, W32 | draped outline ≠ flat-lay outline |
| stripetee | depop_958141161 | horizontal-stripe surf tee on a hanger, L | cross-grain stripes over side seams and sleeves |
| stripetee | depop_959308776 | striped longsleeve, crumpled lay, M | the same on a harder photo |
| plaid | grailed_109137061 | JCPenney wool flannel shirt, M | two-way repeat, collar and cuffs |
| graphictee | depop_953525988 | WWJD graphic tee, XL | print registration, mirrored back |
| camo | depop_957013558 | distressed camo denim pants, W32 | fallback (no repeat to model) |
| hoodie | depop_959195954 | Lee blank heather-grey hoodie, M | solid, baked wrinkles |
| tee | depop_954868283 | black tee, M | solid, baked wrinkles |

The PoC four (sweats, knit hoodie, mudwash jeans, Billabong tee) were re-draped and re-textured too (runs/out_v2).

## How it was scored

eval.py renders every draped GLB through the viewer's `?eval=1` mode (orthographic camera framed on the garment
bbox, transparent background, headless Chrome) from the front, the wearer's left side and the back, with and
without the avatar, for both textures. Two scores per variant:

- LPIPS (AlexNet) of the front render against the cutout, both centred on a grey 256² canvas.
- A Claude rubric (claude-sonnet-5-5, forced tool use) on the cutout, the listing photo and the three renders:
  seven criteria scored 0–2, or null when they do not apply (stripes present, parallel to grain, continuous across
  seams, count and spacing, side stripe from the side and back, print readable and not mirrored, wrinkles not
  doubled). An item's score is the mean of its non-null criteria.

The judge is noisy: on identical legacy textures, single passes moved an item's score by 0.33 on average (up to
1.0) between runs. The tables below average two passes per variant (`--passes 2`); the two passes still differ by
0.20 per item on average (max 0.67) on the 12-item set and by 0.37 (max 2.0) on the PoC four, so a single item
moving by less than ~0.5 is not evidence on its own, while the criterion means over 12 items are steadier. A full
run (16 items, both textures, two passes) costs $1.23.

## Results

### 12-item eval set

| role | item | spec | registration | LPIPS legacy | LPIPS v2 | judge legacy | judge v2 |
|---|---|---|---|---|---|---|---|
| track | depop_936695379 | solid, 1 trim | tps, 7 marks | 0.568 | 0.599 | 1.17 | **1.58** |
| track | depop_945724547 | solid, 2 trims, 1 placement | tps, 6 | 0.462 | 0.489 | 1.43 | **1.50** |
| pinstripe | grailed_109046872 | pinstripes 3.5 cm (FFT; model said 1.3) | affine, 4 | 0.524 | 0.545 | 1.10 | **1.80** |
| legging | depop_958674696 | solid, 1 trim, 1 placement | tps, 7 | 0.507 | 0.474 | **1.36** | 1.14 |
| widejeans | depop_958854988 | solid | tps, 7 | 0.667 | 0.646 | 0.00 | **1.33** |
| stripetee | depop_958141161 | stripes ×3, 9.0 cm | upright, 2 | 0.561 | 0.567 | 1.00 | **1.30** |
| stripetee | depop_959308776 | stripes ×4, 3.0 cm | not registered | 0.710 | 0.648 | 0.70 | **1.60** |
| plaid | grailed_109137061 | plaid ×4 (cross 12.4 cm by FFT) | upright, anchors only | 0.705 | 0.613 | 0.25 | **1.00** |
| graphictee | depop_953525988 | graphic, 1 placement | upright, 4 | 0.576 | 0.568 | **0.25** | 0.00 |
| camo | depop_957013558 | camo | tps, 7 | 0.539 | 0.526 | **0.75** | 0.33 |
| hoodie | depop_959195954 | solid, 2 trims, 1 placement | upright, 2 | 0.624 | 0.560 | 1.00 | **2.00** |
| tee | depop_954868283 | solid, 1 trim | upright, anchors only | 0.602 | 0.612 | 1.50 | **2.00** |
| | **mean** | | | 0.587 | 0.571 | 0.88 | **1.30** |

v2 scores higher on 9 of 12 items and lower on 3 (the legging, the WWJD tee, the camo pants). Registration names
the landmark fit and how many landmarks it kept; "anchors only" means every landmark was rejected and the torso's
hem and top rows carried the fit. Every atlas is 2048² (9.4–17.1 px/cm).

Per criterion, the mean over the items where the judge applied it:

| criterion | legacy | v2 | n (legacy / v2) |
|---|---|---|---|
| stripes present | 1.07 | **1.50** | 7 / 7 |
| parallel to grain | 1.44 | **1.88** | 8 / 8 |
| continuous across seams | 0.70 | **1.06** | 10 / 9 |
| count and spacing | **0.88** | 0.75 | 8 / 8 |
| side stripe from the side and back | 0.62 | **1.33** | 4 / 3 |
| print readable, not mirrored | **0.75** | 0.67 | 4 / 3 |
| wrinkles not doubled | 0.79 | **1.54** | 12 / 12 |

### PoC four, re-draped and re-textured

| role | item | spec | registration | LPIPS legacy | LPIPS v2 | judge legacy | judge v2 |
|---|---|---|---|---|---|---|---|
| sweats | depop_941190262 | solid, 3 trims, 1 placement | tps, 6 | 0.434 | 0.490 | **1.21** | 1.07 |
| hoodie | grailed_108767954 | other (fallback) | upright, anchors only | 0.502 | 0.520 | 1.10 | **1.40** |
| jeans | grailed_108843068 | other (fallback) | tps, 7 | 0.403 | 0.401 | **1.00** | 0.00 |
| tee | depop_958293311 | graphic, 1 placement | upright, 4 | 0.457 | 0.428 | **1.50** | 1.25 |
| | **mean** | | | 0.449 | 0.460 | **1.20** | 0.93 |

v2 is better only on the knit hoodie. Three of the four use the photo fallback or a print, and the sweats carry
details the spec has no home for (see below).

## Screenshots

`runs/out/shots/texture/<safe>_texture.jpg`: top row legacy, bottom row v2; front | wearer's left side | back, on
the avatar.

![track, burgundy](runs/out/shots/texture/depop_936695379_texture.jpg)
![track, adidas](runs/out/shots/texture/depop_945724547_texture.jpg)
![pinstripe](runs/out/shots/texture/grailed_109046872_texture.jpg)
![legging](runs/out/shots/texture/depop_958674696_texture.jpg)
![wide jeans](runs/out/shots/texture/depop_958854988_texture.jpg)
![stripe tee, surf](runs/out/shots/texture/depop_958141161_texture.jpg)
![stripe longsleeve](runs/out/shots/texture/depop_959308776_texture.jpg)
![plaid](runs/out/shots/texture/grailed_109137061_texture.jpg)
![graphic tee](runs/out/shots/texture/depop_953525988_texture.jpg)
![camo](runs/out/shots/texture/depop_957013558_texture.jpg)
![hoodie](runs/out/shots/texture/depop_959195954_texture.jpg)
![tee](runs/out/shots/texture/depop_954868283_texture.jpg)
![PoC sweats](runs/out/shots/texture/depop_941190262_texture.jpg)
![PoC knit hoodie](runs/out/shots/texture/grailed_108767954_texture.jpg)
![PoC mudwash jeans](runs/out/shots/texture/grailed_108843068_texture.jpg)
![PoC Billabong tee](runs/out/shots/texture/depop_958293311_texture.jpg)

## What still fails

1. **Tees ride ~6 cm low, off the shoulders.** A drape problem, not a texture one (X5 above); every tee render
   shows a boat neck.
2. **The WWJD print is clipped by the neckline.** It is upright and at chest height now, but Claude's params cut
   this XL tee with a 19.5 cm front neck drop (a crew neck is ~8–10 cm), so the top third of the print falls in the
   neck hole (64 % on its panels); the judge gives it 0 on both passes.
3. **Fallback items carry the photo's shading and break at the side seams.** The registered front keeps hem folds
   (WWJD) and whiskers and fades (mudwash jeans, read as baked wrinkles); the synthesized back does not continue
   the front's fade or camo across the side seams (camo 0.33, mudwash jeans 0.0).
4. **Lines that are not seams, and unplaced logos, are dropped.** The PoC sweats' curved knee piping and the small
   Southpole and adidas logos have no PatternSpec home: trims only attach to labelled edges, and the spec placed no
   box for those logos.
5. **Repeats are only as rich as the spec.** The surf tee's thin red and white sub-lines and the flannel's muted
   lines collapse into the few bands the spec lists, which is why count and spacing is the one stripe criterion v2
   does not win; the Harnden pinstripe has the right 3.5 cm period but far more contrast than the subtle tonal
   original.
6. **Outseam stripes from the front.** They are centred on the outseam, as built, so the front view shows a thin
   edge line where the flat lay shows the full band. The judge prefers v2 from the side and back (0.62 → 1.33) but
   marks the khaki joggers down from the front.
7. **Procedural normal maps** (shared by both paths): the denim twill is too coarse and bands horizontally, the
   jersey reads bumpy.
8. **Verify blind spots** (from the code review, not fixed): the phase gate only checks the mean on the tree seams,
   which is zero by construction; the line metrics only measure grain sets, so cross and bias sets pass vacuously;
   the scale-ratio gate only runs when there is a print (the pinstripe trouser's unused affine fit is 3.8×
   anisotropic); collars and hoods have no flat-lay frame, so their stripe phase can come out mirrored (plaid
   collar spread 0.43 of a period); the 4096/mip decision looks at the period, not the line width (the Harnden
   0.1 cm lines are 1.3 px at 2048); `extent` upper/lower is implemented but no item uses it; a semantically
   invalid spec is accepted after its one retry (none occurred).
9. **LPIPS against the flat lay is not a useful score here.** It moves by ±0.03–0.09 and rewards copying the photo,
   so it favours legacy on the PoC four.

## Next steps

1. Mannequin shoulders (gen3d/app): match GarmentCode's mean shoulder width and slope, then re-drape the tops.
2. A neckline-depth prior in drape/params.py (front neck drop from the size chart), then re-drape the tops.
3. Tint and fallback: keep only wash-scale tint (drop whiskers and folds by scale), mirror the tint field across
   the side seams so front and back meet, and seed the back's patch synthesis from the front's side-seam band.
4. PatternSpec: a `line` trim drawn as a polyline in panel cm for design lines that are not seams; placements on
   leg panels for small logos.
5. Spec repeats: sub-bands inside a StripeSet; line colour and contrast measured from the albedo.
6. Phase: a least-squares fit over all stitched edges instead of a tree, a layout frame for collars and hoods, and
   a gate on the along-seam spread and the loop residual instead of the tree mean.
7. Retune the twill and jersey normal maps (scale, amplitude).
8. Eval: three judge passes, a side-photo check when the listing has one, drop LPIPS against the flat lay.
9. Switch drape/patternspec.py to shared/schema after garments-v3 merges.

Needs the GPU box: any re-drape (the shoulder fix, the neckline prior, new items or new params). Spec, delight,
panels, synth, atlas, texture, export and eval all run on the Mac.

## Re-running

```
cd gen3d/drape
uv run --no-sync python -m drape.inputs --set texture        # prod Postgres via DATABASE_URL (ssh tunnel)
uv run --no-sync python -m drape.params --inputs runs/inputs_texture
uv run --no-sync python -m drape.spec --inputs runs/inputs_texture
# GPU box (pod + rsync: GPU_RUN.md); pose, waist hold and stress params follow the category and role
uv run --no-sync python -m drape.pattern --inputs runs/inputs_texture --bodies runs/bodies --out runs/out_texture
uv run --no-sync python -m drape.drape --inputs runs/inputs_texture --bodies runs/bodies --out runs/out_texture
# Mac, after rsyncing runs/out_texture back
uv run --no-sync python -m drape.texture --inputs runs/inputs_texture --out runs/out_texture   # runs delight if missing
uv run --no-sync python -m drape.bind --inputs runs/inputs_texture --out runs/out_texture
uv run --no-sync python -m drape.texture --inputs runs/inputs_texture --out runs/out_texture --legacy
uv run --no-sync python -m drape.export --inputs runs/inputs_texture --out runs/out_texture
uv run --no-sync python -m drape.export --inputs runs/inputs_texture --out runs/out_texture --legacy
uv run --no-sync python viewer/build_manifest.py --inputs runs/inputs_texture --out runs/out_texture
uv run --no-sync python -m drape.eval --inputs runs/inputs_texture --out runs/out_texture --passes 2
```

The order matters: bind writes the web-pose obj that export and the legacy projection read, so drape/scripts/
run_poc.sh now runs texture → bind → texture --legacy → export → export --legacy (its old texture → export → bind
order exported every top in the 45° sim pose). On the pod, texture v2 calls Claude for any item without a
spec.json, so run drape.spec on the Mac before syncing the inputs.

Per-stage checks: `drape.spec --recheck` (FFT only, no Claude), `drape.delight --verify`, `drape.panels --verify`,
`drape.synth --verify` (writes `<safe>/synth_preview.png`). Always `uv run --no-sync`: a plain `uv sync` prunes the
hand-installed warp fork (see drape/scripts/setup_gpu.sh). The eval extra (lpips, torch, playwright; Chrome from
/Applications) needs one `uv sync --extra eval`, after which the warp fork has to be re-installed before draping
again.

## Viewer

`cd <repo root> && python3 -m http.server 8808`, then
http://localhost:8808/gen3d/drape/viewer/index.html?out=runs/out_texture for the 12-item set, or `?out=runs/out_v2`
for the PoC four. The top bar toggles texture v2 | legacy (and draped | bound for the morph-bound GLBs); `?eval=1`
is the orthographic mode eval.py drives. The left pane (current template pipeline) is empty for the eval items,
which have no template GLB.

## Verdict

**Use v2 for the pattern kinds now; the photo-fallback kinds are not ready on either path.**

- On the 12-item set the judge scores v2 1.30 against 0.88 for legacy (9 of 12 items better, two passes
  averaged), and the gains are on what front projection broke: stripes present 1.07 → 1.50, parallel to grain
  1.44 → 1.88, continuous across seams 0.70 → 1.06, side stripes from the side and back 0.62 → 1.33, wrinkles not
  doubled 0.79 → 1.54.
- Checked on all 16 items rather than judged: outseam bands split half/half at exact widths, stripes keep their cm
  pitch on tapered legs, backs are synthesized and never mirrored, the atlas is cm-exact, every GLB verifies.
- v2 loses where it still borrows pixels from the photo: the clipped WWJD print (0.0), front-only shading on camo
  and mudwash denim (0.33, 0.0), and the PoC four average 0.93 against 1.20. Legacy is no answer there either: it
  mirrors the print onto the back.
- Before scaling: the shoulder fix for tees, a neckline prior, tint mirrored across the side seams, then this eval
  again with three judge passes.
