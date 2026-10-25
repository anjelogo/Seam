# T3 measurement audit — our body yaml vs GarmentCode's definitions

Hypothesis H1: keys in our GarmentCode body yaml are computed differently from how GarmentCode
defines them, so tee patterns draft wrong. **H1 is SUPPORTED.** Six keys disagreed with the
documented definition; the dominant one is `head_l`, which moved GarmentCode's whole vertical
datum 4.87 cm down the body.

`KEYS` (`drape/body.py:36-42`) holds **26** keys, not 27. All 26 are rowed below.

## Ground truth used

Prose alone is ambiguous, so every verdict is calibrated against the matched body/measurement
pair GarmentCode ships: `vendor/GarmentCode/assets/bodies/mean_all.obj` (metres) +
`mean_all.yaml` (cm) + `ggg_body_segmentation.json`. Sources, all inside `vendor/`:

- `docs/Body Measurements GarmentCode.pdf` — "GarmentCode Body Measurements / Field Explanation"
  table. Quoted below as **PDF**. (Text is a custom font cmap; decoded with a +29 codepoint shift.)
- `assets/bodies/body_params.py:12-39` — derived `_`-keys.
- `assets/bodies/f_smpl_average_A40.yaml`, `m_smpl_average_A40.yaml` — inline comments on the keys.
- `assets/bodies/mean_all_tpose.yaml` — the same body in a T-pose; the control for `arm_pose_angle`.
- Consumers: `assets/garment_programs/{tee,bodice,sleeves,base_classes}.py`,
  `pygarment/meshgen/garment.py`.

Two independent checks confirm `height - head_l` is the **nape (neck base) level** on `mean_all`:
its value 145.66 cm is exactly where the neck column starts (section half-width 9.2 cm, vs 6.0 cm
for the neck proper and 18 cm at the shoulder), and the girth at `nape - vert_bust_line` is
99.84 cm = the `bust` value in the yaml.

## The 26 keys

`ours` = `runs/bodies/wearer_masc_a45.yaml` (before this change). `fixed` = corrected export.

