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

---

# Neckline round (branch anjelo/tee-neck)

Question: why does every collarless tee read as a shallow V in blind review, and does a fix survive the
frozen gates? Plus two side fixes: the black tee drafts cropped, and the contact sheets are speckled white.

## Root cause of the V: the rib band is cut straight

Neckline plots per top and sweep size: `runs/out/shots/tee_neck/neckline/<safe>.png`
(`python -m drape.neckline --out <run> [--sim]`, pattern space, no sim needed).

- **Not the neckline shape.** All five tees already use `CircleNeckHalf` front and back, and the Turtle
  collar cuts the torso with `CircleNeckHalf` whatever the params say (collars.py:138-143). The drafted
  torso neckline meets centre front 2.1-2.8° from horizontal, front and back, on every in-scope top and
  sweep size (target ≤5°). The crew rule is now explicit anyway: prompts/system.md names `CircleNeckHalf`,
  and `clamp_neckline`/`--reclamp` pin it for collarless crews.
- **The band.** Turtle cuts each band half as a straight rectangle (bands.py:6-32) and sews it to a
  neckline arc sweeping 120-125° (front) and 94-105° (back). A straight strip can only lie on that arc as
  a chord, so at centre front its tangent misses the neckline's by half the sweep: 59.8-62.7° front,
  47.1-52.6° back. The two chords meet at the CF seam as a notch. On the draped meshes the neck rim turns
  5-7° per step all the way round except at centre front: 85.8° on the tee-fix black tee M, the sharpest
  point of the ring.
- The blind reviewer, unprompted: "every failure is the same defect — a pointed centre-front notch/V ...
  The notch depth scales with garment size (deepest on sheets 3 and 10, the two widest cuts), which points
  at the neckline construction rather than the simulation."

## What was tried: two loops, then stopped

| loop | change | probe (black tee M / longsleeve M; frozen gates) |
|---|---|---|
| 1 (71256bc) | each band half recut as an arc concentric with its neckline: seam edge on the neckline's own radius, same arc length (stretch-on 0.85 kept), free edge concentric 2.5 cm inside | construction bug: band depth was read off the rectangle's diagonal (16.97 cm, clamped to 0.9R = 8.39 cm), so every half became an 8.4 cm triangle with a 1.7 cm free edge; the neck cinched (drop 1.3 cm, neck ring +504%, penetration 0.129%) |
| 2 (34396c5) | depth taken from the side edge: a true 2.5 cm arc band (free edge 40.5 cm against the straight band's 56.7); probed at stretch-on 0.85 and at 1.0 | 0.85: round, but neck ring +17.0/+19.4% (≤12) and drop 5.30/5.51 cm (prior 6.86-9.80); 1.0: ring +10.9/+12.4%, drop 6.69/7.21, and the notch is back (CF kink 65.6°/38.7° vs 23.9°/8.4° at 0.85) |
| stop (f58e64f) | loop budget spent; the arc band breaks two gates the M tees pass, so the straight rib band stays the shipped default | — |

Probe sheets: `runs/out/shots/tee_neck/ringband/arc085_*.jpg`, `arc100_*.jpg`, and
`loop1_bug_depop_954868283.jpg` (the cinch).

**The arc band is the fix the review asks for.** The round-3 reviewer saw the two 0.85 arc-band sheets
mixed in with the eight shipped sheets, anonymized, and passed both on all six questions in both poses:
"Sheets 8 and 9 are the only two with a clean round crew." Only two frozen gates block it. The neck ring is
measured against the band's free edge, which a curved band cuts 28% shorter than a straight one and then
stretches on; and the crew drop prior (7-10 cm) sits about 1.5 cm below where a round crew at the base of
the neck lands. Shipping it needs a decision on those two gates, which this branch may not make. To
re-enable it, restore `_ring_neckband` and its call in `build_pattern` from 34396c5.

Depth rule, declared before the re-drape: no width, band-ratio or sub-floor change. At the 0.3 floor the
drafted front drop is 0.3·bust_line + tan(shoulder_incl)·(half − width/2) = 13.6 cm (M) to 14.1 cm (WWJD
XL) against a 6.9-10.6 cm prior; the slope term alone is +7.3/+7.7 cm. Narrowing `collar.width` makes the
cut deeper (the slope term grows as width/2 shrinks) and the whole width prior moves it at most 0.7 cm.
The band ratio is shared by every Turtle tee, and the probes show it trades the notch against the drop.
So the large-neck neck_drop misses stay, documented below.

## Gate table (shipped: straight band + body-length prior)

Frozen gates, `drape/gates.json` byte-identical (sha256 aa04a7a5…9cf0), on the tee-neck re-drapes;
tee-fix value in brackets where it moved. Shoulder cap coverage is 100/100 in both poses on every row,
strap detector clean everywhere.

| top | armhole ≤5 | sleeve ≤3 / ΔLR | neck ring ≤12% | drop (prior) | pen ≤0.1 | sim s | gates | blind Q3 |
|---|---|---|---|---|---|---|---|---|
| WWJD tee XL | 9.82 [8.69] | 4.38 / 0.79 | +2.4 | 12.12 (7.42-10.6) [12.8] | 0.000 | 35.6≤47.8 | FAIL armhole, sleeve_hem, neck_drop | FAIL |
| black tee M | 3.37 | 0.54 / 0.15 | +3.1 | 8.89 (6.86-9.8) [9.5] | 0.010 | 27.5≤44.0 | **PASS** | FAIL |
| surf tee L | 3.04 | 1.67 / 0.12 | +2.9 | 9.08 (7.14-10.2) | 0.019 | 26.5≤43.3 | **PASS** | FAIL |
| longsleeve M | 2.67 | 1.06 / 0.14 | +2.5 | 8.67 (6.86-9.8) [8.2] | 0.045 | 36.5≤50.4 | **PASS** | FAIL |
| Billabong tee L | 4.27 | 1.72 / 0.01 | +2.3 | 10.21 (7.14-10.2) [10.8] | 0.000 | 30.8≤45.7 | FAIL neck_drop (by 0.01 cm) | FAIL |
| black tee XS (sweep) | 5.16 [5.37] | 2.81 / 0.09 | +3.5 | 8.04 | 0.086 [0.159] | 24.6≤44.0 | FAIL armhole | FAIL |
| black tee M (sweep) | 3.43 | 0.68 / 0.16 | +3.1 | 9.02 | 0.029 | 28.0≤44.0 | **PASS** | FAIL |
| black tee XL (sweep) | 7.47 [6.56] | 3.77 / 0.29 | +2.2 | 11.58 (6.86-9.8) [11.2] | 0.000 | 34.5≤44.0 | FAIL armhole, sleeve_hem, neck_drop | FAIL |
| arc band 0.85, black tee M (probe, not shipped) | 3.35 | 0.59 / 0.16 | **+17.0** | **5.30** | 0.029 | 27.4≤44.0 | FAIL neck_ring, neck_drop | **PASS all six** |
| arc band 0.85, longsleeve M (probe, not shipped) | 3.27 | 1.02 / 0.09 | **+19.4** | **5.51** | 0.084 | 36.5≤50.4 | FAIL neck_ring, neck_drop | **PASS all six** |

Hoodie M, flannel M and knit hoodie L were not re-drafted or re-draped; their params.json are
byte-identical to the start of the run (sha256 check), and re-measured on their old sims they read as
before (hoodie FAIL armhole 5.96, flannel PASS, knit hoodie PASS). XS penetration now passes
(0.159 → 0.086). The longer bodies pull the oversized cuts' armholes further out (WWJD 8.69 → 9.82,
XL sweep 6.56 → 7.47).

