# T4 — placement + slide film for the tee-shoulder diagnosis

8 filmstrips (4 sims x front + top-down), shoulder close-up, orange = garment, blue = body.
Every panel is labelled `R` (mannequin's right) on the left edge and `L` (mannequin's left) on the
right edge — a conventional front view, you are facing the mannequin.

| sim | variant | item |
|---|---|---|
| `film_tc__depop_954868283` | tee-collar defaults (ring hold, stiff 4) | black tee M |
| `film_tc__depop_953525988` | tee-collar defaults | WWJD XL |
| `film_v3__depop_954868283` | plain v3 (`--neck-hold none --neck-stiff 1`) | black tee M |
| `film_v3__depop_953525988` | plain v3 | WWJD XL |

Frames 0,100,...,2300 plus the last dump (f2375 — the 2400-frame cap stops dumping at 2375).
Crop: 40 cm of body height centred on the acromion (y 119.1–159.1 cm), x ±32 cm.

Reproduce (from `gen3d/drape`, dumps already in `runs/film_tc` and `runs/film_v3`):

```
uv run --no-sync python -m drape.film strips --runs runs/film_tc runs/film_v3 --out film
uv run --no-sync python -m drape.film gaps   --runs runs/film_tc runs/film_v3
uv run --no-sync python -m drape.film slide  --runs runs/film_tc runs/film_v3
```

Sims were produced on the A40 pod with `--dump-every 25`, all four flock-wrapped on
`/workspace/seam/.gpu.lock`, into separate out dirs; all four exited rc=0 in ~47 s each.

## 1. What the film shows — the headline

**The tees do not slide off the shoulders. They are never on the shoulders.** At frame 0 the
boxmesh is a flat shell hanging below the shoulder line; the first simulated frames drop it
straight down. Neither variant ever lifts fabric onto the shoulder cap.

The tee-collar neckband + ring hold changes nothing about this. `film_tc` and `film_v3` are
visually near-identical through the whole 2375 frames — the hold keeps the *collar* up, the
shoulders are bare either way. Their frame-0 placement is byte-identical (section 3), as expected:
the neck hold is a sim constraint, not a placement change.

## 2. Slide annotation, per sim per side