| key | GarmentCode definition (vendor quote + file:line) | how body.py computes it | ours | fixed | mean_all | agree? |
|---|---|---|---|---|---|---|
| arm_length | "Distance from shoulder to wrist (geodesic or Eucledean, those are close for this measurement)" — PDF | `body.py:147` shoulder_joint→wrist-ring centroid, Euclidean | 53.50 | 53.50 | 53.97 | **AGREES** |
| arm_pose_angle | "Specification of the used arm pose (shoulder joint), used for component alignment (e.g. sleeves). Assumes both arms have the same pose" — PDF; consumer `sleeves.py:339-340` `rotate_by(R.from_euler('XYZ',[0,0,body['arm_pose_angle']],degrees=True))`; control `mean_all_tpose.yaml:3` `arm_pose_angle: 0.0` | `body.py:148` `atan2(abs(dy),abs(dx))` = below-horizontal; `body.py:216` `90.0 - deg` | 45.00 | 45.00 | 45.48 | **AGREES** |
| armscye_depth | "Distance from the shoulder to the bottom of the underarm pit, measured on the back" — PDF; `f_smpl_average_A40.yaml` `armscye_depth: 15  # Nape of the Neck to armscye depth on the back`; `body_params.py:38-39` `_armscye_depth = armscye_depth + 2.5` | `body.py:149` was `sh_y - at["armpit"]` (armpit **station**, a lofting ring, not the pit) | 9.57 | **13.23** | 12.87 | **MISMATCH** — fixed |
| back_width | "Same as `waist_back_width`, but for bust circumferences. From one balance line to the other, measured from the back"; "Balance line = vertical line passing through the side of the body along the coronal plane" — PDF | `body.py:150` `_back_arc(bust)`; `_back_arc` (`body.py:73`) splits at the **max-x** points, not the coronal-plane crossings | 43.94 | 43.94 | 47.68 | **PARTIAL** — see open items |
| bum_points | "Distance between the two peak points of the bottom cheeks" — PDF | `body.py:151` `_rear_span(hip)` | 17.13 | 17.13 | 18.23 | **AGREES** |
| bust | "Circumference, measured parallel to the floor passing though bust_points" — PDF | `body.py:152` girth of the horizontal section at the lobe apex | 90.44 | 90.44 | 99.84 | **AGREES** |
| bust_line | "Geodesic distance from the shoulder level to the bust points (along waist_over_bust_line)" — PDF | `body.py:153` `_arc_down(apex, i_bust, sh_y)`, `sh_y` now the acromion | 18.38 | 18.41 | 25.69 | **AGREES** |
| bust_points | "Distance between the two peak points of the breasts" — PDF | `body.py:154` `2*abs(apex x)` at the bust ring | 21.56 | 21.56 | 16.95 | **AGREES** |
| crotch_hip_diff | "Vertical distance from hipline to the deepest part of the crotch" — PDF | `body.py:155` hip station − crotch | 11.00 | 11.00 | 8.81 | **AGREES** |
| head_l | "Nape of the neck to the top of the head, Eucledean distance" — PDF; used as a vertical datum by `tee.py:62`, `tee.py:113`, `bodice.py:86`, `bodice.py:167`, `sleeves.py:191-193`, `garment.py:281`, `garment.py:315`, `body_params.py:16` | `body.py:156` was `height - sh_y`, `sh_y` = **argmax-y vertex of the ARM mesh** (arm-cap apex), 4.87 cm below the neck base | 30.93 | **26.06** | 26.33 | **MISMATCH** — fixed |
| height | "Height of a person, from the feet to the top of the head" — PDF | `body.py:157` mesh y-extent | 175.00 | 175.00 | 171.99 | **AGREES** |
| hip_back_width | "Same as `waist_back_width` but for hips. From one balance line to the other, measured from the back" — PDF | `body.py:158` `_back_arc(hip)` | 47.99 | 47.99 | 54.82 | **PARTIAL** — same balance-line caveat |
| hip_inclination | "Waist to hip angle measured on the body side. 0 hip inlincation corresponds to completely vertical body side" — PDF; `body_params.py:32-33` halves it | `body.py:159-160` atan2 of the hip/waist max-x step over the rise | 15.19 | 15.19 | 9.86 | **AGREES** |
| hips | "Circumference, measured parallel to the floor passing passes though bum_points" — PDF | `body.py:161` girth at the hip station | 92.87 | 92.87 | 103.48 | **AGREES** |
| hips_line | "Vertical distance from the waistline level to hip circumference line level (hipline)" — PDF | `body.py:162` waist station − hip station | 14.00 | 14.00 | 23.48 | **AGREES** |
| leg_circ | "Circumference of the thickest part of a thigh (on one leg)" — PDF | `body.py:163` girth of the leg ring at the crotch level | 52.26 | 52.26 | 60.20 | **AGREES** |
| neck_w | "Approximate width of the neck base, measured from the back from one balance line to the other" — PDF; consumers `garment.py:292`/`garment.py:303` `neck_w - 2`, attach at `±neck_w/2`; `bodice.py:235` `min_w = body['neck_w']` | `body.py:164` chord `2*max x` of the neckbase ring | 12.40 | 12.40 | 18.93 | **AGREES (formula)** — but see the collar-attach finding |
| shoulder_incl | "Inclination of the shoulder line (angle between the line from the neck base to the end of a collarbone along coronal plane and a horizontal plane)" — PDF; `body_params.py:34-35`; consumers `tee.py:32`, `tee.py:89`, `bodice.py:26`, `sleeves.py:117` | `body.py:165` atan2 from the neck-base max-x point to the shoulder point; the shoulder point is now the acromion, not the arm cap | 21.99 | **21.03** | 21.68 | **MISMATCH** (endpoint) — fixed |
| shoulder_w | "Distance from the furthest left end of the left collarbone to the furthest right end of the right collarbone" — PDF; `body_params.py:19-22` `_base_sleeve_balance = shoulder_w - 2`; consumers `sleeves.py:189-193`, `base_classes.py:37`, `tee.py:65`, `tee.py:116`, `bodice.py:30`/`:36`/`:58`/`:104`, `bodice.py:234` | `body.py:166` was `2 * x` of the **arm-cap apex vertex**, which moves with the arm pose | 36.50 | **37.58** | 36.46 | **MISMATCH** — fixed |
| underbust | "Circumference, measured parallel to the floor passing right below the bust" — PDF | `body.py:167` girth at the underbust station | 82.46 | 82.46 | 86.25 | **AGREES** |
| vert_bust_line | "Vertical distance from the nape of the neck to bustline that marks bust circumference" — PDF; `body_params.py:25-29` `_bust_line = 2/3*vert_bust_line + 1/3*bust_line` | `body.py:168` was `sh_y - y_bust` (arm-cap apex datum) | 17.57 | **22.44** | 21.14 | **MISMATCH** — fixed |
| waist | "Circumference, ~middle between ribs and hip bones" — PDF | `body.py:169` girth at the waist station | 75.17 | 75.17 | 84.33 | **AGREES** |
| waist_back_width | "Length of the 'back' part of the waist. From the balance line on one side to the balance line on the other" — PDF | `body.py:170` `_back_arc(waist)` | 37.22 | 37.22 | 39.14 | **PARTIAL** — same balance-line caveat |
| waist_line | "Nape of the neck to waist (on the back), preferrably measures as geodesic distance on the body surface" — PDF; `f_smpl_average_A40.yaml` `waist_line: 36   # Nape of the Neck to waist (on the back)`; `body_params.py:15-16` `_waist_level = height - head_l - waist_line` | `body.py:171` was a **vertical** drop from the arm-cap apex; now the geodesic down the trunk's back column from the nape | 37.57 | **42.83** | 36.89 | **MISMATCH** — fixed |
| waist_over_bust_line | "The vertical line passing through a bust point, measured from the neck base (on the balance line) to the waistline from the front over the bust. Follows the convex hull of the geodesic measurement, similar to the tailor's tape measure" — PDF; consumer `bodice.py:31` | `body.py:173` surface arc up the bust-apex column to the shoulder, then vertical to the nape (the "convex hull" part, where the tape leaves the body) | 38.75 | **43.62** | 40.56 | **MISMATCH** (datum) — fixed |
| wrist | "Circumference, thinnest part of the arm at the root of the hand" — PDF | `body.py:174` girth of the wrist ring | 17.89 | 17.89 | 16.59 | **AGREES** |

