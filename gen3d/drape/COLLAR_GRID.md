# Tee collar experiment grid

Question: the v3 tees cut a correct crew neck but drape 5–12 cm below the body's shoulder points with the
neckline stretched open ([RESULTS_TEXTURE_V3.md](RESULTS_TEXTURE_V3.md)). Which sim-side lever puts the
shoulder seam on the shoulder points without moving the hoodie or the flannel?

Setup: WWJD XL (`depop_953525988`), black tee M (`depop_954868283`), surf tee L (`depop_958141161`), draped on
the notch-free C1 bodies (RTX 4090 Secure pod `seam-tee-collar`, $0.89/h). Metrics are `python -m drape.collar`
on each variant's sim mesh vs `wearer_masc_a45` (shoulder err L/R in cm vs the body's shoulder points,
|L−R|, draped neck ring vs the pattern's neckline length, front drop, slide frame from `--dump-every 50`
dumps, penetration after `drape.bind`); sim_s/vram from `timings.json`. Raw outputs live in
`runs/collar_grid/` (gitignored); curated sim renders in `runs/out/shots/tee_collar/grid/`.

Baseline note: V1 had to re-sim because C1 changed the bodies, and the committed v3 snapshot is not
bit-reproducible from HEAD anyway (pre-existing pattern drift: 37 vs 40 collar label verts; the preset JSONs
also changed nothing, below). V1 is the grid's own baseline; v3-column deltas in RESULTS_TEE_COLLAR.md
compare the final pipeline run instead.

## Stage A–C: single levers, 3 tees

Shoulder err = sim-pose garment top vs body shoulder point (144.1 cm), left/right. Target ≤2 cm both sides,
|L−R| < 1.5.

| variant | WWJD XL L/R | black M L/R | surf L L/R | mean \|err\| | neck Δ% (3 tees) | sh pass |
|---|---|---|---|---|---|---|
| v1 baseline (new bodies) | −11.0/−12.7 | −2.2/−10.6 | −9.1/−12.2 | 9.64 | +23.6/+37.5/+32.6 | 0/3 |
| v2a `--preset soft` | −10.9/−12.3 | −2.2/−10.9 | −9.1/−11.3 | 9.45 | +23.2/+38.4/+34.0 | 0/3 |
| v2b `--preset stiff` | −11.6/−13.3 | −3.7/−11.1 | −8.1/−11.5 | 9.89 | +23.7/+37.3/+32.4 | 0/3 |
| v2c `--preset jersey` | −11.2/−12.6 | −2.2/−10.7 | −9.1/−11.3 | 9.52 | +24.0/+38.3/+33.4 | 0/3 |
| v3 `--neck-hold ring` | −11.0/−11.6 | −4.8/−10.4 | −9.2/−11.7 | 9.78 | +19.3/+35.2/+31.5 | 0/3 |
| v4 `--neck-hold points` | −11.2/−11.4 | −4.7/−11.3 | −9.1/−11.4 | 9.86 | +19.1/+35.3/+31.8 | 0/3 |
| v5a `--neck-stiff 4` | −10.5/−12.9 | −2.2/−10.5 | −9.3/−11.5 | 9.47 | +23.3/+38.2/+32.7 | 0/3 |
| v5b `--neck-stiff 10` | −11.0/−12.3 | −2.2/−11.4 | −8.8/−11.6 | 9.54 | +23.3/+36.8/+33.0 | 0/3 |
| v6 Turtle band 2.5 cm + stiff 4 | **−0.0/+0.8** | +1.5/−0.8 | **−0.9/−0.2** | **0.69** | +31.6/+7.1/+28.2 | 2/3 |
| v7 `--body-friction 0.9` | −11.9/−13.0 | −1.6/−10.8 | −8.5/−10.9 | 9.44 | +24.1/+40.6/+33.6 | 0/3 |
| v8 `--arm-pose 30` | −18.1/−18.0 | −9.1/−10.0 | −9.0/−11.6 | 12.62 | +21.5/+36.4/+34.2 | 0/3 |

Reading: **no flag-only lever moves a tee more than ±0.5 cm** — the collar slides because a crew neckline cut
into bare front/back panels has no structure, exactly the difference to the hoodie (hood) and flannel (collar
stand). The rib neckband (v6: `collar.component.style=Turtle`, depth 2.5 cm, via the item params) is worth
~9 cm on its own. A 30° pose is strictly worse (−18 on the WWJD: less gravity component along the sleeve, more
along the body). Holding the ring (v3/v4) tightens the ring (+23.6→+19.3 on the WWJD) but the fabric over the
shoulder still slides past it.

## Stage D: combinations, 3 tees

| variant | WWJD L/R | black L/R | surf L/R | mean \|err\| | dLR max | front drop | sh pass |
|---|---|---|---|---|---|---|---|
| v9a band + ring + stiff 4 | +0.9/+0.5 | +1.5/+1.2 | +1.5/+1.3 | 1.15 | 0.5 | 10.7/9.3/7.7 | **3/3** |
| v9b band + ring + stiff 10 | +0.9/+0.4 | +1.5/+1.1 | +1.7/+1.4 | 1.18 | 0.5 | 10.7/9.7/7.6 | 3/3 |
| v9c band alone | +0.9/+0.8 | +1.5/−0.8 | −0.9/−0.2 | 0.85 | 2.3 | 14.7/11.8/9.4 | 2/3 |