Judged by eye from the strips, cross-checked by casting a vertical ray up from the body's acromion
through the garment mesh at every dump (`film slide`, stride 25 — finer than the strips' stride 100).
Eye and ray agree on every row.

| sim | side | shoulder fabric gone from | sleeve top below arm root from | by eye |
|---|---|---|---|---|
| film_tc black M | right | **f0 — never covered** | f0 | bare blue shoulder in every panel f0→f2375 |
| film_tc black M | left | f0, recovers, **covered at the end** (+0.63 cm) | f0 | orange over the outer shoulder from ~f100 on |
| film_tc WWJD XL | right | **f25, and stays bare** | f0 | both shoulders bare blue by f100, never recovers |
| film_tc WWJD XL | left | **f25, and stays bare** | f0 | as right — symmetric collapse to armpit level |
| film_v3 black M | right | **f0 — never covered** | f0 | identical to film_tc |
| film_v3 black M | left | f0, recovers, **covered at the end** (+0.68 cm) | f0 | identical to film_tc |
| film_v3 WWJD XL | right | **f25, and stays bare** | f0 | identical to film_tc |
| film_v3 WWJD XL | left | **f25, and stays bare** | f0 | identical to film_tc |

Notes on these numbers:

- **The sleeve answer is f0 on all eight rows.** The sleeve's top is already below the arm-root
  ring's top (y 142.46 cm) in the undraped boxmesh. There is no frame at which a sleeve "slides
  below" the arm root, because none starts above it.
- The XL's `f0` ray hit (+0.71 cm) is the undraped box shell's top edge passing over the acromion,
  not fabric resting on a shoulder — see the f0 panel. It is gone by f25.
- **The M's left/right asymmetry is real but is not a placement asymmetry**: frame 0 is
  near-symmetric (seam→acromion 7.78 left vs 7.93 right). One side happens to catch and the other
  does not. Treat it as sim-dynamics noise around a marginal contact, not as a left/right bug.
- The XL (bigger garment, larger armhole) fails on **both** sides and ends lower — the bigger the
  tee, the further it drops.

## 3. Frame-0 gap report (H3 — the placement question)

Body landmarks from `runs/bodies/wearer_masc_a45.obj`: acromion (topmost arm vertex, as
`collar.body_shoulders`) at ±(18.80, **144.09**, −1.08) cm; arm-root ring (arm-cap ring N_CAP−1,
24 verts, radius 5.60 cm) centroid ±(18.79, **138.50**, −0.80) cm, ring top y 142.46 cm.

Garment at frame 0 (`dump_f0`), shoulder seam = the front-to-back torso stitch adjoining the collar
edge, armhole = every sleeve↔torso stitch on that side. Vertical component is signed, negative =
garment below the body landmark.

| run | item | side | seam→acromion 3D | vert | seam **top** vs acromion | armhole ctr→arm root 3D | vert | dx | dz |
|---|---|---|---|---|---|---|---|---|---|
| film_tc | 954868283 (M) | left | 7.78 | −6.37 | **−3.50** | 9.55 | −8.90 | +1.34 | +3.20 |
| film_tc | 954868283 (M) | right | 7.93 | −7.13 | **−3.50** | 9.56 | −8.91 | −1.32 | +3.20 |
| film_tc | 953525988 (XL) | left | 7.82 | −6.44 | **−3.73** | 13.20 | −11.29 | +6.02 | +3.24 |
| film_tc | 953525988 (XL) | right | 7.79 | −6.79 | **−3.72** | 13.20 | −11.28 | −6.02 | +3.24 |
| film_v3 | 954868283 (M) | left | 7.78 | −6.37 | −3.50 | 9.55 | −8.90 | +1.34 | +3.20 |
| film_v3 | 954868283 (M) | right | 7.93 | −7.13 | −3.50 | 9.56 | −8.91 | −1.32 | +3.20 |
| film_v3 | 953525988 (XL) | left | 7.82 | −6.44 | −3.72 | 13.20 | −11.29 | +6.02 | +3.24 |
| film_v3 | 953525988 (XL) | right | 7.79 | −6.79 | −3.72 | 13.20 | −11.28 | −6.02 | +3.24 |

cm. dx is outboard-positive, dz is forward-positive. `film/frame0_gaps.json` has the raw values.

**Plain answer: the boxmesh does not start aligned to the body's shoulder anatomy. It starts
below it, on both items and both sides.**

- The shoulder seam's **nearest** point is ~7.8–7.9 cm from the acromion, 6.4–7.1 cm of that
  straight down. Even the seam's **highest** vertex is **3.5 cm (M) / 3.7 cm (XL) below** the
  acromion. No part of the shoulder seam starts at or above the shoulder point.
- The armhole ring's centroid starts **8.9 cm (M) / 11.3 cm (XL) below** the arm-root ring centre,
  and 1.3 cm (M) / 6.0 cm (XL) outboard and ~3.2 cm forward. The armhole is not around the arm
  root; it is hanging under it.
- Direction is the same everywhere: **down, slightly forward, and (XL) outboard.** Size scales the
  error — the XL is ~2.4 cm worse at the seam top and ~2.4 cm worse at the armhole.

So the sim is asked to settle a garment that begins with no shoulder contact at all. Gravity has
nothing to catch on, which is exactly what section 2 shows.

### The `*_vertex_labels.yaml` armhole key, and why the table does not use it

`left_armhole` / `right_armhole` in the labels yaml hold only **21–24** vertices with z strictly
negative — that is one panel's armhole edge (the back torso's, stitch 15 / 5), not the ring. Its
centroid sits 19.0 cm (M) / 21.1 cm (XL) from the arm-root centre, which overstates the gap because
the half-edge's centroid is pulled back and down. The table above uses the full ring assembled from
the spec's sleeve↔torso stitches (41 verts M / 47 XL) via `*_sim_segmentation.txt`. The
`left_collar` / `right_collar` keys are complete and are used as-is to identify the shoulder seam.

## 4. What is not established here

- **One ray, one point.** The coverage test casts a single vertical ray through the acromion. A tee
  covering the shoulder slightly inboard of the acromion would read as "bare". The strips are the
  check on this, and they agree, but the frame numbers inherit the limitation.
- **Dump resolution is 25 frames**; "f25" means "somewhere in 1–25". The strips are stride 100, so
  the f25 onsets come from the ray cast, not from the pictures.
- **Why the garment is placed low is not answered here.** This measures the frame-0 offset and its
  consequence; it does not locate the code that chooses the placement.
- The band in the stored params (Turtle 2.5 cm) is baked into both variants — `--neck-hold none
  --neck-stiff 1` reproduces plain v3 *behaviour*, not a band-free pattern.
- No claim is made about textures, panels or anything outside the shoulder crop.