## Deep-dive verdicts

**shoulder_w — MISMATCH, 1.08 cm too NARROW (36.50 → 37.58).** Not too wide, as suspected.
`body.py` took the argmax-y vertex of the arm mesh. `params.py:131-132` states the construction:
`"shoulder_joint": [torso[5,1], torso[5,0] - arm[0,1], torso[5,4]]` with the comment *"dropped by
the root radius, the arm cap's top meets the shoulder ring's widest point: no step either way"* —
so the acromion **is** the shoulder ring's widest point, 18.790 cm. The arm cap is a discretised
hemisphere whose topmost *vertex* lands at 18.251 cm and **moves with `ARM_ANGLE`** (its pole sits
at `j - r0*u`), making a body measurement pose-dependent. On `mean_all` the old formula gives
35.92 vs the true 36.46, so it is only a loose proxy even on a 45° body. Fixed to the trunk
shoulder ring; now pose-free.

**arm_pose_angle — AGREES.** Convention settled empirically, not from prose: `mean_all_tpose.yaml`
(arms horizontal) is `0.0` while `mean_all.yaml` (A-pose) is `45.483`, so the angle is measured
**below the horizontal plane at the shoulder joint** — a from-vertical reading would make the
T-pose 90. Measuring the arm axis on the meshes confirms it: T-pose 3.3° below horizontal (yaml
0.0), A-pose 48.9° (yaml 45.5). `sleeves.py:339-340` then rotates the sleeve by that angle about
Z, and the sleeve is built extending horizontally — consistent with 0 = T-pose. So:
`body.py:148` `atan2(abs(dy),abs(dx))` is the right convention (the unposed 20°-from-vertical body
correctly yields 70.0), and the `90.0 - deg` overwrite at `body.py:216` is the correct
from-vertical→below-horizontal conversion. **`wearer_masc_a45.yaml`'s 45.0 does correctly describe
the simmed 45°-from-vertical pose**, and the 90-deg overwrite is right. No change made.
(At 45° both conventions coincide; the `a30` body is the one that would expose an error, and
`90-30 = 60` is right there too.) Keeping the posed export's other keys from the unposed body also
matches GarmentCode, whose `mean_all.yaml` and `mean_all_tpose.yaml` differ **only** in this key.