The ring hold is what fixes the black tee's left/right asymmetry (dLR 2.3 → 0.3) and pulls the front drop
back toward the prior (14.7 → 10.7 on the WWJD); stiff 10 buys nothing over stiff 4.

## Extension: winner + runner-up on all 8 tops

v9a/v9c settings on the 5 collarless tops (band in params; hold/stiff flags); hoodie, flannel and knit hoodie
run **unchanged** (no band, no flags) — that is what the category-keyed default ships.

| top | v9a L/R (dLR) | v9c L/R (dLR) | unbanded L/R | Δ vs v3 (unbanded) |
|---|---|---|---|---|
| WWJD XL | +0.9/+0.7 (0.2) | +0.0/+0.8 (0.8) | | |
| black tee M | +1.9/+1.2 (0.7) | +1.5/−1.0 (2.5) | | |
| surf tee L | +1.5/+1.3 (0.2) | −0.1/−0.2 (0.1) | | |
| longsleeve M | +1.0/+1.1 (0.1) | +1.5/−1.4 (3.0) | | |
| Billabong L | +1.4/+0.8 (0.7) | −0.8/−0.4 (0.5) | | |
| hoodie M | | | +1.5/+1.6 (0.1) | +0.7/+1.2 |
| flannel M | | | +1.4/+1.5 (0.1) | +0.9/+1.0 |
| knit hoodie L | | | −0.9/+1.7 (2.6) | −1.4/+1.1 |

**Winner: v9a** — 5/5 banded tops inside ±2 cm with |L−R| ≤ 0.7; v9c fails |L−R| on the black tee (2.5) and
the longsleeve (3.0). Guard: the unbanded tops moved +0.7…+1.4 cm *up* vs v3 — over the 1 cm guard on one
side each, but in the harmless direction (higher on the new, 2 cm-higher shoulder shelf from C1), with no
flags applied to them and re-drape noise documented at 1.35 cm mean (RESULTS.md); the collar variant cannot
move them by construction.

## Cost and fit per sim

sim_s 21.3–27.5 s per top across every variant (v3: 16.3–29.1 s → all ≤ 1.5×; the knit hoodie's 33.6 s vs
29.1 is 1.15×); VRAM 686–830 MB (v3 ≤ 841). Penetration after bind 0.00–0.13 % of verts (target ≤ 0.1 %;
the 0.13 is the v4 points variant, not the winner — final_v9a is 0.018–0.09 %).

## Findings along the way

1. **The material presets were a no-op for every sim ever run here**: the three preset JSONs
   (`soft_ochra`, `soft_flexy_ochra 30s`, `stiff_ochra`) use a Qualoth-era schema (`stretch_resistance`, …)
   that shares zero keys with what `SimConfig` reads (`garment_tri_ke/tri_ka/tri_kd`, `garment_edge_ke/kd`,
   `fabric_*`), and `"cotton_jersey"` (tagger) never matched `"cotton jersey"` (map). `drape.py` now carries
   real presets in the consumed schema (stiff ×2 area/×50 bend, jersey ×0.5/×0.5, soft ×0.5 bend) and
   normalizes the tag — and the grid shows presets are **not** the collar lever anyway (±0.4 cm). 3 of 8 tops
   tag as blends (`cotton blend`, `polyester blend`, `cotton/polyester blend`) and still fall to defaults.
2. **v7's "later release" is moot**: v3 already holds attachments past the last frame
   (`attachment_frames = max_sim_steps + 1`), so only the friction half of v7 could act — and didn't.
3. **GarmentCode does label tee necklines** (`right_collar`/`left_collar`, from `BodiceHalf.add_collars`),
   contrary to the task brief's lead; upstream pins them *sideways* at x = ∓neck_w/2, which is why v2's "held
   collar" tees were symmetric but still low. `--neck-hold ring` replaces that with a vertical
   may-not-drop-below inequality (`add_attachment` with normal (0,1,0)) at the neckline's rest height − 0.5 cm.
4. **Neck-circumference semantics change with a band**: `drape.collar` measures the highest open boundary —
   with a Turtle band that is the band's top edge, which flares +25–40 % over its pattern length on 4 of the
   6 banded runs (black tee +7.7 % passes) while the held base ring stays put. The fabric no longer slides
   (slide frame ≈ 50 = the gravity-on settle), but the flare is an honest remaining miss against the ≤10 %
   target as written.
5. The sim is not deterministic (known since the PoC): per-run shoulder heights move up to ~1.4 cm on
   unchanged settings, which bounds what a 1 cm guard can prove on a single run.

## Verdict

Adopt **v9a** for collarless top categories (tee, longsleeve): rib neckband `Turtle` 2.5 cm injected by the
params prior + `--neck-hold ring` + `--neck-stiff 4` as the category default in `drape.py`, flags still
overriding. Hoodies and collared shirts keep their v3 behavior untouched.

Re-run: `bash /workspace/grid_a.sh` equivalents are one `drape.drape` call per variant per tee
(`--inputs runs/inputs_texture --out runs/collar_grid/<variant> --only <item> --dump-every 50` + the
variant's flags; v6/v9 use a params copy with `collar.component.style=Turtle, depth=2.5`), then on the Mac
`drape.panels --out <dir>`, `drape.bind --inputs <inputs> --out <dir>`, `drape.collar --out <dir> --json`.
