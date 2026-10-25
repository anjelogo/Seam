# T1 control: tees on GarmentCode's own mean body

Splits "our body/measurements are wrong" (H1/H2) from "our params/placement are wrong" (H3/H4) by draping the
three tees on GarmentCode's own mean body with stock upstream behaviour and no Seam neckband.

## What was run

Seam's tee behaviour was neutralised three ways, with no shared code touched:

- **No neckband.** `runs/inputs_control/` is the 3 tees' `params.json` with `collar.component.style` back to
  `null` and `depth` back to `7` (the vendor `assets/design_params/t-shirt.yaml` default). The resulting specs
  have 8 panels; the shipped v9a specs have 12 (`left/right_collar_front/back`). Band confirmed gone.
- **Stock sim.** `--neck-hold none --hold off`, no `--preset`, no `--material`: upstream collar attachment,
  released at frame 400, upstream material. Direct `--spec/--name` mode, so `NECK_DEFAULT` and the posed-wearer
  path in the item loop never run — the sim body is `mean_all` exactly as staged, never re-posed or swapped.
- **Right segmentation.** `runs/bodies/ggg_body_segmentation.json` indexes our 9 630-vertex mannequin;
  `mean_all.obj` has 23 752 vertices. The sim reads the segmentation from `bodies_default_path` in `./system.json`,
  so the runs use `runs/out_control_tools/` as CWD with its own `system.json` → `bodies/` holding `mean_all.{obj,yaml}`
  plus the vendor's matching `assets/bodies/ggg_body_segmentation.json`. Panel assignment then prints
  `left_sleeve_f:left_arm` etc., and all 7 sims report 0 body collisions.

`mean_all.yaml` is `arm_pose_angle: 45.483`, within 0.5° of the `size_top_*_a45` bodies the as-cut patterns were
drafted on, so no re-posing was needed. 7 sims on the A40 under `flock /workspace/seam/.gpu.lock`, 11–19 s each,
no fails, converging 408–781 frames (all past the frame-400 attachment release).

## Metrics

`python -m drape.collar --out runs/out_control_*` exits `no tops` — its CLI needs `panels.json` and
`glb/bind_report.json` from the export/bind stages this control skips. `runs/out_control_tools/metrics.py`
therefore calls collar.py's own `obj_mesh`, `neck_ring`, `ring_metrics` and `shoulder_heights`, with the body
shoulder points computed by collar.py's rule (topmost vertex of each arm region) on `mean_all.obj` using the
vendor segmentation: **left (x +17.96, y 142.21), right (x −18.25, y 141.69)**, mean 141.95 cm.
Sidecars: `runs/out_control_{asis,gcdefault,recut}/collar_metrics.json`.

`ring − shoulder` is the neck ring's top above the body's mean shoulder height. The sidecars also carry a
`neck_ring_rest` / `neck_ring_delta` against the pre-sim boxmesh; that boxmesh is the wide box placement around
the body, not a pattern-space neckline, so its ~−100 cm circumference delta only says the sim closed the
placement onto the neck. Don't read it as neckline slack.

| run | pattern cut on | shoulder err L/R (cm) | ring top (cm) | ring − shoulder | ring circ (cm) | frames | shoulders covered |
| --- | --- | --- | --- | --- | --- | --- | --- |
| asis WWJD XL | size_top_XL_a45 | **+1.03 / +1.05** | 146.55 | +4.60 | 85.68 | 444 | **yes** |
| asis black M | size_top_M_a45 | **+0.86 / +1.11** | 146.81 | +4.86 | 74.08 | 408 | **yes** |
| asis surf L | size_top_L_a45 | **+1.02 / +1.13** | 146.69 | +4.74 | 75.96 | 409 | **yes** |
| gcdefault t-shirt.yaml | mean_all | **+1.06 / +1.20** | 145.90 | +3.95 | 71.62 | 411 | **yes** |
| recut WWJD XL | mean_all | **+1.00 / +1.12** | 145.68 | +3.73 | 82.62 | 781 | **yes** |
| recut black M | mean_all | **+1.06 / +1.16** | 146.00 | +4.05 | 77.22 | 423 | **yes** |
| recut surf L | mean_all | **+1.08 / +1.18** | 145.87 | +3.92 | 75.66 | 412 | **yes** |

Renders: `<group>__<name>__{front,three_quarter,top}.jpg`, body blue-grey / garment orange on flat grey.
Eyeball verdict is the same in all 7: front view shows orange fabric from shoulder point to shoulder point with
the sleeve cap over the deltoid; the top-down shows the neck opening ringing the neck with the collar edge
behind and in front of it, not pooled on the chest. No run shows a bare shoulder. Every run spreads
left/right within 0.34 cm, and the Seam tees are indistinguishable from GarmentCode's own default tee.

## License

`mean_all.{obj,yaml}` comes from `vendor/GarmentCode`, which is MIT (© 2024 Maria Korosteleva). Its
`assets/bodies/Readme.md` splits the folder: models with `smpl` in the name derive from SMPL (CC BY 4.0, and the
repo notes it cannot ship the full SMPL-derived shape set), while models *without* `smpl` — `mean_all` included —
are GarmentCode's own body model from [GarmentMeasurements](https://github.com/mbotsch/GarmentMeasurements).
So `mean_all` carries no SMPL restriction and is fine to use for this diagnosis under MIT with attribution; if it
were ever to ship in a product rather than a diagnostic, check the GarmentMeasurements repo's own terms first.

## Verdict: H1/H2 — our body, not our params

**The tees are fine on GarmentCode's body.** All three, cut from the shipped Claude params with only the v9a
neckband removed and draped with stock upstream attachment behaviour, land +0.86…+1.20 cm above `mean_all`'s
shoulder points — i.e. one fabric thickness on top of the shoulder — with the neck ring ~4 cm above shoulder
height and zero body collisions. GarmentCode's own default t-shirt on the same body scores +1.06/+1.20, inside
that same band: our params are not distinguishable from upstream's. The as-cut row matters most: those patterns
were drafted against *our* size bodies (`size_top_*_a45`, carrying our measurements) and they still sit correctly
once placed on GarmentCode's mesh — so neither the design params (H3) nor the drafting/placement (H4) is what
drops a tee 5–12 cm low on our mannequin (`RESULTS_TEE_COLLAR.md:145`). What changed between the two experiments
is the body mesh, which points the fix at our mannequin's shoulder geometry (H1) over the measurements that feed
the cut (H2), since those measurements were in play here and caused no harm.

**Limitation.** This control did not re-run the broken case: there is no sim here with these same stock flags on
`wearer_masc_a45`. The 5–12 cm baseline it is compared against (v3) ran with `--hold on` and the material presets.
The cheapest next step is one such run per tee — the control's exact flags, our body — which would isolate the
mannequin from the sim settings outright.