**armscye_depth — MISMATCH, 3.65 cm too SHALLOW (9.57 → 13.23).** `body.py` used `at["armpit"]`,
the armpit *station* — one of the 8 torso cross-section heights used to loft the trunk
(`params.py:5`), not a claim about where the pit is. The real underarm pit is where the arm
surface enters the trunk surface; on our unposed mannequin that is y=130.87 cm, 3.63 cm below the
station at 134.50. The PDF's "from the shoulder" reading beats the `f_smpl` comment's "nape of the
neck" reading on GarmentCode's own numbers: on `mean_all` the true junction pit (lowest vertex on
the body/arm segment boundary) is y=127.96, giving acromion−pit = 14.25 and nape−pit = 17.70,
against a stated 12.87. "Measured on the back", where the crease is higher than the deepest point,
accounts for the remaining gap. Fixed to acromion − pit.

**shoulder_incl — MISMATCH (endpoint), −0.96° (21.99 → 21.03).** The formula shape already matched
the PDF; only its outboard endpoint was the arm cap instead of the collarbone end. Cross-checked
on `mean_all`: neck-base-section max-x (0.0922) → acromion (0.1823, 1.4221) gives 20.99° against a
stated 21.678°, while every other neck-x candidate lands at 15.8–18.7°.

**neck_w — formula AGREES, but the value breaks the sim's collar attachment.** Calibration on
`mean_all` is decisive for the *formula*: at the nape level the chord is 18.43 vs the stated 18.93,
while the back arc is 20.38 and the coronal-plane arc 29.39 — so `neck_w` is the **chord**, which
is what `body.py:164` computes. **I did not change it.** But the value is honestly out of family:
12.40 vs 18.93. That is our mannequin's shape, not a formula bug — `mean_all`'s neck *tube* chord
is 11.95–12.07 cm, essentially identical to ours, and GarmentCode's 18.93 comes from measuring at
a flared nape that our trunk spline does not have (it tapers from 18.79 cm half-width at the
shoulder to 6.20 cm at the neckbase ring in 4.84 cm of height). The consequence is concrete:
`garment.py:292-306` pins the collar's side vertices at `±(neck_w/2 - 1)` = **±5.20 cm**, while our
neck half-width is 6.20 cm — the attachment target is **1.0 cm inside the neck surface**, fighting
the body collision. On `mean_all` the same formula gives ±8.47 cm against a 6.0 cm neck, i.e.
2.5 cm clear. This is a strong candidate for the collar misbehaviour that v9a's neckband + ring-hold
masked. Inflating `neck_w` to make the number look right would be gaming the metric; the real fix
is either the mannequin's neck-base flare or an explicit attach offset, and it needs a decision.

**back_width / waist_back_width / hip_back_width — PARTIAL, unresolved, left unchanged.** The PDF
defines the balance line as the "vertical line passing through the side of the body along the
coronal plane"; `_back_arc` (`body.py:71-75`) splits the section at its max-x points instead. On
`mean_all` neither convention reproduces the stated numbers cleanly (back_width 47.68 vs max-x
44.13 and coronal 50.24; waist_back_width 39.14 vs 41.75 and 40.62 — the errors point in opposite
directions), and my section levels there are themselves derived, so the calibration cannot decide
it. On our body the two conventions differ by 1.32 cm at the bust and 0.00 cm at the waist. Not
the tee-slide cause; flagged rather than guessed at.

**bust_line / waist_line / vert_bust_line / waist_over_bust_line — all shared the `head_l` datum
bug.** `vert_bust_line` is confirmed vertical-from-nape (girth at `nape - vert_bust_line` on
`mean_all` = 99.84 = its `bust`). `waist_line` is confirmed geodesic: `nape - waist_line` on
`mean_all` lands at y=108.77, 2.5 cm *below* the true minimum-girth waist at y≈111.3, exactly the
excess a curved back adds over a vertical drop. `bust_line` is the one key in this family whose
datum is correctly the *shoulder* level, not the nape, per the PDF — so it barely moved (+0.03).

## Old vs new, per key

Only 8 keys move. Key set is unchanged and still diffs empty against `mean_all.yaml`.

