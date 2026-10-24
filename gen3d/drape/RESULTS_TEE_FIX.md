# Tee fix results

Question: the tee-collar branch "passed" its own shoulder metric while the screenshots showed tees riding
the shoulders like halter straps ([RESULTS_TEE_COLLAR.md](RESULTS_TEE_COLLAR.md) vs
`runs/out/shots/tee_collar/final/depop_958141161_collar.jpg`). What actually keeps a tee on this
mannequin's shoulders, under a metric that cannot be gamed and a blind visual review?

## Root cause (H1): the body yaml was measured from the wrong landmark

`drape/body.py` measured six GarmentCode keys from the **arm-cap apex** instead of the **nape/neck base**
([MEASUREMENTS.md](MEASUREMENTS.md) has the full 27-key audit with vendor file:line quotes, calibrated
against GarmentCode's own matched `mean_all.obj`+`.yaml` pair):

| key | was | is | why it matters |
|---|---|---|---|
| `head_l` | 30.93 | 26.06 | GarmentCode places a top's neckline corner and sleeve pivot at `height − head_l` (sleeves.py:189-193, tee.py:62). 4.87 cm too much head = the whole shoulder girdle drafted/placed 4.9 cm below the neck base. |
| `shoulder_w` | 36.50 | 37.58 | was the arm-ball apex vertex (pose-dependent); acromion = the shoulder ring's widest point. Sleeve pivot sits at ±shoulder_w/2. |
| `armscye_depth` | 9.57 | 13.23 | used the armpit lofting *station*, 3.6 cm above the real arm/trunk pit. |
| `vert_bust_line` / `waist_line` / `waist_over_bust_line` | — | +4.87 / +5.25 / +4.87 | same bad datum (waist_line now geodesic per the GC definition). |
| `shoulder_incl` | 21.99° | 21.03° | endpoint fix. |
| `arm_pose_angle` | — | unchanged | **verified correct**: `mean_all_tpose.yaml: 0.0` proves GC measures degrees *below horizontal*; our `90−deg` export is right, a45 = the simmed pose. |

The evidence chain, each piece committed on this branch:

- **T1 control** ([control/README.md](control/README.md)): the same tee patterns — including ones cut
  from *our* measurements — drape at **+0.86…+1.20 cm above the shoulder points on GarmentCode's own
  mean body** with stock settings and no band. Our patterns were never the problem. (Bundled body:
  github.com/mbotsch/GarmentMeasurements provenance, MIT; no SMPL.)
- **T4 slide film** ([film/README.md](film/README.md)): on our body the boxmesh starts with the shoulder
  seam's *highest* vertex 3.50–3.72 cm **below** the acromion and the armhole ring 8.9–11.3 cm below the
  arm root; the WWJD XL is off both shoulders by frame 25 and never recovers. Identical frame-0 placement
  with and without the v9a hold — the band+ring hold never fixed placement, it pinned a mislocated collar.
- **T3 audit** (MEASUREMENTS.md): the datum error above, found by calibrating every key against GC's
  matched body+yaml pair rather than prose.

Why the old numbers lied: `drape.collar` reports the highest garment point in a 2 cm column over each
shoulder point. The held neckband is always that point, so v9a scored +0.5…+2.1 "pass" while the body
and sleeves hung below it (old table vs new gates below).

## What was tried (tracks), in order

| track | change | result |
|---|---|---|
| T5-0 revert | v9a defaults removed: `params.py` NECKBAND injection deleted, `drape.py` NECK_DEFAULT (ring hold + ×4 stiffness) deleted; `--reclamp` strips the bands it injected (keyed off the `params_meta.json` log; the flannel's real `SimpleLapel` untouched) | commit `fix(drape): revert v9a collar defaults` |
| T5-A measurements | corrected `body.py` (committed in Wave 1), bodies regenerated, `--reclamp` (bust_line 17.84→21.10 moves the neckline-depth mapping), all 8 tops + XS/M/XL sweep re-draped | **cap coverage 0–63% → 100/100 on every run, both poses**; shoulder seam from −3.5 cm to **+1.5/+1.8 cm above the acromion**; v3 hoodie's torn right shoulder (64.9%) healed to 100% |
| band, 1:1 | rib neckband restored as a **per-item pattern feature** — all five collarless listings show a rib crew band (photo-checked); `Turtle 2.5 cm` in stored params only, no code default, **no hold, no stiffness** | neck-ring flare gone (+0.2…+1.1% vs pattern); front still falls into a V; neck_drop worse by ~1 cm |
| band, stretch-on | `NECKBAND_RATIO = 0.85`: band cut 0.85× the neckline (declared before results; real construction — bands are cut short and stretched on). GC drafts the band exactly 1.000× the neckline arc (an earlier 1.19× reading was a chord-vs-arc measurement error, corrected in-session) | every neck_drop −2.1…−3.8 cm; XS passes; cap coverage stays 100 everywhere; commit `fix(drape): stretch-on rib neckband` |

Not needed: T5-B (shoulder reshape — the hemisphere cap holds fabric fine once the pattern sits at the
right height), T5-C (placement is downstream of the yaml), T5-E (fallback).

## Gate table — old metric vs frozen coverage gates

Old = `drape.collar` sim-pose shoulder error L/R (the metric that "passed" v9a). New = the frozen gates
(`drape/gates.json`, committed before any fix ran and byte-identical since): cap coverage ≥95% within
2 cm both sides both poses, armhole ≤5 cm of the arm-root ring, sleeve hem ±3 cm/ΔLR<1.5, neck ring
≤12% of pattern, front drop in the per-size prior, strap detector, pen ≤0.1%, sim ≤2× v3.

| top | old collar sim L/R (“pass”≤2) | cap cov % sim · web | armhole ≤5 | sleeve ≤3/Δ<1.5 | neck ≤12% | drop (band) | strap | pen ≤0.1 | sim s | gates | blind review |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WWJD tee XL | +0.9/+0.5 | 100/100 · 100/100 | 8.69 | 4.4/Δ0.2 | +2.0% | 12.8 (7.4–10.6) | ok | 0.000 | 33.3≤47.8 | FAIL armhole,sleeve_hem,neck_drop | FAIL Q3 |
| black tee M | +1.5/+1.8 | 100/100 · 100/100 | 3.10 | 0.5/Δ0.1 | +2.2% | 9.5 (6.9–9.8) | ok | 0.000 | 25.5≤44.0 | **PASS** | FAIL Q3 |
| surf tee L | +1.5/+1.1 | 100/100 · 100/100 | 2.80 | 1.6/Δ0.0 | +2.8% | 9.2 (7.1–10.2) | ok | 0.010 | 27.0≤43.3 | **PASS** | FAIL Q3 |
| longsleeve M | +1.4/+1.6 | 100/100 · 100/100 | 2.65 | 1.1/Δ0.1 | +2.4% | 8.2 (6.9–9.8) | ok | 0.063 | 35.7≤50.4 | **PASS** | FAIL Q3 |
| hoodie M | +1.6/+1.5 | 100/100 · 100/100 | 5.96 | 2.4/Δ0.2 | +0.1% | 34.9 (5.9–8.8) skip | ok | 0.000 | 40.1≤58.2 | FAIL armhole | **PASS** |
| flannel M | +1.5/+1.5 | 100/100 · 100/100 | 3.48 | 2.0/Δ0.0 | +0.8% | 17.5 (6.9–9.8) skip | ok | 0.055 | 34.6≤38.7 | **PASS** | FAIL Q3 |
| Billabong tee L | +1.4/+0.8 | 100/100 · 100/100 | 4.28 | 1.8/Δ0.1 | +2.4% | 10.8 (7.1–10.2) | ok | 0.000 | 30.4≤45.7 | FAIL neck_drop | FAIL Q3 |
| knit hoodie L | −5.0/+2.0 | 100/100 · 100/100 | 4.96 | 0.7/Δ0.1 | +0.2% | 35.7 (6.1–9.2) skip | ok | 0.000 | 49.4≤55.0 | **PASS** | **PASS** |
| black tee XS (sweep) | +1.5/+1.3 | 100/100 · 100/100 | 5.37 | 2.9/Δ0.4 | +2.2% | 6.9 (6.9–9.8) | ok | 0.159 | 21.8≤44.0 | FAIL armhole,penetration | FAIL Q3 |
| black tee M (sweep) | +1.5/+1.8 | 100/100 · 100/100 | 3.30 | 0.7/Δ0.7 | +2.4% | 9.1 (6.9–9.8) | ok | 0.024 | 25.6≤44.0 | **PASS** | FAIL Q3 |
| black tee XL (sweep) | +1.3/+0.8 | 100/100 · 100/100 | 6.56 | 3.2/Δ0.2 | +1.7% | 11.2 (6.9–9.8) | ok | 0.000 | 29.3≤44.0 | FAIL armhole,sleeve_hem,neck_drop | FAIL Q2,Q3 |

## Blind review (T6)

A fresh reviewer saw only the contact sheets (metric header cropped), the listing photos and the
six-question rubric — no metrics, no code, no plan. Verbatim verdicts in
[REVIEW_TEE.md](REVIEW_TEE.md).

Round 2 (final artifacts): **hoodie M and knit hoodie L PASS all six questions in both poses.** Every
other sheet fails exactly Q3 — "every crew-neck listing renders with a V or wide notched scoop dropping
onto the chest instead of a crew at the base of the neck. Shoulder coverage (Q1), sleeve seam position
(Q2, except the XL sweep's cape-like sleeves), symmetry (Q5) and wearability (Q6) hold on all 11
sheets." The flannel's Q3 fail is its lapel draping open (buttons/placket are texture-stage and the
sheets are untextured sim renders — the reviewer flagged this reading as a judgement call; verdict kept
as written). Round 1 (pre depth-fix) had failed all 11 on Q3 with the V "plunging well down the chest";
round 2's V is "closing around the collarbone line" — the fix moved it, the shape still is not a crew.

## Judge scores (eval --passes 3, tops)

Rubric means over 3 judge passes (claude-sonnet-5-5; the criteria are texture criteria — none score
"sits on the shoulders", so the drape win lives in the gate table and the sheets, not here). v3 column
from RESULTS_TEE_COLLAR.md's table for reference; judge noise is ±0.2 mean pass spread.

| top | legacy (now) | now | v3 ref |
|---|---|---|---|
| WWJD tee XL | 0.83 | 0.50 | 0.67 |
| black tee M | 1.00 | 1.67 | 2.00 |
| surf tee L | 0.93 | 1.80 | 1.73 |
| longsleeve M | 0.87 | 1.60 | 1.60 |
| hoodie M | 1.00 | 1.67 | 2.00 |
| flannel M | 0.60 | 1.20 | 1.33 |
| **mean (6)** | 0.87 | **1.41** | 1.56 |
| Billabong tee L (PoC) | 1.50 | 1.67 | 1.00 |
| knit hoodie L (PoC) | 1.20 | 1.33 | 1.40 |

Mean 1.41 vs v3's 1.56 is inside the judge's documented noise (the tee-collar run also scored 1.41);
the WWJD stays the known low outlier (print clipping, unchanged). Full stdout in the run log; each
`--only` pass overwrites `eval.json`/`eval.csv` as before.

## Contact sheets

- v3 (broken, for the record): `runs/out/shots/tee_fix/sheets_v3/` — tees at 0–25% cap coverage.
- tee-collar (the lie): `runs/out/shots/tee_fix/sheets_tee_collar/` — black tee M band riding as a
  halter strap over a bare right shoulder, old metric +1.5/+1.8 "pass".
- now: `runs/out/shots/tee_fix/sheets_final/` — every top covered in both poses.

## Vendor behaviour patched from gen3d/drape (vendor/ untouched)

All pre-existing patches from v2/v3/tee-collar remain (see RESULTS_TEE_COLLAR.md's table). New in this
branch, one site: `drape/pattern.py _stretch_on_neckband()` — `collars.Turtle.__init__` wrapped so that,
for the duration of that constructor only, `StraightBandPanel` panels are cut at `NECKBAND_RATIO = 0.85`
of their drafted length (restored in `finally`; `SimpleLapel`, hoods, cuffs and waistbands proven
unaffected). The tee-collar-era sim patches for `--neck-hold`/`--neck-stiff` remain available behind
flags but are no longer any category's default.

## Spend

One pod for the whole run: `kzt8o7vm7al529`, A40 48GB Secure (CA-MTL-1), **$0.59/h** — created
2026-10-23 20:37Z after the catalog read showed no RTX 4090 Secure stock at placement, **stopped**
2026-10-24 00:14Z (3.58h uptime; no volume, so the stopped pod bills nothing). Billing read for the
Oct-23 UTC bucket: **$1.82** ($1.79 GPU + $0.03 disk); the ~14 min past midnight UTC adds ≈$0.14 when it
settles — **≈$2.0 GPU total, against the $15 cap**. Claude spend this run: ≈$1.4 of judge passes
(12 × ~$0.12) + $0 params (reclamps are model-free). Setup to first smoke sim: 86 s; sims 20–50 s each
on the A40, every one inside its 2× v3 budget.

## What still fails

1. **Crew necklines still read as a shallow V, not a round crew** (blind review Q3, all collarless
   tees + the flannel's open lapel). The gates agree where the prior is still out of reach: WWJD XL
   12.8, Billabong 10.8, XL sweep 11.2 vs their bands. Two mechanisms remain, both documented and both
   stopped at honestly: (a) GarmentCode's own `fc_depth >= 0.3` schema floor keeps the cut 2.8-3.9 cm
   above the prior's target on large necklines — solving below the floor was pre-declared, then stopped,
   because the band pulls the draped drop ~3-4 cm above the cut, so a uniform sub-floor solve would
   overshoot the four now-passing tops into fail-low, and compensating per item would be tuning against
   the gate; (b) the rib band cinches to a point at the centre-front seam instead of rounding — a
   drape-shape issue no flag-level lever in this stack addresses (holds and stiffness are reverted and
   banned as defaults by this task).
2. **Armhole gate on oversized cuts**: WWJD XL 8.69, XL sweep 6.56, XS 5.37, hoodie 5.96 vs 5.0 — the
   seam of a boxy/dropped-shoulder cut sits outboard of the arm-root ring by construction; the blind
   review nonetheless answers "sleeves sit at the shoulder: yes" on all of them except the XL sweep.
3. **XS penetration 0.159%** (was 0.093 pre-band): the tightened neck pinches on the smallest size.
4. **WWJD XL sleeve_hem 4.4 cm** and the XL sweep's flaring sleeves (blind Q2 fail) — oversized sleeve
   drape, not slide; sleeve ΔLR is 0.2 cm.
5. The reviewer notes the black tee renders cropped at the lower ribs vs a full-length listing — body
   length is outside both the gates and the rubric; logged here, untouched.
6. The same depth-mapping gap exists for `bc_depth` (back) and for hooded/lapel uppers' own priors —
   left in place deliberately to keep scope; the non-tees were required not to change.

## Re-running

GPU (pod per GPU_RUN.md): `drape.drape --inputs runs/inputs_texture --out runs/out_tee_fix --only <top>
--dump-every 50` (defaults are now hold-free; the band lives in each item's stored params; `--size XS|M|XL`
for the sweep, PoC pair via `--inputs runs/inputs`). Mac: `drape.panels`, `drape.bind`, `drape.collar`,
`drape.coverage --out <dir>` (exit ≠0 on any gate failure), `drape.sheet --out <dir>`, `drape.texture`,
`drape.export`, `viewer/build_manifest.py`, `drape.eval --passes 3`. Re-draping into an existing out dir
requires deleting that item's `pattern/` + `sim/` dirs and pruning its `timings.json` entries first —
`ensure_pattern` reuses a stale spec and coverage takes the first timings match.

## Verdict

**The shoulders are fixed, and the fix was the measurements, not the sim.** Every top and every sweep
size now covers both shoulder caps 100% in both poses with zero bare-patch centimetres — under gates that
provably fail the old "passing" run (black tee M reads 50% right-cap coverage there) — and the blind
reviewer answers "fabric covers both shoulders / no strap / wearable: yes" on all 22 pose-judgements. The
v9a neckband+ring-hold default that masked the defect is reverted; what remains committed is the body-yaml
datum fix, a listing-true stretch-on rib band, and a neckline prior that now cuts the depth it declares.
The honest miss: a crew neckline that *reads* round. 6 of 11 rows pass every frozen gate and 2 of 11 pass
the blind review outright, but only the knit hoodie passes both — the collarless tees all fail the
review's neckline question, and WWJD XL / Billabong / XL sweep still miss the neck-drop gate against
GarmentCode's fc_depth floor. That failure is reported as a failure, with the levers and their stopping
reasons documented above, rather than re-scoped into a pass.