Before/after sheets per top: before `runs/out/shots/tee_fix/sheets_final/<safe>.jpg`, after
`runs/out/shots/tee_neck/sheets/<safe>.jpg` (sweep: `sweep_<size>_depop_954868283.jpg`).

## Blind review, round 3

Fresh reviewer, sheets (header cropped) and listing photos only, the six-question rubric; full text,
key and verbatim answers in [REVIEW_TEE.md](REVIEW_TEE.md) round 3. Summary table verbatim, with the key
the reviewer never saw in brackets:

| Sheet | Listing | Verdict |
|-------|---------|---------|
| 1 [surf L] | A | FAIL — Q3 (A, B) |
| 2 [black tee M sweep] | B | FAIL — Q3 (A, B) |
| 3 [WWJD XL] | C | FAIL — Q3 (A, B) |
| 4 [black tee M] | B | FAIL — Q3 (A, B) |
| 5 [black tee XS sweep] | B | FAIL — Q3 (A, B) |
| 6 [Billabong L] | D | FAIL — Q3 (A, B) |
| 7 [longsleeve M] | E | FAIL — Q3 (A, B) |
| 8 [arc band 0.85, longsleeve M] | E | PASS |
| 9 [arc band 0.85, black tee M] | B | PASS |
| 10 [black tee XL sweep] | B | FAIL — Q3 (A, B) |

Q1, Q2, Q4, Q5 and Q6 are yes on every sheet in both poses, including the XL sweep's sleeves (a Q2 fail in
round 2). The reviewer flagged sheets 1 and 9 as the closest calls at this tile resolution.

## Body length (hem)

`drape/size_body.py` holds tees and longsleeves to the size chart's body length ±3 cm (the chart already
had the column; it was dropped). HPS→hem on the front torso panel is
shirt.length·waist_line + tan(shoulder_incl)·(half − collar/2 − fb_diff), exact to 0.01 cm on all 8
drafted specs. The clamp runs in `ask()` and model-free in `--reclamp`, skips anything whose title, fit or
tags say crop/cropped, and acts only on category tee/longsleeve. For `--size` drafts (`drape.drape`,
`drape.pattern`) it re-clamps for the draft size in memory. New params_meta.json clamp lines:

| item | shirt.length | HPS→hem cm | chart |
|---|---|---|---|
| WWJD tee XL | 1.3 → 1.3912 | 65.09 → 69.00 | 72 |
| black tee M | 1.0 → 1.34667 | 50.15 → 65.00 | 68 |
| surf tee L | 1.3 → 1.3922 | 63.05 → 67.00 | 70 |
| longsleeve M | 1.3 → 1.35775 | 62.53 → 65.00 | 68 |
| Billabong tee L | 1.3 → 1.3754 | 63.77 → 67.00 | 70 |
| sweep XS / M / XL | 1.34667 / 1.34667 / 1.40412 | 63.85 / 65.00 / 69.00 | 64 / 68 / 72 |

Every clamp lands on the near band edge (chart − 3 cm), the smallest change that meets the prior.

## White specks

Not holes: the black tee's sim mesh has exactly 4 open boundary loops (hem 118, neckline 58, two cuffs
56), no non-manifold edges and no degenerate faces. The sheet renderer is a painter's algorithm that sorts
body and garment triangles together by mean depth; where cloth sits a few mm off the skin, a large body
triangle's mean depth beats the cloth in front of it and body grey shows through. Fix (sheet.py
`LIFT = 1.0`): the garment layer is pushed 1 cm toward the camera in the dressed tiles only; the cap tiles
are byte-stable. Against a z-buffer reference the body-grey pixels drop 73 → 0 (front), 202 → 61 (side),
182 → 5 (3/4) and 796 → 39 (shoulder) with the silhouette unchanged. Crops:
`runs/out/shots/tee_neck/specks/{before,after}_{front,shoulder,side}.png`. The web viewer has a real depth
buffer and never showed them (`viewer_front.png`, `viewer_closeup.png`), so export.py is untouched.

## Judge scores and viewer (eval --passes 3)

Texture-rubric means over 3 judge passes (claude-sonnet-5-5; these criteria don't score the neckline or
the hem), on the re-textured, re-exported GLBs:

| top | legacy | v2 now | tee-fix v2 |
|---|---|---|---|
| WWJD tee XL | 0.50 | 0.50 | 0.50 |
| black tee M | 1.00 | 2.00 | 1.67 |
| surf tee L | 1.13 | 1.53 | 1.80 |
| longsleeve M | 0.87 | 1.60 | 1.60 |
| Billabong tee L | 1.50 | 1.17 | 1.67 |
| **mean (5)** | 1.00 | **1.36** | 1.45 |

The difference is inside the judge's noise (per-item pass spread up to 0.5). Sheets:
`runs/out/shots/tee_neck/eval/<safe>_texture.jpg`. The viewer at `?out=runs/out_tee_fix` loads the new
GLB (`depop_954868283_draped.glb`, HTTP 200): `runs/out/shots/tee_neck/viewer_depop_954868283_{front,tq}.png`.
Its left "current pipeline" pane has no template-textured asset for this item, which is the page's one
console 404 and predates this branch.

## Vendor behaviour patched from gen3d/drape (vendor/ untouched)

No new patch ships. `_stretch_on_neckband` (Turtle band at 0.85) is unchanged. The arc band (34396c5,
not shipped) rewrote the drafted spec JSON after `pattern.serialize`; it never touched vendor code.

## Spend

GPU, two pods in turn (the first was replaced at the user's request mid-run), both A40 48GB Secure
EU-SE-1 at **$0.59/h**, no volume:

| pod | up | state | billed |
|---|---|---|---|
| 5g8e5lgpbek5kp | 01:12:59-01:49Z (36 min) | terminated | $0.262 so far (01:00 UTC bucket: $0.259 GPU + $0.003 disk, still settling) |
| xthfemifoc4lhm | 01:49:10-02:24Z (35.2 min) | stopped (EXITED; no volume, so nothing bills) | not posted yet; ≈$0.35 by uptime |

**≈$0.70 GPU in total, against the $8 cap.** Every sim ran in 24.6-42.7 s, inside its 2× v3 budget.
Claude: about $1.20 of judge passes ($0.603 for the recorded run, plus about the same for a first run
that crashed after judging on a relative `--shots` path). Parameter changes were model-free.

## What still fails

1. **Crew necks still read as a V**: Q3 fails on all 8 shipped sheets. The fix exists (arc band, 34396c5)
   and passes the blind review on both probed tees, but fails the frozen neck_ring and neck_drop gates
   there, so shipping it needs a decision on those two gates.
2. **neck_drop on large necks**: WWJD XL 12.12, Billabong L 10.21 (over by 0.01 cm), XL sweep 11.58 —
   the 0.3 depth floor plus GarmentCode's shoulder-slope term; no lever inside the rules reaches it.
3. **Oversized cuts**: armhole WWJD XL 9.82, XL sweep 7.47, XS 5.16; sleeve_hem WWJD 4.38, XL sweep 3.77.
   The longer bodies made the two armholes worse.
4. **Hem clamps sit exactly on the band edge** (chart − 3 cm). The listing photos read longer than that;
   a later chart edit or a narrower band flips them out.

## Re-running

As above, plus: `drape.params --inputs <set> --reclamp --only <safe>` now also clamps body length, and
`drape.neckline --out <run> [--sim]` measures the CF tangents and the draped CF kink.