| key | old | new | delta | mean_all |
|---|---|---|---|---|
| armscye_depth | 9.5740 | 13.2285 | +3.6545 | 12.8679 |
| bust_line | 18.3829 | 18.4110 | +0.0281 | 25.6947 |
| head_l | 30.9260 | 26.0600 | **−4.8660** | 26.3262 |
| shoulder_incl | 21.9879 | 21.0284 | −0.9595 | 21.6777 |
| shoulder_w | 36.5022 | 37.5800 | +1.0778 | 36.4568 |
| vert_bust_line | 17.5740 | 22.4400 | +4.8660 | 21.1388 |
| waist_line | 37.5740 | 42.8259 | +5.2519 | 36.8913 |
| waist_over_bust_line | 38.7498 | 43.6179 | +4.8681 | 40.5603 |

The other 18 keys are bit-identical.

## What this does to the drafted tee

Frame-0 boxmesh of the black tee M (`depop_954868283`, `runs/inputs_texture`), drafted on each
body and rendered over it — no sim was run.

| body | garment top | vs true neck base (148.94 ours / 145.66 mean_all) |
|---|---|---|
| `wearer_masc_a45` (before) | 147.07 | **−1.87 cm — the shoulder seam lands below the neck base** |
| `wearer_masc_audit` (after) | 151.94 | **+3.00 cm** |
| `mean_all` (GarmentCode) | 148.66 | **+3.00 cm** |

GarmentCode always places the garment's neck point 3.00 cm above where the yaml says the nape is.
Our old yaml put the nape 4.87 cm too low, so the tee was drafted with its shoulder seam on the
slope of the neck taper with nothing under it to sit on. After the fix our body reproduces
`mean_all`'s +3.00 cm exactly. This is the mechanism behind the tee sliding off the shoulders.

## Downstream callers of the changed keys

Ours (none edited):
- `drape/params.py:174-186` `bust_line()` mirrors `body_params.py:25-29`
  (`2/3*vert_bust_line + 1/3*bust_line`); used at `params.py:210`, `params.py:418`,
  `params.py:481`. **`vert_bust_line` +4.87 moves this from 17.84 to 21.09 cm**, so the collar- and
  length-clamping in `params.py` shifts. Re-running the `params.py` reclamp is likely needed.
- `drape/size_body.py:47` scales `shoulder_w` by `k_bust`, so the `size_top_*` bodies inherit the
  +1.08 cm; they are rebuilt from the wearer, not edited here.

Vendor consumers of the changed keys (read-only): `tee.py:32`/`:62`/`:65`/`:89`/`:113`/`:116`,
`bodice.py:26`/`:30`/`:36`/`:48`/`:58`/`:86`/`:100`/`:104`/`:116`/`:142`/`:167`/`:225`/`:234-235`/`:245`/`:254`/`:261`/`:362-363`,
`sleeves.py:117`/`:172`/`:189-193`/`:215`/`:218`, `base_classes.py:37`,
`garment.py:281`/`:292`/`:303`/`:315`, `body_params.py:15-39`.

## Verification

- `drape.body` export run twice; the two `wearer_masc_audit.yaml` files are byte-identical.
- Key set of the corrected export vs `mean_all.yaml`: symmetric difference empty.
- No sim was run; renders are frame-0 boxmeshes only.
- `runs/bodies/*` existing bodies were not overwritten; the corrected pair is exported under the
  scratch names `wearer_masc_audit_base` (unposed) and `wearer_masc_audit` (a45).

## Open items (not fixed — need a decision)

1. **`neck_w` 12.40 vs 18.93** puts the sim's collar attachment 1 cm inside our neck. Mannequin
   shape or an attach-offset change, not a measurement fix.
2. **Balance-line convention** for the three `*_back_width` keys is unresolved; worth ±1.3 cm at
   the bust.
3. **`armscye_depth` is pose-sensitive** on our mannequin: the pit is 13.23 cm below the acromion
   at the 20° measuring pose but 10.92 cm at the 45° sim pose. We measure unposed (as GarmentCode
   does), but GarmentCode's canonical measuring pose is itself 45°, matching its sim pose; ours is
   the 20° web pose.
4. `waist_over_bust_line` uses the bust-apex column for its surface part; the PDF's "from the neck
   base (on the balance line)" suggests a side-of-neck start. Datum is fixed, path is not.
