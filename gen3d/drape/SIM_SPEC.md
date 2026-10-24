# Cloth sim behaviour specification

## 0. Header

**Purpose.** This document specifies, in behaviour only, every simulation feature that
`pygarment`'s draping stage depends on, so that a Newton backend can be written without anyone
reading the non-commercial sim fork. It is the sole input for implementing the engine side of the
port: the frame loop, the model construction, the solver step, the counters, and the parameters with
the exact defaults `pygarment` passes.

**Clean-room notice.** This is a behaviour specification written from reading the fork; it contains
no fork code. No code of any language appears here — no kernel bodies, no pseudocode, no
variable-by-variable transcriptions, and no fork-internal kernel or helper names. Public API names
are used where `pygarment` itself calls them, because those names are the interface the port must
provide. Where a feature implements a published method, the method is named and cited and only the
fork's *deviation* from it is described in words. Numeric rules are stated as observable behaviour in
standard notation. **This is licensing hygiene, not legal advice.**

**Commits pinned.**

| Component | Commit |
| --- | --- |
| Sim fork (`NvidiaWarp-GarmentCode`, fork of NVIDIA Warp v1.0.0-beta.6) | `63baf6855efdd89b2834b74640f84b3bb0d86b50` |
| `GarmentCode` / `pygarment` (MIT) | `d449629979028123a5c4dc9e732a2ec19b7fce31` |

**Reference works cited in place of describing fork code.**

- **XPBD** — Macklin, Müller, Chentanez 2016, *XPBD: Position-Based Simulation of Compliant
  Constrained Dynamics*. The compliance-and-damping form of the distance, bending and attachment
  constraints is this method unmodified.
- **PBD** — Müller, Heidelberger, Hennix, Ratcliff 2007, *Position Based Dynamics*. The
  predict-then-project-then-derive-velocity frame structure.
- **Cloth collisions** — Bridson, Fedkiw, Anderson 2002, *Robust Treatment of Collisions, Contact and
  Friction for Cloth Animation*; Provot 1997, *Collision and Self-Collision Handling in Cloth Model
  Dedicated to Design Garments*. The point–triangle / edge–edge decomposition and velocity limiting.
- **Predictive contacts** — Lewin, *Cloth Self Collision with Predictive Contacts*, GDC 2018. The
  "project one step forward, create the constraint only if the pair will come close" rule used by both
  self-contact passes. The fork's own comments point at this method and at a public write-up of the
  same technique.
- **GarmentCode** — Korosteleva & Sorkine-Hornung 2023, SIGGRAPH Asia. The pattern stage and the
  panel labels this spec consumes.
- **GarmentCodeData** — Korosteleva et al. 2024, ECCV (arXiv:2405.17609). **§3.4 "Draping"** is the
  authority for the draping design; its two named paragraphs **"Draping setup"** and **"Resolving
  initial collisions"** describe, respectively, the stitch-by-rest-length scheme with gravity-free
  start and static-equilibrium test, and the global piercing-edge survey plus the body-part drag
  constraint. **§3.1 "Overview"** places draping as the third pipeline step. The **supplemental
  material, Appendix C "Mesh generation"**, describes the box mesh and the retention of original edge
  lengths that this spec's stitching behaviour relies on.

**One discrepancy worth recording up front.** GarmentCodeData §3.4 states a static-equilibrium
threshold of 0.04 cm; the shipped configuration file uses 0.03 cm. The configuration file is what
actually runs, so this spec uses 0.03 cm and flags the difference.

---

## 1. Conventions

### 1.1 Units

| Quantity | Unit | Notes |
| --- | --- | --- |
| Length | centimetre | The garment box mesh is authored in centimetres and is **not** rescaled. |
| Time | second | |
| Mass | arbitrary, consistent with area × density | Per-particle mass accumulates as density × triangle rest area ÷ 3 from each incident triangle. With `fabric_density` 1.0 a particle's mass is numerically one third of its incident rest area in square centimetres. |
| Angle | radian internally | Bending rest angles are radians. `pygarment` supplies body measurement angles in degrees and converts. |

### 1.2 Up axis, body scale, shift

- **Up axis is +Y.** The model builder's up vector is +Y and gravity, when enabled, points along −Y.
- **Body scale is ×100.** The body mesh is loaded from an OBJ authored in metres and every vertex is
  multiplied by 100, putting it in centimetres to match the garment.
- **Y-shift.** After scaling, the minimum Y over all body vertices is inspected. If it is negative,
  the absolute value of that minimum is added to the Y of **every body vertex and every cloth
  vertex**, so the lowest point of the body sits at Y = 0. If the minimum is already at or above
  zero, no shift is applied. The shift is a single scalar shared by body and garment, so their
  relative placement is preserved exactly.
- **No rotation.** Both the garment and the body are placed with an identity rotation at the origin.
  The garment's placement comes entirely from the pattern's own 3D panel placement.

### 1.3 Gravity, and when it turns on

- The model is built with **gravity zero**. Frames 0 through `zero_gravity_steps − 1` therefore run
  with no gravity at all; this is the window in which the stitching springs pull the panels together
  (GarmentCodeData §3.4, "Draping setup").
- At the **first frame whose index equals `zero_gravity_steps`**, gravity is set to a downward vector
  of magnitude **9.81 per second squared in scene units** and stays on for the rest of the sim.
- **Critical unit consequence.** The scene is in centimetres and the gravity constant is the
  number 9.81, so the effective acceleration is 9.81 cm/s², which is **one hundredth of earth
  gravity at that scale**. This is not a bug to fix — every stiffness, damping and velocity cap in
  the configuration is balanced against this weak gravity. A port that works in metres, or that
  "corrects" gravity to 981 cm/s², will not reproduce any of the baselines in §8. Reproduce the
  number in the same unit convention.
- Gravity is applied **only to particles with non-zero inverse mass**. A particle pinned to infinite
  mass receives no gravitational acceleration.
- `zero_gravity_steps` default is **10** as `pygarment` ships it (the config class's own fallback,
  used only if the key is absent, is 5).

### 1.4 Rates

| Name | Value | Source |
| --- | --- | --- |
| Frame rate | 60 frames per second | Config class constant |
| Substeps per frame | 10 | Config class constant |
| Solver timestep | one six-hundredth of a second (≈ 1.6667 ms) | Frame period divided by substeps |
| Collision-detection timestep | one sixtieth of a second | The **full frame period** — see §2.2 |

The two timesteps differ by a factor of ten and this is deliberate. Collision detection runs once
per frame and is handed the whole frame period so its forward prediction looks a full frame ahead;
the solver then runs ten times with the short step.

### 1.5 Integrator defaults

`pygarment` constructs the XPBD integrator **with no arguments**. The resulting settings are:

| Setting | Value as constructed | Upstream Warp 1.0.0-beta.6 default | Relevant here |
| --- | --- | --- | --- |
| Solver iterations per substep | **1** | 2 | Yes — the fork lowered this, on the stated reasoning that more than one is unnecessary when substepping |
| Soft-body relaxation | 0.9 | 0.9 | No (no tetrahedra) |
| Soft-contact relaxation | **0.9** | 0.9 | Yes — scales body-contact and ground-contact corrections |
| Joint linear relaxation | 0.7 | 0.7 | No (no joints) |
| Joint angular relaxation | 0.4 | 0.4 | No (no joints) |
| Rigid-contact relaxation | 0.8 | 0.8 | No (no rigid bodies) |
| Rigid-contact constraint weighting | enabled | enabled | No |
| Angular damping | 0.0 | 0.0 | No |
| Restitution | **disabled** | disabled | Yes — the restitution passes never run |

Because iterations is 1, every constraint in the solve is visited exactly once per substep, so ten
times per frame. **A port must not silently use a higher iteration count**: several constraints in
§4 are tuned as hard single-shot projections and behave differently when iterated.

### 1.6 When the per-frame GPU graph is re-captured

On a CUDA device the whole frame — one collision-detection pass plus the ten substeps — is captured
once into a replayable graph and then replayed each frame. The graph is **captured at construction**
and **re-captured** at exactly these four moments, because each changes which kernels the frame must
launch or which host-side values they close over:

1. At the frame where gravity turns on (`zero_gravity_steps`).
2. At **every** body-smoothing frame, if body smoothing is enabled.
3. At the frame where the attachment constraint is released (`attachment_frames`).
4. Never otherwise — in particular, not when contact counts change.

On a non-CUDA device no graph is used and the frame's kernels are launched directly. The observable
behaviour is identical; only the launch mechanism differs.

**Port requirement.** Whatever replay or compilation caching the Newton backend uses, it must be
invalidated at those three event frames. A stale capture at the gravity frame is the single easiest
way to produce a sim that never falls.

---

## 2. Frame loop

This section describes the behaviour of `pygarment`'s simulation driver together with its cloth
object. **The driver file carries an NVIDIA proprietary copyright header, so implementers are
forbidden to open it.** Everything it does that matters is therefore specified here, under the same
no-code rules.

### 2.1 Outer sequence

1. A simulation-config object is built from the properties dictionary. Every value it exposes is
   either read from the `sim.config` section or filled from its own fallback. §6 quotes both.
2. The cloth object is constructed. Construction performs **all** of the model building in §3 and
   leaves a finalised model, two state buffers, an integrator, and (on CUDA) a captured graph.
3. The frame loop runs for frame indices 0 up to `max_sim_steps − 1` inclusive.
4. On loop exit — normal, static, or by exception — a post-processing block always runs: it records
   stats, counts intersections, writes the output mesh, and renders images.

### 2.2 What one frame does

Each frame, in this order:

1. **Particle hash grid rebuild** — only if particle–particle collisions are enabled. The grid is
   rebuilt over current particle positions with a cell size of twice the maximum particle radius.
   With the shipped configuration this is **off**, so the grid is never rebuilt.
2. **Gravity switch** — if this frame index equals `zero_gravity_steps`, gravity is set as in §1.3
   and the graph is re-captured.
3. **Body-smoothing step** — if body smoothing is enabled and this frame index is in the
   precomputed smoothing frame list, the next body vertex set is applied to the body collider (§3.7)
   and the graph is re-captured.
4. **Attachment release** — if the attachment constraint is currently on and this frame index is
   greater than or equal to `attachment_frames`, the attachment constraint is switched **off** and
   the graph is re-captured. There is no ramp-down; the constraint simply stops being applied from
   this frame onward, and is never re-enabled.
5. **The frame itself**, which is:
   - **One collision-detection pass** (§4.2), given the **full frame period** as its timestep.
   - **Then ten substeps.** Each substep clears particle and body forces, runs one integrator step
     with the short timestep, and swaps the two state buffers.

   So collision detection is **once per frame, not once per substep**. Contact pairs discovered at
   the start of a frame are reused by all ten substeps, while the positions they were derived from
   drift over those substeps. This staleness is intrinsic to the method and is part of what must be
   reproduced: detecting per substep produces a visibly different, stiffer drape.
6. **Vertex bookkeeping** — the previous frame's positions are retained and the current particle
   positions are copied to the host. This host copy is what the static test, the dumps and the
   output writer all read.

### 2.3 Static-equilibrium test

**When evaluated.** After the frame completes, and only if **both** of these hold:

- the frame index is greater than or equal to `zero_gravity_steps`, and
- the frame index is greater than or equal to `min_sim_steps`.

**The criterion, exactly.** For every particle, take the absolute per-axis difference between its
current and previous frame positions and sum the three components — an L1 norm per particle. Count
the particles whose L1 norm exceeds `static_threshold`. The cloth is static if that count is zero,
**or** if the count is strictly less than `particle_count × 0.01 × non_static_percent`. With the
shipped values this is: *fewer than 1.5 % of particles moved more than 0.03 cm in total absolute
displacement since the previous frame*. If static, the loop breaks immediately on that frame.

Note the test is on **per-frame displacement**, which with a fixed frame rate is equivalent to a
per-particle speed test, and that it is an **outlier-tolerant** test — a small number of
still-moving vertices cannot prevent the sim from being declared settled.

**`min_sim_steps`** is derived, not configured:

- It starts at 0.
- If body smoothing is enabled it becomes `smoothing_recover_start_frame + smoothing_num_steps`.
- If the attachment constraint is enabled it becomes the greater of that and
  `attachment_frames + 5`. The five extra frames exist so the cloth has a chance to start moving
  again after release before the sim is allowed to call itself settled.
- With the shipped configuration (smoothing off, attachment on, release at 400) **`min_sim_steps` is
  405**. The sim therefore cannot stop before frame 405 however still the cloth is.
- It is recomputed whenever the attachment configuration changes, including when attachment is
  turned off because no labels were found.

### 2.4 Caps and timeouts

| Cap | Shipped value | Behaviour on breach |
| --- | --- | --- |
| `max_sim_steps` | 2400 | Loop ends at frame 2399. Not an error by itself, but see the `static_equilibrium` tag below. |
| `max_frame_time` | 60 s | Per-frame wall-clock alarm. **Frame 0 gets double the budget** (120 s) because of first-frame kernel compilation. Breach raises a frame-timeout and ends the sim. |
| `max_sim_time` | 600 s | Checked after every frame against total elapsed sim time. Breach raises a sim-timeout and ends the sim. |
| `max_meshgen_time` | 60 s | Belongs to the mesh-generation stage, not the sim. Listed for completeness. |

**Platform caveat on the frame timeout.** The per-frame alarm is armed only on platforms the driver
recognises as POSIX-like, and the name it tests for macOS does not match what macOS actually
reports. On macOS the alarm therefore **never arms and the frame is skipped entirely** by that code
path. Seam works around this by nulling `max_frame_time` on macOS (§7). A port should treat the
frame timeout as a host-side concern and not inherit the platform bug.

### 2.5 Fail tags, and when each is recorded

Exactly one tag is recorded per failing condition, into a per-garment fails map.

| Tag | Recorded when |
| --- | --- |
| `frame_timeout` | A frame exceeded its wall-clock budget. |
| `simulation_timeout` | Total sim time exceeded `max_sim_time`. |
| `gt_edges_creation` | A stitching-geometry error was raised during setup. |
| `crashes` | Any other exception escaped the loop. A keyboard interrupt is deliberately **not** recorded as a failure and is re-raised. |
| `static_equilibrium` | The loop ran to the very last allowed frame — that is, the final frame index equals `max_sim_steps − 1`. Recorded **only on the success path**, and the non-static count is re-evaluated and printed at that point. |
| `fast_finish` | The whole sim returned in under 0.5 s. |
| `cloth_body_intersection` | The end-of-sim body intersection count exceeds `max_body_collisions` (35). |
| `cloth_self_intersection` | The end-of-sim self intersection count exceeds `max_self_collisions` (300). |

The four success-path quality tags are evaluated in that order. Note that a sim which simply used
its whole frame budget is tagged `static_equilibrium` even if the drape is perfectly good — Seam's
own results record this tag on essentially every run (§8), so **the tags over-report and must not be
used as the port's acceptance criterion**.

One subtlety worth reproducing: a triangle-inequality violation while building a stitch triangle's
rest shape (§3.3) raises a plain runtime error, which is caught by the catch-all and tagged
`crashes`, **not** `gt_edges_creation`.

### 2.6 End-of-sim intersection counts

On the success path only, and in this order:

1. **Body–cloth intersections** are counted (§5.2) and printed.
2. **Self intersections** are counted (§5.1).
3. Both are stored in the stats as `body_collisions` and `self_collisions`.
4. The two threshold tags above are applied.

Both counters also exist as per-frame diagnostics: in verbose mode the self-intersection count is
printed after every frame.

### 2.7 Stats fields

| Field | Meaning |
| --- | --- |
| `fails` | Map from tag name to the list of garment names carrying it. |
| `sim_time` | Wall-clock seconds for the whole run, including model construction. |
| `spf` | Seconds per frame — total sim time divided by the final frame index, or the total time if that index is zero. Note the divisor is the **index**, not the count. |
| `fin_frame` | The final frame **index** reached. A full 2400-frame run reports 2399. |
| `body_collisions` | The §5.2 count. |
| `self_collisions` | The §5.1 count. |
| `render_time` | Seconds spent in the image render, recorded in the render section. |

### 2.8 What is written

The simulated garment OBJ is produced by **re-using the box mesh OBJ and replacing only its vertex
lines**:

- Every vertex-position line is rewritten, in file order, with the corresponding current particle
  position. The mapping is positional — the nth vertex line gets the nth particle — so **particle
  order must equal box-mesh vertex order**.
- Vertex-normal lines are rewritten only if normals were requested; otherwise they are dropped from
  the output.
- **Every other line is copied through verbatim** — faces, texture coordinates, material references,
  groups, comments. This is why panel UVs, material assignments and the texturing stage survive the
  sim untouched.

If storage optimisation is on, the box mesh and sim mesh are additionally converted to PLY, the
originals unlinked, and the large fabric texture and material file deleted.

An image render is then called **unconditionally**. Seam replaces it with a no-op (§7).

**Port requirement.** The engine must expose final particle positions in box-mesh vertex order on
the host. Nothing else about the output format is the engine's concern.

---

## 3. Model construction

Everything in this section happens once, during cloth construction, before any frame runs.

### 3.1 Inputs loaded

| Input | Contents | Transform applied |
| --- | --- | --- |
| Body OBJ | Triangle mesh of the body | ×100, then Y-shift (§1.2) |
| Body segmentation JSON | Map from body-part name to the list of body vertex indices | none |
| Garment box mesh OBJ | The stitched single-component garment mesh | Y-shift only |
| Garment segmentation text | One row per cloth vertex naming its panel | parsed, see below |
| Original edge lengths pickle | Map from an ordered vertex-index pair to the pattern-space length of that edge | none |
| Pattern specification JSON | Per-panel `label` strings | read for panel labels |
| Vertex labels YAML | Map from attachment-label name to cloth vertex indices | none |
| Body measurements YAML | Named body measurements in centimetres | none |

**Segmentation parsing (`read_segmentation`).** The garment segmentation file has one
comma-separated row per cloth vertex, in vertex order. The first field is the label. **Any label
beginning with `stitch` is collapsed to the single key `stitch`**; all other labels are kept as-is.
The result maps each label to the list of vertex indices carrying it. The `stitch` entry, if present,
becomes the stitching-vertex set; if absent, that set is empty.

If the original-edge-lengths file is missing, the map is treated as absent and a notice is printed.
This materially changes stitching behaviour — see §3.3.

### 3.2 Build order

The order matters because later steps index into arrays filled by earlier ones.

1. Create the builder **with gravity zero**.
2. Load and transform the body; read its segmentation.
3. Load and transform the garment; read its segmentation and stitching set; load original edge
   lengths.
4. **`add_cloth_mesh_sewing_spring`** — creates every particle, triangle, bending element and spring
   (§3.3).
5. Optionally replace the body vertices with a smoothed version (§3.7).
6. Wrap the body vertices and indices as a collider mesh.
7. **`panel_assignment`** — assign each cloth vertex a body-part label (§3.4).
8. Optionally build the body-collision filters (§3.5).
9. **`add_shape_mesh`** — add the body as collider shape index 0 (§3.5).
10. Optionally add the attachment constraints (§3.6).
11. For each used body part, extract its submesh and register it as a reference shape
    (`add_cloth_reference_shape_mesh`).
12. **`add_cloth_reference_labels`** — map per-vertex labels to reference-shape indices and register
    the allowed drag pairs (§3.4).
13. **Finalize** — upload everything, build the cloth's own query mesh, size the contact buffers.
14. Assign the Model fields listed in §6.

**The body is collider shape index 0**, and this index is relied on by the body-intersection counter
and by the inside-body drag constraint.

### 3.3 `add_cloth_mesh_sewing_spring`

This single call creates the entire garment. It is the fork's most consequential addition: upstream's
plain cloth-mesh helper exists too, but it derives all rest state from the input geometry, which for
a box mesh means the *stitched-shut* geometry rather than the pattern's true shape.

**Inputs as `pygarment` passes them.**

| Argument | Value passed | Meaning |
| --- | --- | --- |
| position | origin | Garment placement offset |
| rotation | identity | No rotation |
| scale | 1.0 | Box mesh is already in centimetres |
| velocity | zero | Cloth starts at rest |
| vertices, indices | the box mesh | Triangle soup, two-manifold |
| `resolution_scale` | 1.0 (Seam may override) | Fallback stitch rest edge length |
| `orig_lens` | the edge-length map, or absent | Pattern-space rest lengths |
| `stitching_vertices` | the `stitch` label's vertices | Which vertices were merged by stitching |
| `density` | 1.0 | Mass per unit rest area |
| `radius` | 0.1 | Particle radius, i.e. fabric half-thickness |
| `edge_ke`, `edge_kd` | 1.0, 10.0 | Bending stiffness and damping |
| `tri_ke`, `tri_ka`, `tri_kd` | 10000.0, 10000.0, 1.0 | Per-triangle material — **see the warning below** |
| `tri_drag`, `tri_lift` | 0.0, 0.0 | Aerodynamic terms, unused |
| `add_springs` | true | Create the spring network |
| `spring_ke`, `spring_kd` | 50000.0, 10.0 | Spring stiffness and damping |

**What it creates.**

*Particles.* One per cloth vertex, in input order, each at its transformed position, with the given
initial velocity and the given radius. Particle order equals box-mesh vertex order, which §2.8
depends on.

*Triangles, and the rest-shape split.* The triangles are partitioned into two sets:

- A triangle is a **stitch triangle** if **any** of its three vertices is in the stitching set.
- All others are **normal triangles**.

Normal triangles get their rest shape from their initial 3D configuration, the ordinary behaviour.

Stitch triangles do **not**. Their rest shape is built from the pattern instead, in one of two ways:

- **With `orig_lens` present** (the normal case): the triangle's three vertex indices are sorted, the
  three stored pattern-space lengths for its three vertex pairs are looked up, and a flat triangle
  with exactly those three side lengths is constructed as the rest shape. Its rest area is that flat
  triangle's area. **This is the mechanism that sews the garment**: a stitch triangle spanning a seam
  is born stretched, because its rest shape is the pattern's shape while its initial shape is the
  gap between two panels. Over the gravity-free frames it contracts and pulls the panels together.
  This is GarmentCodeData §3.4 "Draping setup" and supplemental Appendix C.
- **With `orig_lens` absent**: every stitch triangle gets the *same* rest shape — an equilateral
  triangle with side length equal to `resolution_scale`, uniformly rescaled so its area equals the
  **mean rest area of the normal triangles**. Seams then merely resist distortion rather than pulling
  to a known length, and the garment does not properly close.

If the three stored lengths violate the triangle inequality, construction raises and the sim is
tagged `crashes` (§2.5). Degenerate or inverted rest triangles are clamped to zero area, replaced
with an identity rest basis, reported, and excluded from the element list.

*Mass.* Each triangle distributes `density × rest_area ÷ 3` to each of its three vertices,
accumulating. Stitch triangles contribute their **pattern-space** rest area, so mass reflects the
true garment, not the stitched-shut mesh.

*Bending elements.* Built from the adjacency of only the triangles just added. **Only interior edges
qualify** — an edge with a face on just one side produces no bending element, so the garment's
boundaries (hem, neckline, cuffs) are free to curl. Each element references the two vertices of the
shared edge plus the two opposite vertices. **Every rest angle is set to zero**, i.e. the rest state
of the fabric is flat everywhere, regardless of the box mesh's actual initial dihedral angles. Each
element carries `edge_ke` and `edge_kd`.

*Springs.* Created from the bending elements, not from the triangles. For each bending element, five
vertex pairs are added: both opposite vertices paired with each of the two shared-edge vertices, plus
the shared edge itself. Pairs are deduplicated across the whole garment, so the spring set is the set
of **triangle edges plus the diagonals of adjacent triangle pairs**. Each spring's rest length is:

- the stored pattern-space length, if that vertex pair appears in `orig_lens`; otherwise
- the current distance between the two particles.

All springs share `spring_ke` and `spring_kd`.

**The spring set is also the edge set used by both intersection counters (§5) and by the global
piercing survey (§4.5).** This is important: those counts are per-spring, so they include diagonals,
and their magnitude is not comparable to a count over mesh edges alone.

> **⚠ The per-triangle material tuple is inert in this configuration.** Each triangle stores a
> five-value material tuple `(tri_ke, tri_ka, tri_kd, tri_drag, tri_lift)` and it is uploaded to the
> device. But **the XPBD solver launches no triangle kernel at all** — there is no in-plane FEM
> constraint in the XPBD path. The tuple is consumed only by the semi-implicit Euler integrator,
> which `pygarment` does not use (it is constructed and immediately commented out in favour of XPBD).
> Verified by inspection: the XPBD integrator never references the triangle indices, rest poses,
> activations or materials, while the Euler integrator has an explicit triangle evaluation. The
> practical consequences are large and a port must know them:
>
> - **In-plane stiffness comes entirely from the springs.** `spring_ke` and `spring_kd` are the only
>   stretch parameters that bite.
> - **`garment_tri_ke`, `garment_tri_ka` and `garment_tri_kd` change nothing** in an XPBD run.
> - Therefore Seam's material presets differ from each other **only** in `garment_edge_ke`
>   (bending), and Seam's per-triangle neck-stiffness flag is observably a no-op (§7).
>
> A Newton port is free to implement a real triangle constraint, but doing so **changes the drape**
> and invalidates §8's baselines. If the goal is to reproduce the fork, leave in-plane stiffness to
> the springs and expose the triangle parameters as accepted-and-ignored, or omit them.

### 3.4 Panel assignment and the reference shapes

The purpose of this whole block is to answer one question per cloth vertex: *which body part does
this piece of fabric semantically belong to?* The answer drives the body-part drag constraint
(§4.6), which is what un-tangles the heuristic initial panel placement. GarmentCodeData §3.4,
"Resolving initial collisions".

**`panel_assignment`.** Inputs are the garment segmentation, cloth vertices and indices with their
transform, the body segmentation, body vertices and indices with their transform, a device, the
per-panel preferred labels, a strategy, a leg-merge flag and an SMPL flag. `pygarment` passes
strategy `'closest'`, leg-merge **true**, and SMPL **false** for Seam's own bodies.

Behaviour, per panel, skipping the `stitch` and `None` pseudo-panels:

1. For each of the panel's vertices, find the **closest point on the body mesh** and note which body
   face it landed on. The search radius is effectively unbounded, so a face is always found. (The
   alternative `'ray_hit'` strategy instead casts a ray along the panel's own inward normal; it is
   not used.)
2. Accumulate votes: each hit face contributes **one third of a vote to every body-part label carried
   by each of its three vertices**. A body vertex may carry several labels, and all of them score.
3. If the panel has a non-empty preferred label from the pattern specification, **every body part
   whose name does not contain that string is cancelled** by setting its score negative. This
   restricts the winner to parts matching the designer's intent, at whatever granularity the pattern
   declared.
4. The winner is the highest-scoring part.
5. **Leg merge**: if the winner is a single leg and the panel's name does not contain `pant`, the
   label is replaced by the combined `legs` label. The stated reasoning is that panels spanning both
   legs — skirts — drag more stably toward a merged target, while actual trouser panels keep their
   own leg.
6. Every vertex of the panel receives the panel's label.

Vertices belonging to no panel — stitch vertices in particular — keep a sentinel "no label".

Outputs are the per-cloth-vertex label list (one entry per particle) and the set of body parts
actually used, as submesh vertex lists, with the merged arm/leg labels available.

**Body-part label merging.** Before voting, the body segmentation may be transformed two ways. An
SMPL-style segmentation is collapsed into five coarse parts (two arms, two legs including hips, and a
trunk-plus-legs "body"). Separately, a limb-merge pass adds two new labels, `arms` and `legs`, each
the union of its two sides. The voting pass uses the un-merged form; the returned used-parts map uses
the merged form. The fork's own comment flags this asymmetry as suspicious. Reproduce it: the drag
targets include merged limbs even though the voting did not consider them.

**`extract_submesh`.** Given the body vertices, the flat index list and one part's vertex indices:
keep those vertices in the given order, keep **only faces whose all three vertices are in the part**,
and reindex those faces to the new compact numbering. Faces straddling a part boundary are dropped,
so each reference shape is an **open** mesh with a boundary at the joint. This matters for §4.6:
closest-point queries against an open shape can return points on its boundary rim.

**`add_cloth_reference_shape_mesh`.** Registers one reference mesh under a name, with a placement
transform and a per-axis scale. `pygarment` registers one per used body part, all at the origin with
identity rotation and unit scale, because the body was already scaled in §1.2. If no name is given,
the running index is used as the name.

**`add_cloth_reference_labels`.** Inputs are the per-vertex label list and a list of label pairs.
Behaviour:

- Asserts the label list length equals the particle count, and that at least one reference shape has
  been registered. Both are hard errors.
- Builds a name-to-index map over the registered reference shapes and converts each vertex's label
  name to that index. An empty, null or sentinel label becomes "no reference". An unrecognised label
  name is reported and also becomes "no reference".
- **Side effect**: fills the model's per-particle reference-label array. The §0 note that this call
  has a side effect is accurate and the port must preserve it — nothing else populates that array.
- Converts the label-pair list into index pairs, **keeping only pairs where both names are
  registered reference shapes**. Pairs naming an unused body part are silently dropped.
- Returns the name-to-index map.

**The label-pair list is an ALLOW list, not a deny list.** This is the single most likely thing for
an implementer to get backwards, so it is stated plainly: cloth–cloth drag fires **only** when the
pair of labels involved appears in this list. The pairs `pygarment` passes are:

| # | Pair |
| --- | --- |
| 1 | left arm ↔ body |
| 2 | right arm ↔ body |
| 3 | left leg ↔ right leg |
| 4 | left arm ↔ left leg |
| 5 | right arm ↔ left leg |
| 6 | left arm ↔ right leg |
| 7 | right arm ↔ right leg |
| 8 | left arm ↔ legs |
| 9 | right arm ↔ legs |

Matching is **unordered** — either direction qualifies. The accompanying note explains what is
deliberately *absent*: there is **no leg ↔ body pair and no legs ↔ body pair**, on the stated grounds
that dragging between the legs and the trunk is useless and fights the waist attachment. So a trouser
panel intersecting the torso is never dragged apart; only a waist attachment can fix that case.

### 3.5 The body collider and its collision filters

**`add_shape_mesh`** as `pygarment` calls it: attached to **no body** (a static shape), at the origin
with identity rotation and unit scale, with the body mesh, `thickness` from
`body_collision_thickness` (**0.25**), `mu` from `body_friction` (**0.5**), plus the two fork-only
arguments below. It returns the shape index, which is 0.

The remaining material parameters take the builder's shape defaults and are irrelevant here, because
the only contacts generated against this shape are particle–shape soft contacts, which use the
`soft_contact_*` Model fields and the shape's `mu`, not the shape's stiffnesses.

**`face_filters`** — a list of filters. Each filter is a per-body-face flag list; a true flag means
*this body face is ignored*. Default is a single empty filter.

**`model_particle_filter_ids`** — one integer per particle, naming **which single filter that
particle uses**, or a sentinel for none. The comment is explicit that there is **one filter per
particle per shape** — a particle cannot subscribe to two filters. Default is empty.

At finalize both are padded into rectangular arrays: filters are padded to equal length with
false, and an empty per-shape particle-filter list is expanded to a full-length list of the
"no filter" sentinel. A per-shape particle-filter list of the wrong length is a hard error.

**How the filter is applied** (in the soft-contact pass, §4.3): once a particle's closest body face
is known, if that particle has a filter and that filter marks that face, **the contact is discarded
entirely** — no contact is registered, and the inside-body test for that particle does not fire
either. The particle passes through those faces freely.

**`create_face_filter`.** Inputs: body vertices, body indices, body segmentation, the list of part
names to filter, and the SMPL flag. Behaviour: build a per-body-vertex label, then for each face
decide by **majority vote over its three vertices** whether it is in the filtered set. Two caveats
the fork itself flags:

- A body vertex carrying several labels **keeps only the last one assigned**, so multi-label
  vertices are mislabelled.
- Vertices with no label are never filtered.

**`assign_face_filter_points`.** Inputs: the per-cloth-vertex panel labels, the list of part names, a
filter id, an optional vertex-neighbour map, and an optional existing assignment. Behaviour:

- A particle whose panel label is in the named parts gets the filter id.
- A particle with **no** label — a stitch vertex — gets the filter id if **strictly more than half**
  of its mesh neighbours have labels in the named parts. This is what keeps seams behaving like the
  panels they join.
- When merging with an existing assignment, **existing assignments win**. A particle already carrying
  filter *k* keeps *k* even if it also qualifies for *j*.

**As `pygarment` composes them**, when `enable_body_collision_filters` is true (shipped default
**true**):

| Filter id | Body faces ignored | Applied to cloth particles labelled |
| --- | --- | --- |
| 0 | left arm, right arm, arms | left leg, right leg, legs |
| 1 | internal face geometry | body |

Filter 0 is described as "the arm filter for the skirts": fabric that belongs to the legs ignores the
arms, so a skirt hem swinging near a hand does not catch on it. Filter 1 ignores the body's internal
geometry — the mouth cavity and similar — for trunk fabric, which would otherwise find spurious
closest faces inside the head.

Because merging gives priority to the earlier assignment, **leg particles keep filter 0** and only
the remaining trunk particles take filter 1. A particle is never subject to both.

A vertex-neighbour map is built for this purpose: for every face, each of its three vertices records
the other two. The map therefore contains duplicates, which is harmless for a majority vote but means
neighbour counts are weighted by incident-face multiplicity. Reproduce the behaviour, not the
tidiness.

### 3.6 Attachments

**`add_attachment`** is the fork's general pin. Inputs:

| Argument | Meaning |
| --- | --- |
| particle indices | Which particles to constrain |
| attachment point | Either one point per particle, or a **single** point broadcast to all of them |
| attachment normal | Optional. Its presence selects the constraint type |
| stiffness | Constraint stiffness, broadcast to every listed particle |
| damping | Constraint damping, broadcast to every listed particle |

**The two semantics.**

- **No normal given → equality attachment.** The stored normal is zero. At solve time a zero normal
  is detected and replaced by the unit direction from the particle to its target, which makes the
  constraint error always non-positive and therefore always active: the particle is pulled toward the
  target point from wherever it is. The effect is "hold this particle at this point".
- **A normal given → inequality attachment.** The point and the normal define a half-space. The
  constraint is satisfied when the particle lies on the positive side, i.e. when the dot product of
  (particle − point) with the normal is non-negative, and is active only when it is negative. The
  effect is "keep this particle on this side of this plane, and otherwise leave it alone". Combined
  with a single broadcast point this is the natural way to say "do not let these vertices fall below
  this height" — and that is exactly what §7's neck hold does.

Only the **component of position along the normal** is constrained; the particle slides freely within
the plane. For a vertical normal, that means a held waistband can move horizontally and can ride up,
but cannot drop.

**Stiffness and damping units.** These are XPBD constraint parameters, not forces. In the standard
XPBD formulation (Macklin et al. 2016) stiffness enters as a compliance of one over
(stiffness × timestep²) and damping as (damping ÷ (stiffness × timestep)). So stiffness has units of
force per length in the scene's unit system and larger values mean a harder constraint; a stiffness
at or below zero, or a negative damping, disables that entry. Zero damping is explicitly permitted.

**One deviation from textbook XPBD.** The attachment solve computes a Lagrange-multiplier increment
and applies the resulting position delta, but **does not write the accumulated multiplier back**. The
multiplier therefore stays at its zeroed value, so the constraint behaves as a fresh single-shot
projection each time it is visited rather than a properly accumulated compliant constraint. With the
default of one iteration per substep this is unobservable — each substep visits it once anyway — but a
port that raises the iteration count will diverge from the fork here. The spring and bending
constraints, by contrast, *do* accumulate correctly.

**How `pygarment` builds the attachments.** The attachment labels are tried in configured order and
each is matched against the vertex-labels file; a label that is absent, or present with no vertices,
is skipped. The index of the label within the configured list selects its stiffness and damping, so
**the stiffness and damping lists are positionally aligned with the label-name list**.

| Label | Point | Normal | Resulting behaviour |
| --- | --- | --- | --- |
| `lower_interface` | (0, waist level, 0) | +Y | Waistband must stay at or above waist level |
| `right_collar` | (−(neck width − 2) ÷ 2, 0, 0) | +X | Collar vertices must stay at or to the +X side of that plane |
| `left_collar` | (+(neck width − 2) ÷ 2, 0, 0) | −X | Collar vertices must stay at or to the −X side of that plane |
| `strapless_top` | (0, underarm level, 0) | +Y | Bodice must stay at or above the underarm |

All four are **inequality** attachments. The levels come from body measurements:

- **Waist level** is the measurement `_waist_level` if present, else height − head length − waist
  line.
- **Underarm level** is height − head length − armscye depth.
- **Neck width** is the `neck_w` measurement **minus 2 cm**, and each collar is pinned at half that,
  so the two collar planes sit 2 cm inside the measured neck width. The two normals point **inward
  toward each other**, meaning each collar side is pushed toward the neck centre line — a sideways
  pinch, not a vertical hold. This is precisely the behaviour Seam's neck-hold flag replaces, and
  Seam's results show why: a sideways pinch keeps a collar near the neck while letting the whole
  garment sink.

Any other requested label prints a warning and is skipped. **If no configured label matched at all,
the attachment constraint is switched off entirely and `min_sim_steps` is recomputed** — which,
with smoothing off, drops it to zero and lets the sim stop as soon as it is static.

**Release.** See §2.2 step 4. The constraint is dropped wholesale at `attachment_frames`; individual
attachments cannot be released separately, and there is no fade.

### 3.7 Body smoothing

Shipped default is **off** (`enable_body_smoothing` false), so this is not on Seam's path. It is
specified because `implicit_laplacian_smoothing` and `replace_mesh_points` are both in the gap table
and a port must either implement or deliberately omit them.

**`implicit_laplacian_smoothing`.** Inputs are vertices, triangles, a step size and an iteration
count. It performs standard **implicit (backward-Euler) Laplacian mesh smoothing** using a cotangent
Laplacian and a barycentric mass matrix — the classical Desbrun-style implicit fairing scheme. Each
iteration solves the linear system *(M − h·L) V' = M·V* for the new vertices, where L is the
cotangent Laplacian, M the mass matrix and h the step size. Two details of the fork's use:

- The **cotangent Laplacian is computed once** from the original mesh and reused for every iteration,
  while the **mass matrix is recomputed** from the current vertices at each iteration.
- The return value is the **whole sequence**: a list of iteration-count-plus-one vertex sets, index 0
  being the unmodified original and the last being the most smoothed.

Output is that list; topology never changes, so the body's faces and its segmentation stay valid for
every entry.

**How `pygarment` drives it.** Step size is `smoothing_total_smoothing_factor ÷ smoothing_num_steps`.
A frame list is precomputed, holding one frame number per smoothing step: the nth entry is
`smoothing_recover_start_frame` plus n times `smoothing_frame_gap_between_steps`, counting n from zero
up to and including the step count. Then:

- The **last** (most smoothed) vertex set is taken as the body's starting shape, and the last frame
  number is dropped from the list.
- At each remaining listed frame, the next-to-last entry is taken, so the body walks **backwards
  toward its original shape**.

The net behaviour: the sim starts against a smooth, detail-free body — which is far easier to drape
onto without catching — and the real anatomy is restored over the smoothing window. By
`smoothing_recover_start_frame + smoothing_frame_gap_between_steps × smoothing_num_steps` the body is
exact again. `min_sim_steps` is raised so the sim cannot declare itself settled before that.

`smoothing_num_steps` is clamped into the range zero to `max_sim_steps − smoothing_recover_start_frame`,
and if the clamp yields zero, smoothing is disabled.

**`replace_mesh_points`.** Overwrites a mesh's point array in place from a supplied array, one
element per vertex. It is a device-side bulk copy and nothing else: no normal recomputation, no
topology change, no acceleration-structure update. **The caller must refit the mesh's bounding
hierarchy afterwards**, and `pygarment` does. Used in two distinct places:

1. By `pygarment`, to swap in the next smoothed body (followed by a refit).
2. By the integrator itself, at the end of **every substep**, to push current particle positions into
   the cloth's own query mesh (followed by a refit) — see §4.9.

**Port requirement.** The engine must allow the collider mesh's vertices to be replaced between
frames without rebuilding the model, and must expose a refit. Newton's own mesh handling must be
checked for whether a refit is sufficient or a rebuild is required; if only a rebuild is available,
smoothing becomes expensive but remains correct.

### 3.8 Finalize

Relevant behaviour only:

- **The cloth's own query mesh (`particle_shape`) is built here**, from the particle positions and the
  full cloth triangle index list. This mesh is what every self-collision query and both intersection
  counters run against. It is a *separate* mesh object from the collider shapes.
- **Per-vertex normals** are computed for that mesh, by summing each face's unnormalised normal into
  its three vertices and then normalising. Area-weighted, since the unnormalised cross product scales
  with area.
- Each reference shape is finalised to a device mesh; the Python-side meshes are retained so they are
  not garbage collected.
- The per-particle reference-label array, the drag-particle flag array (zeroed) and the allowed
  drag-pair array are uploaded, along with the pair count.
- Attachment indices, points, normals, stiffnesses, dampings and a multiplier array are uploaded.
- Springs, triangles, bending elements each get their arrays plus a multiplier array.
- **Contact buffer sizing** happens here, and it is multiplicative:

| Buffer | Shipped per-unit allowance | Total allocated |
| --- | --- | --- |
| Soft (body) contacts | — | 65 536, a flat cap |
| Edge–edge self contacts | **192 per spring** | 192 × spring count |
| Point–triangle self contacts | **64 per particle** | 64 × particle count |
| Global piercing flags | — | one per bending element, plus two single counters |

  The per-unit allowances are the fork's own defaults and `pygarment` does not change them. These
  buffers dominate the sim's memory and are the reason peak VRAM scales with garment size (§8). Both
  self-contact passes **print a diagnostic naming the exceeded limit and drop the element** on
  overflow rather than failing, so an undersized buffer degrades collision quality silently.
- `particle_max_velocity` is taken from the builder, whose default is 100 000; `pygarment` overwrites
  it afterwards (§6).
- Gravity is set to the up vector times the builder's gravity, which is **zero** here.
- Triangle collisions are explicitly disabled.

---

## 4. The step

### 4.1 Order of operations

**Once per frame**, before any substep:

| # | Pass | Notes |
| --- | --- | --- |
| 1 | Clear the drag flags and the piercing flags | Only if drag or the global filter is on |
| 2 | **Body soft-contact generation** (§4.3) | Over every particle × every shape but the last |
| 3 | Rigid-body broadphase and narrowphase | No rigid bodies here — no-op |
| 4 | **Global piercing survey** (§4.5) | Only if the global collision filter is on |
| 5 | **Edge–edge self-contact detection** (§4.7) | Requires springs to exist |
| 6 | **Point–triangle self-contact detection** (§4.7) | Over every particle |

Passes 5 and 6 run **after** pass 4 deliberately, because they consume the piercing flags it sets.

**Then, ten times** (once per substep), each time with the short timestep:

| # | Step | Condition |
| --- | --- | --- |
| 1 | Clear particle and body forces | always |
| 2 | **Integration** with gravity and global damping (§4.2) | always |
| 3 | Zero the spring, bending and attachment multipliers | once per substep, before the iteration loop |
| 4 | Zero the position-delta accumulator | per iteration |
| 5 | Ground contact | only if `ground` — **off** here |
| 6 | **Body contact solve** (§4.3) | if more than one shape exists |
| 7 | **Body-part drag solve** (§4.6) | if `cloth_reference_drag` |
| 8 | Particle–particle self contact | if enabled — **off** here |
| 9 | **Point–triangle self-contact solve** (§4.7) | if `enable_triangle_particle_collisions` |
| 10 | **Edge–edge self-contact solve** (§4.7) | if springs exist and `enable_edge_edge_collisions` |
| 11 | **Spring solve** (§4.8) | if springs exist |
| 12 | **Bending solve** (§4.8) | if bending elements exist |
| 13 | **Attachment solve** (§3.6) | if `attachment_constraint` |
| 14 | Tetrahedral solve | none exist |
| 15 | **Apply position deltas, with the velocity cap** (§4.9) | always |
| 16 | Rigid-body and restitution passes | none / disabled |
| 17 | **Push particle positions into the cloth query mesh and refit** | always |

Note that steps 6 and 7 sit **inside** the iteration loop and that step 15 closes it. All constraint
passes write into **one shared delta accumulator** and are applied together — this is a Jacobi-style
solve, not Gauss–Seidel, so constraint ordering within an iteration does not matter but the
*accumulation* does.

Note also that step 8's particle–particle pass is documented in the fork as producing CUDA errors
when combined with body-part drag, cause unknown. It is off in the shipped configuration and should
stay off.

### 4.2 Integration

Standard semi-implicit (symplectic) Euler, as in PBD's prediction step: accelerate the velocity by
force over mass plus gravity, then advance position by the new velocity. Gravity is applied only to
finite-mass particles (§1.3). Between the velocity update and the position update, the fork inserts
**global viscous damping**, which is its own addition.

**`global_viscous_damping` is a three-component value**, and `pygarment` packs it as
**(damping factor, effective velocity, maximum velocity)**:

| Component | Shipped value | Behaviour |
| --- | --- | --- |
| damping factor | **0.25** | If this is greater than zero **and** the particle's new speed exceeds the effective velocity, the velocity is multiplied by the exponential of the negative of (factor × speed × timestep). Because the exponent is proportional to speed, this is **quadratic drag** — fast particles are damped far harder than slow ones. |
| effective velocity | **0.0** | The speed above which damping applies. At zero, damping applies to **any** moving particle. |
| maximum velocity | **25.0** | If this is greater than zero and the speed exceeds it, the velocity direction is kept and its magnitude is set exactly to this cap. |

Two details to reproduce exactly:

- Both tests use the speed **before** damping, so the cap test is not re-evaluated against the damped
  velocity within this step.
- The cap here affects velocity only; position is advanced with the capped velocity, so it is
  consistent. The *other* cap, in §4.9, is the one that also rewrites position.

Upstream's integration takes a plain maximum-velocity scalar and clamps with it. The fork replaces
that scalar with this triple, adding the speed-proportional damping while keeping a cap. A port must
provide both the quadratic damping and the cap; omitting the damping makes the garment ring and
oscillate instead of settling, and the static test in §2.3 will then never pass.

Observable effect: energy is removed aggressively from fast motion and gently from slow motion, which
is what lets a garment dropped onto a body settle within a couple of thousand frames without the
drape being visibly damped-looking.

### 4.3 Body contact

**Detection**, once per frame, for every particle against every collider shape except the last
(the last being the ground plane, which is handled separately):

1. Transform the particle into the shape's local frame.
2. Find the closest point on the shape, with a sign indicating inside or outside. For a mesh this is
   a signed closest-point query using face normals, and **its search radius is effectively unbounded**
   — the nearest face is always found regardless of distance. The margin is applied afterwards, as a
   test, not as a search bound.
3. **Apply the per-particle face filter** (§3.5). A filtered face discards the contact and skips
   step 6 as well.
4. Compute the signed distance to the surface point and the outward normal.
5. **Subtract the shape's collision thickness** from the distance. With `body_collision_thickness`
   0.25 the body behaves as if inflated by 0.25 cm, so cloth is held off the skin.
6. **Register a contact** if the thickness-adjusted distance is **greater than the negative margin
   and less than the margin plus the particle radius**. The contact stores the shape, the surface
   point and surface velocity in body-local coordinates, the particle, and the world-space normal.
7. **Independently**, if the thickness-adjusted distance is **below the negative margin** — the
   particle is *deeper inside than the margin* — flag that particle for **body-collision drag**
   (§4.6). This is the only place that flag is raised.

Shipped values: `soft_contact_margin` **0.2** (a config-class constant, not a YAML key), particle
radius **0.1**, body thickness **0.25**. So the contact band runs from 0.2 cm inside the inflated
surface to 0.3 cm outside it, and anything more than 0.2 cm inside is treated as a penetration to be
dragged out rather than a contact to be resolved.

Overflow past the soft-contact cap increments the count but writes nothing, so contacts beyond
65 536 are lost. The count is clamped when consumed.

**Response**, per solver iteration, per registered contact:

- The constraint value is the normal distance from the particle to the contact point minus the
  particle's radius. The contact is skipped if that value exceeds `particle_adhesion` (0.0), so only
  touching-or-penetrating contacts are resolved.
- The **friction coefficient is the average of the particle's own `particle_mu` (0.5) and the shape's
  `mu` (`body_friction`, 0.5)** — so the effective coefficient is 0.5, and changing `body_friction`
  alone moves the effective value only half as far.
- Relative velocity between particle and shape is split into normal and tangential components. The
  shape here is static, so its velocity contribution is zero.
- The normal correction pushes the particle out along the contact normal. The tangential (friction)
  correction is limited by the Coulomb condition against the normal correction and, separately,
  cannot exceed the tangential displacement that would occur over the timestep — a standard
  non-overshoot clamp (Bridson et al. 2002 handles friction in the same spirit).
- The combined correction is divided by the summed inverse masses and scaled by the
  **soft-contact relaxation, 0.9**, then accumulated into the shared delta buffer.

**How the inside/outside decision is made** differs between the two mechanisms and this is important:

- For **contact**, the sign comes from the signed closest-point query, i.e. from the local face
  normal at the nearest point. This is cheap and correct near a smooth surface, but unreliable in
  concave regions and near boundaries.
- For **drag** (§4.6), a different and more robust test is used: a **three-ray parity vote**. Rays
  are cast along +X, +Y and +Z; the point is declared inside only if **all three** report hitting a
  back-facing triangle. Unanimity is required, so the test is conservative — it under-reports inside
  rather than over-reporting it. This is the classical ray-parity containment test, hardened by
  voting across axes to survive the degenerate ray-through-an-edge cases a single ray hits.

### 4.4 The `collide` entry point and what its timestep is for

The fork's signature is **(model, state, timestep, edge search iterations)**. Upstream's is
**(model, state, edge search iterations)** — the timestep is the fork's inserted third positional
argument, and this signature change alone breaks any upstream-shaped caller.

**The timestep is used only for forward prediction in the two self-contact detection passes.** It
never integrates anything. In both passes, candidate positions are advanced one step by velocity plus
a gravity term, and the candidate pair is kept only if the *predicted* separation is small enough.
`pygarment` passes the **full frame period**, so detection looks a whole frame ahead while the solver
steps a tenth of that. The effect is a generous contact band: pairs are created well before they
actually touch, which is what makes predictive contacts stable (Lewin, GDC 2018).

The edge-search-iteration argument applies only to rigid-body edge/SDF contacts and is irrelevant
here.

### 4.5 The global piercing survey and `global_collision_filter`

This is the fork's answer to the initial-penetration problem described in GarmentCodeData §3.4,
"Resolving initial collisions": conventional self-collision response *preserves* the current
relative configuration, so it will faithfully preserve an interpenetration that was present at frame
zero. The fix is to find the already-pierced elements and **exempt them** from self-collision
response so they can pass back through.

Runs once per frame, before self-contact detection, only when `global_collision_filter` is true
(`enable_global_collision_filter`, shipped **true**). Over **the spring set**:

1. Treat the spring's two endpoints as a segment and ask whether it pierces the cloth's own mesh,
   using the edge query of §5.5 — which excludes any triangle sharing either endpoint.
2. On a hit:
   - Increment a **global self-intersection counter** (distinct from the reportable counter of §5.1).
   - **Mark both endpoints as already-intersecting.** Both self-contact detection passes skip any
     element touching a marked particle, so these particles are released from self-collision
     entirely.
   - Determine the panel label of the pierced face — taken from the **first of its three vertices
     that carries a label** — and the panel label of the piercing edge, likewise the first labelled
     endpoint.
   - If the face's label exists and **differs** from the edge's label, and the unordered label pair is
     in the allow list (§3.4), **mark both endpoints for cloth–cloth drag**.

Unlabelled geometry is deliberately excluded: a face with no labelled vertex never triggers drag.

Observable effect: at the start of a sim the garment's self-intersecting regions go limp with respect
to each other and are simultaneously pulled toward their own body parts, so overlaps unwind instead
of locking. Once an edge stops piercing, its particles are no longer flagged on the next frame and
normal self-collision resumes.

**`global_collision_filter` has no default on the model.** Nothing initialises it; `pygarment`
assigns it during setup, and the collision pass reads it unconditionally. A port must give it a
default — false is the safe choice — or an unset field will fault.

### 4.6 Body-part drag

The constraint `cloth_reference_*` configures. Runs inside every solver iteration, over every
particle, but returns immediately unless the particle **is flagged**, is active, and has a reference
label. Two different behaviours share the pass, selected by which flag value the particle carries.

**Who is dragged, toward what.**

| Flag | Raised by | Target | Active when |
| --- | --- | --- | --- |
| 1 — cloth–cloth | §4.5, piercing edge whose label pair is allowed | The reference submesh of the particle's **own panel label** | The particle is **farther** from its body part than `cloth_reference_margin` plus its radius |
| 2 — inside body | §4.3, particle deeper than the contact margin inside the body | The **whole body** collider, at `cloth_reference_watertight_whole_shape_index` | The particle is **inside** (three-ray vote, §4.3) |

So flag 1 pulls stray fabric *in* toward the limb it belongs to, and flag 2 pushes trapped fabric
*out* of the body. The fork's own comment notes the two should really be separate constraints with
separate flag arrays.

**How strongly.** This is the most surprising behaviour in the whole step and a port must not
"improve" it:

- The correction direction is the unit vector from the particle toward the closest point on the
  target.
- The correction magnitude is the **full distance to that closest point**. The inverse mass cancels
  between the numerator and the denominator, so the particle is projected **all the way onto the
  target surface in a single application**, with no compliance, no relaxation and no step limiting.
- **`cloth_reference_k` is accepted, stored, uploaded, passed into the constraint — and never used.**
  The fork's own comment asks whether it should be put back. So the stiffness field in the gap table
  is inert: setting it to any value changes nothing.
- The only thing that limits how far a particle actually moves per substep is the velocity cap in
  §4.9, which rewrites position as well as velocity. **That cap is what makes this constraint
  survivable**, and it is the fork's stated stability fix.

**Margin.** `cloth_reference_margin`, shipped **0.1** cm, gates only the cloth–cloth branch: fabric
within the margin plus its radius of its own body part is left alone. The inside-body branch ignores
the margin and triggers on any detected penetration.

**Collision thickness is deliberately not applied** when computing the drag target, on the stated
reasoning that the gradient direction would be wrong for a particle inside the thickness shell. Note
also that the thickness value read is always the **main collider's**, even in the cloth–cloth branch
where the target is a body-part submesh — an inconsistency to reproduce rather than fix.

**State read.** The constraint reads **frame-start** positions and velocities, not the current
predicted positions. Across the ten substeps of a frame it therefore keeps pulling toward a target
computed from where the particle was at the beginning of the frame.

**When it stops.** The flags are cleared and recomputed at the start of **every** frame's collision
pass. So:

- Flag 2 clears as soon as the particle is no longer deeper than the margin inside the body.
- Flag 1 clears as soon as the particle's springs no longer pierce the cloth, or the label pair stops
  qualifying.

Drag therefore stops on the frame **after** the condition resolves, and it is self-terminating: a
garment that untangles stops being dragged. This yields the acceptance check in §6.

**`cloth_reference_watertight_whole_shape_index`** names which collider shape counts as "the whole
body" for the flag-2 branch. `pygarment` sets it to **0**, matching the body being the first collider
added. It has **no model default** — it is initialised to a null value and only `pygarment`'s
assignment makes it usable.

### 4.7 Self-collision

Point–triangle and edge–edge, the classical decomposition (Provot 1997; Bridson et al. 2002),
implemented as predictive positional constraints in the XPBD setting (Lewin, GDC 2018).
GarmentCodeData §3.4 records that these two algorithms are the fork's own addition because the base
simulator lacked them.

Both share a thickness convention: the target separation is **twice the particle radius**, i.e. 0.2 cm
with the shipped `fabric_thickness`, and the detection band adds a safety margin of **half a radius**
on top, giving 0.25 cm. Both also share the rule that **already-piercing particles are skipped**
(§4.5).

**Point–triangle detection**, once per frame, per particle:

- Skip if the particle is flagged as already intersecting.
- Query the cloth mesh for faces within an axis-aligned box of half-extent **three times the particle
  radius** about the particle. The three-radius figure follows the published guidance on avoiding the
  instability that arises when the detection band is too tight relative to the response thickness.
- Reserve one contact slot per returned face.
- **Exclude the particle's own incident faces** — any face naming this particle is marked filtered.
- Otherwise compute the closest point on the triangle by barycentric clamping, predict the particle
  and the three triangle vertices forward one detection step by velocity plus a gravity term, project
  both predicted motions onto the current separation direction, and **keep the contact only if the
  predicted separation falls below twice the radius plus half a radius**.
- Record the pair and a **sidedness flag**: whether the particle currently lies on the negative side
  of the triangle's normal. This freezes the correct separation direction at detection time, which is
  what stops the response from flipping the particle through the triangle later in the frame.

**Point–triangle response**, per iteration, per recorded pair:

- Skip entries past the recorded count or marked filtered.
- Take the triangle normal, **flip it if the sidedness flag says so**.
- The constraint is the normal distance from the triangle's closest point to the particle, minus
  twice the radius; active only when negative.
- Gradients are formed with respect to the particle **and** all three triangle vertices, and the
  denominator includes all four inverse masses, so the constraint is *scaled* as a four-body
  constraint. But **only the particle's own delta is applied** — the three triangle vertices are
  never moved by this pass. Each of them gets its own opportunity when it is itself the queried
  particle.
- **No compliance and no damping**: the correction is applied at full strength with relaxation 1.0,
  the fork's stated intent being that the constraint "should be as hard as possible". This is a
  deliberate departure from XPBD's compliant form.

**Edge–edge detection**, once per frame, per spring:

- Skip if **either** endpoint is flagged as already intersecting.
- Query the cloth mesh for faces within a box about the **edge midpoint** of half-extent
  **half the edge length plus three radii**.
- Reserve **three slots per returned face**, one per face edge.
- Mark a slot filtered if the face edge **shares a vertex** with the query edge, or if the same
  opposite edge was **already recorded within this edge's own block** — the duplicate check compares
  the pair in reversed order, because neighbouring triangles traverse a shared edge in opposite
  directions.
- Otherwise find the closest points between the two segments. **Reject the pair if either closest
  point lies within one radius of a segment endpoint** — that configuration is left to the
  point–triangle pass, which handles it better. This is the standard split of responsibilities
  between the two tests.
- Predict both closest points forward one detection step, project onto the connecting direction, and
  keep the contact only if the predicted separation falls below twice the radius plus half a radius.
- Record the four particle indices and the **connecting direction at detection time**.

**Edge–edge response**, per iteration, per recorded pair:

- Skip entries past the recorded count or marked filtered.
- Recompute the closest points from current positions, take the connecting direction, and **flip it
  to agree with the direction recorded at detection time**. Same anti-flip purpose as the sidedness
  flag.
- The constraint is the separation along that direction minus twice the radius; active only when
  negative.
- Gradients are formed for all four particles and the denominator includes all four inverse masses,
  but **only the two particles of the first edge are moved**. The second edge is corrected when it is
  itself the query edge.
- **No compliance, no damping, relaxation 1.0**, same stated reasoning as above.

**Neither pass implements friction.** Both carry an explicit note that friction is not accounted for.
Cloth-on-cloth therefore slides freely, which is part of why garments slip on the body in Seam's
results.

**The three toggles.**

| Toggle | Shipped | Effect when false |
| --- | --- | --- |
| `enable_triangle_particle_collisions` | **true** | Point–triangle detection still runs every frame and still fills its buffer; only the **response** is skipped. |
| `enable_edge_edge_collisions` | **true** | Edge–edge detection still runs; only the response is skipped. |
| `enable_particle_particle_collisions` | **false** | Also suppresses the per-frame hash-grid rebuild. Documented as producing CUDA errors together with body-part drag. |

Note the asymmetry: **the two self-contact detection passes are unconditional**, gated only on
particles and springs existing, while their solves are gated on the toggles. Turning a toggle off
therefore saves solve time but not detection time or memory. The point–triangle detection is not even
gated on the self-collision radius being positive, whereas both responses sit behind a check that the
maximum particle radius exceeds zero.

### 4.8 Springs, bending, and the missing triangle solve

**Springs** are the standard XPBD distance constraint (Macklin et al. 2016) to each spring's stored
rest length — which for seam springs is the **pattern-space** length, not the initial distance
(§3.3). Compliance is one over (`spring_ke` × timestep²) and damping enters as
`spring_kd` ÷ (`spring_ke` × timestep). The multiplier **is** accumulated across iterations, properly.
A spring with zero length is skipped; a non-positive stiffness or negative damping disables the
spring. Shipped values are `spring_ke` **50000.0** and `spring_kd` **10.0**.

Since there is no triangle constraint (below), **the springs are the garment's entire in-plane
behaviour** — stretch, shear and the seam contraction that assembles the garment.

**Bending** is the standard XPBD dihedral-angle constraint over each interior edge's two triangles,
driving the angle to the stored rest angle, which §3.3 sets to **zero everywhere** — fabric wants to
be flat. Compliance and damping take the same XPBD form with `garment_edge_ke` and `garment_edge_kd`.
Elements with a degenerate normal on either face are skipped, as are those with a non-positive
stiffness or negative damping. The multiplier is accumulated properly. Shipped values are
`garment_edge_ke` **1.0** — commented in the configuration as "very soft fabric" — and
`garment_edge_kd` **10.0**.

**Bending stiffness is the one material lever that visibly works** in this configuration, which is
why Seam's presets are effectively bending presets (§7).

**There is no triangle or in-plane FEM solve in the XPBD path.** See the warning in §3.3. What
"stiffness" means for each constraint that *does* run:

| Constraint | Stiffness parameter | Meaning |
| --- | --- | --- |
| Spring | `spring_ke` | XPBD compliance; higher is a harder length constraint |
| Bending | `garment_edge_ke` | XPBD compliance on the dihedral angle; higher resists folding |
| Attachment | per-label `attachment_stiffness` | XPBD compliance on the pin, but see §3.6's multiplier note |
| Body contact | `soft_contact_*` plus relaxation 0.9 | A relaxation-scaled projection, not a compliance |
| Self contact | none | Hard projection, relaxation 1.0 |
| Body-part drag | `cloth_reference_k`, **ignored** | Full projection to the surface |

### 4.9 Applying the deltas, and the velocity cap

This closes each solver iteration, over every active particle:

1. The new position is the predicted position **plus** the accumulated delta from every constraint
   that fired.
2. The new velocity is derived as the total displacement **from the position at the start of the
   substep** divided by the timestep — PBD's velocity derivation.
3. **The cap**: if the resulting speed exceeds `particle_max_velocity`, the velocity is rescaled to
   that cap **and the position is recomputed** as the start-of-substep position plus the capped
   velocity times the timestep.

**Step 3 is the fork's stated stability fix** — the one its own notes describe as applying the
maximum velocity to position for stability. Upstream's equivalent limits the reported velocity but
leaves the position where the constraints put it, so a hard projection can teleport a particle
arbitrarily far in one substep and the velocity cap merely hides it. The fork's version makes the cap
a genuine bound on motion.

**This matters enormously here**, because §4.6's drag constraint projects particles the full distance
to a surface with no limiting of its own. Without the position rewrite, a deeply penetrating particle
would jump out instantly and explode the neighbouring springs. With it, the motion is spread over
substeps and frames.

**Observable rule to reproduce:** no particle's position changes by more than
`particle_max_velocity` × timestep within one substep. With the shipped cap of **25.0** scene units
per second and a timestep of one six-hundredth of a second, that is **at most about 0.0417 cm per
substep**, hence at most about **0.417 cm per frame**. This is a directly checkable invariant and the
best single test that a port's cap is wired correctly.

`particle_max_velocity` is set by `pygarment` from `global_max_velocity`, the **same value** that is
the third component of `global_viscous_damping`. So one configuration number, 25.0, serves as both
the integration-time clamp and the delta-time clamp. The model's own default is 100 000, i.e.
effectively no cap, so a port that forgets this assignment will appear to work and then explode.

**Velocity update.** There is no separate velocity pass for particles: velocity is derived in step 2
above, every iteration. The body-velocity-from-position pass and both restitution passes exist but do
nothing here, having no rigid bodies and restitution disabled.

**Finally**, after the iteration loop, current particle positions are pushed into the cloth's own
query mesh and its bounding hierarchy is refit — **every substep**. So the mesh used by self-collision
queries and by the counters is current as of the last substep, while the *contact pairs* were derived
once at the start of the frame. A port must keep this mesh updated at substep rate, or the
intersection counters in §5 will report against stale geometry.

---

## 5. Counters

Four counters and one native query. All operate on the **cloth's own query mesh** and, except where
noted, over **the spring set** — so "edge" below means *spring*, including the diagonals of §3.3, not
only mesh edges.

### 5.1 `count_self_intersections`

- **Launched over the spring count**, with the spring indices and the cloth query mesh.
- Per spring: treat the two endpoints as a segment and run the edge query of §5.5. On a hit,
  atomically increment a single counter.
- **Returned number**: the number of **spring edges that pierce the cloth mesh**. Not pairs, not
  pierced faces, and not particles. One spring piercing three faces counts once.
- Guarded: returns zero unless both particles and springs exist. The counter is zeroed before each
  use.
- Read back to the host as a single integer.

### 5.2 `count_body_cloth_intersections`

- **Launched over the spring count**, with the spring indices, the cloth query mesh, the shape
  geometry and the **body shape index** (0).
- Per spring: take the first endpoint as a ray origin and the direction to the second endpoint, with
  a maximum distance equal to the **edge length**, and cast against the **body** mesh. On a hit,
  increment a single counter.
- Because the target is a *different* mesh, this uses an ordinary ray query — **the adjacent-face
  exclusion of §5.5 does not apply and is not needed**.
- **Returned number**: the number of **spring edges that cross the body surface**. This is a measure
  of cloth buried in the body.
- Guarded only on particles existing, though it is launched over the spring count — so a model with
  particles but no springs would launch nothing. Not reachable with `pygarment`'s construction, which
  always adds springs.

### 5.3 `particle_self_intersection_count`

A single-element device counter, the output target of §5.1. Zeroed before each count. Allocated
alongside two companions:

- **`particle_global_self_intersection_count`** — a *separate* single-element counter, used by the
  per-frame piercing survey of §4.5. The two are distinct and must not be conflated: one is the
  reportable end-of-sim statistic, the other is internal bookkeeping that runs every frame.
- **`particle_self_intersection_particle`** — a **per-particle flag array**, sized to the particle
  count, marking particles that lie on a piercing edge. This is the array both self-contact detection
  passes consult to decide whom to exempt.

### 5.4 `body_cloth_intersection_count`

A single-element device counter, the output target of §5.2. Zeroed before each count. Note it is
allocated inside the **soft-contact** allocation rather than with the other intersection counters —
an organisational quirk, but it means a port that allocates intersection counters only when
self-collision is enabled will leave this one missing.

### 5.5 `mesh_query_edge`

The fork's new native builtin, and the reason a source build is required (prebuilt packages ship no
native headers). An adjoint entry point exists but is an empty stub, so **this query is not
differentiable**.

**Inputs**: a mesh identifier and **two vertex indices of that same mesh**. Not arbitrary points —
the segment is defined by naming two of the mesh's own vertices.

**Behaviour**: treat the segment from the first vertex to the second as a ray, with a maximum
distance equal to the segment's length, and find the nearest triangle it hits, subject to one
exclusion:

- **Any triangle naming either endpoint vertex is skipped.** This is the adjacency exclusion. It
  removes the triangles incident to the edge — which a segment lying in their plane would otherwise
  trivially "hit" — and is why the query is meaningful as a self-intersection test at all. Note the
  exclusion is by **vertex identity**, so it also excludes triangles that merely touch an endpoint
  without sharing the edge.

**What counts as a hit**: a triangle intersection at a distance along the segment that is
non-negative and **strictly less than the segment length**. Reaching exactly the far endpoint does
not count. A small epsilon expansion is applied to bounding-box tests during traversal, which makes
the broad phase slightly permissive but does not change the final triangle test.

**Outputs on a hit**: true, plus the distance along the segment, the barycentric coordinates of the
hit, a **sign** indicating whether the triangle was hit front- or back-facing, the normalised triangle
normal, and the face index. On a miss: false, and the outputs are not written.

**What the returned number means in the counters**: each counter uses only the boolean. The sign,
barycentrics and normal are used by the piercing survey of §4.5 only insofar as it needs the face
index to look up the pierced face's panel label.

**Port note.** This is the one piece of genuinely new native code. Before writing a native extension,
check whether the target engine's existing ray query can be given a maximum distance and whether
adjacent triangles can be excluded some other way — for instance by filtering hits on the host, or
by checking the returned face's vertices against the two endpoints and treating a shared-vertex hit
as a miss. A filtered ordinary ray query reproduces this behaviour exactly, at the cost of
occasionally returning the *second* nearest hit when the nearest is adjacent. That difference is
observable only when a segment pierces an adjacent face, which the exclusion defines as impossible,
so **a host-filtered ray query is a faithful substitute** and avoids owning a CUDA toolchain.

---

## 6. Gap-table coverage

One subsection per symbol. Defaults are quoted from the shipped configuration file, the
configuration class, or `pygarment`'s setup, and the source is named. "Config fallback" means the
value used only if the key is absent from the configuration file.

### 6.1 `implicit_laplacian_smoothing`

- **Purpose** — produce a sequence of progressively smoothed body shapes so the sim can start against
  a detail-free body and restore anatomy gradually.
- **Inputs / outputs** — in: vertices, triangles, step size, iteration count. Out: a list of
  iteration-count-plus-one vertex arrays, index 0 the original, last the most smoothed. Topology
  unchanged.
- **Parameters** — `smoothing_total_smoothing_factor` **1.0**; `smoothing_num_steps` **100**;
  `smoothing_recover_start_frame` **150**; `smoothing_frame_gap_between_steps` **1**;
  `enable_body_smoothing` **false** (all from the configuration file). Derived step size is
  total factor ÷ step count = **0.01**. Step count is clamped to
  `max_sim_steps − smoothing_recover_start_frame` and smoothing is disabled if the clamp yields zero.
- **Where in the step** — not in the step. Called once at construction; its results are consumed at
  the listed frames by the frame loop (§2.2 step 3).
- **Observable effect** — with smoothing on, the body silhouette starts visibly rounded and sharpens
  between frames 150 and 250; `min_sim_steps` rises to 250 so the sim cannot stop before the body is
  exact. With the shipped default off, none of this occurs.
- **Acceptance check** — with smoothing enabled, the body collider's vertex positions at frame
  `smoothing_recover_start_frame + smoothing_frame_gap_between_steps × smoothing_num_steps` equal the
  original loaded-and-scaled body vertices to within floating-point tolerance, and at frame 0 the
  mean distance from those originals is strictly greater than zero. With smoothing disabled, the body
  collider's vertices are bit-identical to the originals at every frame.

### 6.2 `count_self_intersections`

- **Purpose** — report how much the garment passes through itself, as an end-of-sim quality measure.
- **Inputs / outputs** — in: spring indices, cloth query mesh. Out: one integer, the count of
  piercing springs. §5.1.
- **Parameters** — none of its own. Thresholded against `max_self_collisions` **300** (configuration
  file).
- **Where in the step** — not in the step. Once at end of sim, plus once per frame in verbose mode.
- **Observable effect** — none on the sim; it is purely diagnostic. Drives the
  `cloth_self_intersection` tag.
- **Acceptance check** — on a garment mesh constructed with a known number of springs deliberately
  threaded through non-adjacent faces, the returned integer equals that number; and on a flat,
  non-self-intersecting panel it returns exactly 0. Running it twice without stepping returns the
  same value, confirming the counter is zeroed before use.

### 6.3 `count_body_cloth_intersections`

- **Purpose** — report how much garment is buried inside the body.
- **Inputs / outputs** — in: spring indices, cloth query mesh, shape geometry, body shape index.
  Out: one integer, the count of springs crossing the body surface. §5.2.
- **Parameters** — the body shape index, **0** as `pygarment` passes it. Thresholded against
  `max_body_collisions` **35** (configuration file).
- **Where in the step** — not in the step. Once at end of sim, before the self-intersection count.
- **Observable effect** — diagnostic only. Drives the `cloth_body_intersection` tag.
- **Acceptance check** — with the garment translated far from the body it returns exactly 0; with the
  garment translated fully inside the body it returns a value strictly greater than zero and no
  greater than the spring count. A garment resting cleanly on the body returns a small number
  consistent with §8's baselines.

### 6.4 `replace_mesh_points`

- **Purpose** — swap a mesh's vertex positions in place without rebuilding the model.
- **Inputs / outputs** — in: a mesh identifier and a full-length vertex array. Out: the mesh's points
  are overwritten. No return value, no normal recomputation, no hierarchy update.
- **Parameters** — none. The array length must equal the mesh's vertex count.
- **Where in the step** — two places: by `pygarment` at each body-smoothing frame (followed by a
  refit), and by the integrator at the **end of every substep** on the cloth's own query mesh
  (followed by a refit). §4.9.
- **Observable effect** — collision queries made after the call see the new geometry. Without the
  refit, queries return stale results against the old bounding hierarchy.
- **Acceptance check** — after replacing a mesh's points with a set translated by a known offset and
  refitting, a closest-point query from a fixed probe returns a distance differing from the
  pre-replacement distance by that offset. And: the cloth query mesh's vertex positions read back at
  the end of a frame equal the particle positions read back for that same frame, element-wise.

### 6.5 `panel_assignment` and the functions `pygarment` calls with it

The module provides five entry points that `pygarment` uses directly.

#### 6.5.1 `read_segmentation`

- **Purpose** — turn the per-vertex garment segmentation file into a label-to-vertices map.
- **Inputs / outputs** — in: a path. Out: a map from label to the list of vertex indices, in file
  order. **All labels beginning with `stitch` collapse to the single key `stitch`.**
- **Parameters** — none.
- **Where in the step** — construction only.
- **Observable effect** — determines the stitching-vertex set (and hence which triangles get
  pattern-space rest shapes) and the panel membership used for assignment.
- **Acceptance check** — on a file with rows `panel_a`, `stitch_3`, `stitch_7`, `panel_b`, the result
  has exactly three keys, and the `stitch` key lists indices 1 and 2.

#### 6.5.2 `panel_assignment`

- **Purpose** — give every cloth vertex the body part it semantically belongs to, and report which
  body parts are used.
- **Inputs / outputs** — in: garment segmentation, cloth vertices/indices/transform, body
  segmentation, body vertices/indices/transform, device, per-panel preferred labels, strategy,
  leg-merge flag, SMPL flag. Out: a per-cloth-vertex label list (one entry per particle, sentinel for
  stitch and unassigned vertices) and a map of used body parts to their vertex lists. §3.4.
- **Parameters as `pygarment` passes them** — strategy **`'closest'`**; `merge_two_legs` **true**;
  `smpl_body` **false** for Seam's bodies; preferred labels taken from each panel's `label` field in
  the pattern specification. The closest-point search radius is effectively unbounded.
- **Where in the step** — construction only, before the collider and the reference shapes.
- **Observable effect** — decides each panel's drag target. A mis-assignment sends fabric toward the
  wrong limb, which is highly visible: a sleeve dragged toward the trunk.
- **Acceptance check** — for a garment whose panels are unambiguously placed (a sleeve tube around an
  arm, a trunk panel over the chest), every vertex of the sleeve panel receives an arm label and
  every vertex of the trunk panel receives the trunk label; the returned used-parts map contains
  exactly the labels that appear in the vertex list; and a panel declaring a preferred label never
  receives a label that does not contain that string.

#### 6.5.3 `create_face_filter`

- **Purpose** — mark the body faces belonging to named parts, so chosen cloth can ignore them.
- **Inputs / outputs** — in: body vertices, body indices, body segmentation, the part names to
  filter, SMPL flag. Out: one boolean per body face, true meaning "ignore this face".
- **Parameters** — the part-name list. `pygarment` calls it twice: with the arm labels, then with the
  internal-face label. §3.5.
- **Where in the step** — construction only; consumed per frame by body-contact detection.
- **Observable effect** — filtered faces generate no contacts for subscribed particles, which pass
  through them.
- **Acceptance check** — the count of true flags equals the number of faces whose majority of
  vertices carry a named label; a face with no labelled vertex is false; and a particle subscribed to
  the filter, placed adjacent to a filtered face and to no other, generates zero body contacts.

#### 6.5.4 `assign_face_filter_points`

- **Purpose** — decide which cloth particles subscribe to which filter.
- **Inputs / outputs** — in: per-cloth-vertex panel labels, part names, a filter id, an optional
  vertex-neighbour map, an optional existing assignment. Out: one filter id per particle, sentinel
  for none.
- **Parameters as `pygarment` passes them** — first call: leg labels, filter id **0**, with the
  neighbour map. Second call: the trunk label, filter id **1**, with the neighbour map and the first
  call's result as the existing assignment. §3.5.
- **Where in the step** — construction only.
- **Observable effect** — unlabelled seam particles inherit a filter by neighbour majority, so seams
  behave like the panels they join; and **earlier assignments win**, so leg particles keep filter 0.
- **Acceptance check** — a particle whose panel label is in the named parts carries the filter id; an
  unlabelled particle more than half of whose neighbours are in the named parts carries it, and one
  with exactly half does not; and after the second call, no particle assigned 0 by the first call
  carries 1.

#### 6.5.5 `extract_submesh`

- **Purpose** — cut one body part out as a standalone mesh, to serve as a drag target.
- **Inputs / outputs** — in: body vertices, flat index list, the part's vertex indices. Out: the
  part's vertices in the given order and a reindexed flat face list, containing **only faces all three
  of whose vertices are in the part**.
- **Parameters** — none.
- **Where in the step** — construction only, once per used body part.
- **Observable effect** — each reference shape is an **open** mesh with a boundary at the joint, so
  closest-point queries against it can land on that rim.
- **Acceptance check** — every returned face index is less than the returned vertex count; the
  returned face count equals the number of original faces fully inside the part; and a vertex shared
  by two parts appears in both submeshes.

### 6.6 `ModelBuilder.add_attachment` — equality and inequality

- **Purpose** — pin chosen particles to a point, or confine them to a half-space.
- **Inputs / outputs** — in: particle indices; an attachment point, either per-particle or a single
  point broadcast; an optional normal; a stiffness; a damping. Out: appends to the attachment arrays.
  Stiffness, damping and a broadcast normal are replicated per particle. §3.6.
- **Semantics** — **no normal → equality**, the particle is pulled to the point from any direction.
  **Normal given → inequality**, the particle is only corrected when it is on the negative side of the
  plane through the point with that normal, and is otherwise free, including free to slide within the
  plane.
- **Parameters and defaults `pygarment` passes** — `attachment_label_names`
  **`lower_interface`, `right_collar`, `left_collar`, `strapless_top`**;
  `attachment_stiffness` **[1000, 1000, 1000, 1000]**; `attachment_damping` **[10, 0, 0, 0]** — note
  only the waistband is damped; `enable_attachment_constraint` **true**; `attachment_frames` **400**
  (all from the configuration file). The lists are **positionally aligned with the label list**.
  Stiffness is an XPBD compliance term with units of force per length in scene units; damping has
  units of force-time per length. Stiffness at or below zero, or damping below zero, disables an
  entry; zero damping is valid. Points are derived from body measurements in centimetres as tabulated
  in §3.6.
- **Where in the step** — solve step 13, inside every iteration, after bending and before the delta
  application.
- **Observable effect** — held vertices do not cross their plane while the constraint is on, and are
  completely unconstrained the frame after release.
- **Acceptance check, inequality** — for the waistband attachment, **no vertex carrying the
  `lower_interface` label has a Y coordinate below the waist level minus a small tolerance at any
  frame before `attachment_frames`**, while such vertices are free to rise above it and to translate
  in X and Z. **Acceptance check, equality** — an attachment created with no normal brings its
  particles to within a small tolerance of the target point within a few frames and holds them there.
  **Acceptance check, release** — the maximum per-frame displacement among held vertices is strictly
  greater immediately after `attachment_frames` than immediately before it.

### 6.7 `ModelBuilder.add_cloth_mesh_sewing_spring`

- **Purpose** — build the whole garment: particles, triangles with pattern-space rest shapes for
  seams, bending elements, and the spring network that both stitches the panels and supplies all
  in-plane stiffness.
- **Inputs / outputs** — see the argument table in §3.3. Creates particles, two classes of triangle,
  bending elements over interior edges only, and springs. No return value used by `pygarment`.
- **Parameters and defaults** — `fabric_density` **1.0**, `fabric_thickness` **0.1** (the particle
  radius), `garment_edge_ke` **1.0**, `garment_edge_kd` **10.0**, `garment_tri_ke` **10000.0**,
  `garment_tri_ka` **10000.0**, `garment_tri_kd` **1.0**, triangle drag and lift **0.0** (fixed in the
  configuration class), `spring_ke` **50000.0**, `spring_kd` **10.0**, `resolution_scale` **1.0**,
  springs **enabled** (all from the configuration file except drag/lift and the springs flag, which
  `pygarment` fixes). Units: lengths in centimetres, density as mass per square centimetre,
  stiffnesses as XPBD compliance terms.
- **Where in the step** — construction only. Its products are consumed by solve steps 11 and 12 and
  by every pass in §5.
- **Observable effect** — the garment closes along its seams during the gravity-free frames. The
  per-triangle material tuple has **no observable effect** in the XPBD path (§3.3).
- **Acceptance check** — after `zero_gravity_steps` frames with gravity still off, the mean length of
  springs whose vertex pair appears in the original-length map is within a small tolerance of their
  stored pattern-space lengths, and strictly shorter than at frame 0. Also: the number of bending
  elements equals the number of interior edges of the cloth mesh, exactly; and no bending element
  references a boundary edge. Also: total particle mass equals `fabric_density` times the total rest
  area of all triangles, to within floating-point tolerance.

### 6.8 `ModelBuilder.add_cloth_reference_labels`

- **Purpose** — bind each particle to the reference shape of its body part, and declare which
  cross-part pairs are eligible for drag.
- **Inputs / outputs** — in: the per-particle label list, and a list of label pairs. Out: returns the
  name-to-index map; **side effect**, fills the model's per-particle reference-label array and the
  allowed-pair array. §3.4.
- **Parameters** — the pair list `pygarment` passes is the nine-row table in §3.4. **It is an allow
  list**: drag fires only for listed pairs. Pairs naming an unregistered part are silently dropped.
  Matching is unordered. **No leg-to-trunk pair is included**, deliberately.
- **Where in the step** — construction only; consumed per frame by the piercing survey (§4.5) and per
  iteration by the drag solve (§4.6).
- **Observable effect** — a sleeve intersecting the trunk is pulled apart; a trouser leg intersecting
  the trunk is not.
- **Acceptance check** — the per-particle reference-label array has exactly one entry per particle,
  with the sentinel for every stitch vertex and a valid reference-shape index for every panel vertex.
  The allowed-pair array's length equals the number of passed pairs whose **both** names are
  registered reference shapes. And behaviourally: with a sleeve panel deliberately intersecting a
  trunk panel, both panels' piercing-edge particles become flagged for drag within one frame, whereas
  with a leg panel deliberately intersecting the trunk panel, none do.

### 6.9 `ModelBuilder.add_cloth_reference_shape_mesh`

- **Purpose** — register one body part as a named drag target.
- **Inputs / outputs** — in: a mesh, an optional name, a position, a rotation, a per-axis scale. Out:
  appends to the reference-shape arrays. If no name is given, the running index is used.
- **Parameters as `pygarment` passes them** — the part's extracted submesh; the part name as the
  name; position at the **origin**; identity rotation; scale **(1, 1, 1)**, because the body was
  already scaled by 100 at load (§1.2). One call per used body part.
- **Where in the step** — construction only; the meshes are finalised to device meshes at finalize and
  queried per iteration by the drag solve.
- **Observable effect** — defines the surface each flagged particle is projected onto.
- **Acceptance check** — the number of registered reference shapes equals the number of distinct
  labels in the used-parts map; and a closest-point query from a point just outside a named part
  returns a point on that part's surface, at a distance matching an independently computed
  point-to-mesh distance.

### 6.10 `Model.attachment_constraint`

- **Purpose** — the master switch for the attachment solve, and the mechanism of release.
- **Inputs / outputs** — a boolean field on the model.
- **Parameters and defaults** — model default **false**; `pygarment` sets it from
  `enable_attachment_constraint` (**true**). It is forced to false at construction if none of the
  configured labels were found. The frame loop sets it to false at the first frame at or after
  `attachment_frames` (**400**) and re-captures the graph; it is never set back to true.
- **Where in the step** — gates solve step 13, and also gates the per-substep zeroing of the
  attachment multipliers.
- **Observable effect** — while true, attachments hold; from the release frame onward they are simply
  not applied.
- **Acceptance check** — the attachment solve is observably inactive from frame `attachment_frames`
  onward: held vertices that were pinned above a plane may fall below it after that frame and not
  before. Additionally, setting `attachment_frames` above `max_sim_steps` keeps the constraint active
  for the entire run, and held vertices never cross their plane at any frame.

### 6.11 `Model.cloth_reference_drag`

- **Purpose** — master switch for the body-part drag solve.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — model default **false**; `pygarment` sets it from
  `enable_cloth_reference_drag` (**true**).
- **Where in the step** — gates solve step 7; also, together with the global filter, gates the
  per-frame clearing of the drag and piercing flag arrays.
- **Observable effect** — with it off, initial interpenetrations persist for the whole sim, since
  nothing else resolves them.
- **Acceptance check** — with a garment deliberately initialised with a panel inside the body, the
  count of particles inside the body falls monotonically over the first tens of frames with drag
  enabled, and does not fall with it disabled.

### 6.12 `Model.cloth_reference_k`

- **Purpose** — nominally the drag stiffness.
- **Inputs / outputs** — a scalar field, uploaded and passed into the drag solve.
- **Parameters and defaults** — model default **1000.0**; configuration-class fallback
  **10 000 000.0**, which is what is actually used because the configuration file does not set
  `cloth_reference_k`. So `pygarment` passes **1.0e7**.
- **Where in the step** — passed into solve step 7 and **not read**. §4.6.
- **Observable effect** — **none.** The drag constraint projects the particle the full distance to the
  target surface regardless of this value. The fork's own comment asks whether the term should be
  restored.
- **Acceptance check** — running the same garment twice with `cloth_reference_k` set to two values
  differing by several orders of magnitude produces **bit-identical** final particle positions. A port
  that gives this field an effect fails this check and will not reproduce §8.

### 6.13 `Model.cloth_reference_margin`

- **Purpose** — the slack allowed before cloth–cloth drag pulls a particle toward its own body part.
- **Inputs / outputs** — a scalar field, in centimetres.
- **Parameters and defaults** — model default **0.1**; configuration file **0.1**.
- **Where in the step** — solve step 7. Gates **only** the cloth–cloth branch: that branch acts when
  the distance to the particle's own body part exceeds the margin plus the particle's radius, so with
  shipped values, beyond **0.2 cm**. The inside-body branch ignores the margin.
- **Observable effect** — larger values let flagged fabric float further from its limb before being
  pulled in; smaller values pull it tight against the body part.
- **Acceptance check** — a flagged particle whose distance to its own body part is less than the
  margin plus its radius receives **zero** drag correction, while one just beyond that distance
  receives a non-zero correction directed toward its body part.

### 6.14 `Model.cloth_reference_watertight_whole_shape_index`

- **Purpose** — name the collider shape that counts as "the whole body" for the inside-body drag
  branch.
- **Inputs / outputs** — an integer field.
- **Parameters and defaults** — **no model default**; initialised to a null value, and only
  `pygarment`'s assignment of **0** makes it usable. Zero is correct because the body is the first
  collider added.
- **Where in the step** — solve step 7, inside-body branch: selects the target mesh, its transform,
  its scale, and the thickness value used by **both** branches.
- **Observable effect** — a wrong index drags penetrating cloth toward the wrong surface. A null index
  faults.
- **Acceptance check** — particles flagged as inside the body are projected onto the **body** surface,
  not onto any body-part submesh: after one frame of drag, each such particle's distance to the full
  body mesh is smaller than before, and the direction of its correction matches the direction to the
  closest point on the full body mesh.

### 6.15 `Model.global_viscous_damping`

- **Purpose** — remove energy from fast motion so the garment settles, and cap speed during
  integration.
- **Inputs / outputs** — a three-component field, packed as **(damping factor, effective velocity,
  maximum velocity)**.
- **Parameters and defaults** — model default **(0, 0, 0)**, i.e. inert. `pygarment` sets it from
  `global_damping_factor` **0.25**, `global_damping_effective_velocity` **0.0** and
  `global_max_velocity` **25.0** (configuration file). Units: the factor is reciprocal
  length (it multiplies speed × time to give a dimensionless exponent); the other two are scene units
  per second, i.e. cm/s.
- **Where in the step** — inside integration, solve step 2, between the velocity update and the
  position update. §4.2.
- **Observable effect** — quadratic drag: damping grows with speed, so a swinging hem is damped hard
  and a settling fold barely at all. With the field left at its default the garment oscillates and
  never satisfies the static test.
- **Acceptance check** — with gravity on and all constraints disabled, a single free particle's speed
  after one substep is strictly less than the undamped prediction whenever its speed is non-zero, and
  never exceeds **25 cm/s** however long it falls. Setting the factor to zero makes the speed match
  the undamped prediction exactly up to the cap.

### 6.16 `Model.enable_edge_edge_collisions`

- **Purpose** — switch the edge–edge self-contact **response**.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — model default **false**; configuration file **true**.
- **Where in the step** — gates solve step 10. **Detection still runs regardless** (§4.7).
- **Observable effect** — with it off, folds pass through each other where two cloth edges cross
  without either vertex being near a face.
- **Acceptance check** — with two cloth strips crossed edge-to-edge and no vertex near the other
  strip's interior, the minimum edge-to-edge separation stays at or above twice the particle radius
  with the flag on, and falls below it with the flag off.

### 6.17 `Model.enable_triangle_particle_collisions`

- **Purpose** — switch the point–triangle self-contact **response**.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — model default **false**; configuration file **true**.
- **Where in the step** — gates solve step 9. **Detection still runs regardless.**
- **Observable effect** — the dominant self-collision mechanism; with it off, the garment freely
  passes through itself wherever a vertex meets a face.
- **Acceptance check** — with a cloth vertex pressed toward a non-adjacent cloth triangle, its
  distance to that triangle stabilises at or above twice the particle radius with the flag on, and
  passes through with it off.

### 6.18 `Model.enable_particle_particle_collisions`

- **Purpose** — switch particle–particle self-contact.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — model default **false**; configuration file **false**.
- **Where in the step** — gates solve step 8, **and** gates the per-frame particle hash-grid rebuild
  in the frame loop (§2.2 step 1).
- **Observable effect** — none in the shipped configuration. Documented in the fork as producing CUDA
  errors when enabled together with body-part drag, cause unknown.
- **Acceptance check** — with the flag false, no hash-grid rebuild occurs and results are unchanged by
  the grid's contents; the port may legitimately omit this feature, in which case the check is that
  setting the flag true raises a clear unsupported error rather than silently doing nothing.

### 6.19 `Model.particle_self_intersection_count`

- **Purpose** — the device-side accumulator for the reportable self-intersection count.
- **Inputs / outputs** — a single-element integer array; read back to the host as one integer.
- **Parameters** — none. Allocated at finalize, sized to the bending-element count for its companions.
  Zeroed before each count.
- **Where in the step** — not in the step; written by §5.1. Distinct from the internal per-frame
  counter used by the piercing survey, which must be a **separate** accumulator.
- **Observable effect** — none on the sim.
- **Acceptance check** — zeroing then counting twice in a row without stepping yields the same value
  both times, and that value is unaffected by how many frames have run since the last count.

### 6.20 `Model.body_cloth_intersection_count`

- **Purpose** — the device-side accumulator for the body-intersection count.
- **Inputs / outputs** — a single-element integer array; read back as one integer.
- **Parameters** — none. Allocated **within the soft-contact allocation**, not with the other
  intersection counters — a port that allocates intersection state only under a self-collision flag
  will leave this missing.
- **Where in the step** — not in the step; written by §5.2.
- **Observable effect** — none on the sim.
- **Acceptance check** — present and zeroable on a model built with particles and a body collider but
  with every self-collision toggle false.

### 6.21 `mesh_query_edge`

- **Purpose** — decide whether the segment between two named mesh vertices pierces that same mesh,
  ignoring the triangles adjacent to those vertices.
- **Inputs / outputs** — in: a mesh identifier, two vertex indices of that mesh. Out: a boolean, plus
  distance along the segment, barycentrics, a front/back sign, the triangle normal, and the face
  index. §5.5.
- **Parameters** — none configurable. The maximum distance is the segment length, implicitly. The
  exclusion rule is fixed: **any triangle naming either endpoint vertex is skipped**. A hit requires a
  distance that is non-negative and strictly less than the segment length. The adjoint is a stub, so
  the query is not differentiable.
- **Where in the step** — once per frame in the piercing survey (§4.5), and in the self-intersection
  counter (§5.1). Not used by the body-intersection counter, which targets a different mesh.
- **Observable effect** — determines which particles are exempted from self-collision and which are
  flagged for cloth–cloth drag; and determines the reported self-intersection number.
- **Acceptance check** — for a segment lying in the plane of its own incident triangles, the query
  returns false (the exclusion works). For a segment deliberately threaded through one non-adjacent
  triangle, it returns true with that triangle's face index and a distance strictly between zero and
  the segment length. For a segment whose far endpoint lies exactly on a non-adjacent triangle, it
  returns false. A host-filtered ordinary ray query that discards hits on triangles sharing either
  endpoint satisfies all three checks and is an acceptable substitute.

### 6.22 `add_shape_mesh` — `face_filters` and `model_particle_filter_ids`

- **Purpose** — let chosen cloth particles ignore chosen body faces.
- **Inputs / outputs** — `face_filters`: a list of filters, each one boolean per body face, true
  meaning ignore. `model_particle_filter_ids`: one integer per particle naming its single filter, or a
  sentinel for none. Both are padded to rectangular arrays at finalize; a wrong-length per-shape
  particle list is a hard error.
- **Parameters and defaults** — builder defaults are a single empty filter and an empty id list.
  `pygarment` passes two filters and a full id list when `enable_body_collision_filters` is **true**
  (configuration file), composed as the table in §3.5. **One filter per particle per shape** — a
  particle cannot subscribe to two.
- **Where in the step** — consumed once per frame in body-contact detection (§4.3), after the closest
  face is found and **before** both the contact registration and the inside-body flag test.
- **Observable effect** — a subscribed particle passes through its filtered faces entirely: no
  contact, and no inside-body drag from them. A skirt's leg fabric does not catch on the arms; trunk
  fabric does not catch on internal head geometry.
- **Acceptance check** — a particle subscribed to the arm filter, positioned within the contact margin
  of an arm face and of nothing else, generates **zero** body contacts and is **not** flagged for
  inside-body drag; the same particle with its filter id set to the sentinel generates exactly one
  contact.

### 6.23 `Model.global_collision_filter`

- **Purpose** — switch the per-frame piercing survey that exempts already-intersecting elements from
  self-collision and flags cloth–cloth drag.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — **no model default**; nothing initialises it, and `pygarment` assigns
  it from `enable_global_collision_filter` (**true**). A port must supply a default or reading it
  faults.
- **Where in the step** — gates the survey (§4.5), and together with the drag flag gates the
  per-frame clearing of the flag arrays.
- **Observable effect** — this is what lets initial interpenetrations unwind. Without it, standard
  self-collision response faithfully preserves them for the whole sim — the failure mode
  GarmentCodeData §3.4 "Resolving initial collisions" describes.
- **Acceptance check** — with a garment initialised with a known self-intersection, the particles on
  the piercing springs are flagged within one frame and are absent from the self-contact pair lists
  for that frame; and the self-intersection count falls over subsequent frames. With the flag false,
  no particle is ever flagged and the count does not fall.

### 6.24 The `collide` signature and what its timestep is for

- **Purpose** — generate all contact information for one frame.
- **Signature** — fork: **(model, state, timestep, edge search iterations with default 10)**.
  Upstream 1.0.0-beta.6: **(model, state, edge search iterations)**. The timestep is the fork's
  inserted third positional argument.
- **What the timestep is for** — **forward prediction in the two self-contact detection passes only.**
  Candidate positions are advanced one step by velocity plus a gravity term and the pair is kept only
  if the predicted separation is below the band. It integrates nothing. §4.4.
- **Parameters and defaults** — `pygarment` passes **the full frame period**, one sixtieth of a
  second — the solver timestep multiplied by the substep count — so detection looks ten solver steps
  ahead. The edge-search-iteration argument applies only to rigid-body contacts and is irrelevant.
- **Where in the step** — once per frame, before the substeps.
- **Observable effect** — a larger timestep creates contacts earlier and more of them, which is
  stabilising but costs buffer space; passing the solver timestep instead would create contacts too
  late and allow tunnelling.
- **Acceptance check** — a pair of cloth elements approaching at a known relative speed enters the
  contact list when their separation is approximately twice the radius plus half a radius plus
  relative speed times the frame period, not times the substep period.

### 6.25 `Model.particle_shape`

- **Purpose** — the cloth's own mesh, used for every self-collision query and both intersection
  counters.
- **Inputs / outputs** — a mesh built at finalize from the particle positions and the full cloth
  triangle index list. Accompanied by a per-vertex normal array, computed by summing unnormalised
  face normals into the vertices and normalising — hence area-weighted.
- **Parameters and defaults** — model default is null; built unconditionally at finalize whenever
  particles exist. It is a **separate mesh object from the collider shapes**.
- **Where in the step** — queried by the piercing survey and both self-contact detection passes once
  per frame; **its points are overwritten and its hierarchy refit at the end of every substep**
  (§4.9).
- **Observable effect** — if it is not updated per substep, self-collision queries and the counters
  report against stale geometry.
- **Acceptance check** — reading this mesh's points at the end of any frame yields exactly the
  particle positions for that frame, element-wise; and a closest-point query against it immediately
  after a substep reflects that substep's motion.

### 6.26 `Model.ground`

- **Purpose** — switch the ground-plane contact pass.
- **Inputs / outputs** — a boolean field.
- **Parameters and defaults** — model default **true**; configuration-class fallback **true**;
  configuration file **false**. `pygarment` assigns the configuration value, so **ground is off**.
- **Where in the step** — gates solve step 5 and the ground branch of the rigid broadphase. A ground
  plane shape is nevertheless created at finalize if none exists, which is why body-contact detection
  deliberately iterates over every shape **except the last**.
- **Observable effect** — with ground off, a garment that slides off the body falls indefinitely. This
  is exactly what Seam observed for both bottoms under the default release behaviour (§8), with final
  Y values below zero.
- **Acceptance check** — with the flag false, a particle released well below the body continues
  descending at the damping-limited terminal speed and never comes to rest at Y = 0; with it true, it
  rests at approximately the particle radius above the plane.

### 6.27 Contact-buffer sizing

- **Purpose** — bound the memory for self-contact pairs.
- **Parameters and defaults** — soft (body) contacts **65 536** flat; edge–edge **192 per spring**;
  point–triangle **64 per particle**. All three are fork defaults that `pygarment` does not change.
  The per-unit figures are multiplied by the spring and particle counts at finalize.
- **Where in the step** — allocation at finalize; the caps are tested during detection.
- **Observable effect** — on overflow, both self-contact passes **print a diagnostic naming the
  exceeded limit and drop the element**, so collision quality degrades silently rather than failing.
  These buffers dominate VRAM and are why peak memory tracks garment size (§8).
- **Acceptance check** — allocated element counts equal 192 times the spring count and 64 times the
  particle count respectively; and a deliberately crowded region that exceeds the cap produces the
  diagnostic rather than a crash or a corrupted pair list.

### 6.28 Fork defaults that differ from upstream

Collected for the port, since each is a silent behaviour change if missed.

| Item | Upstream 1.0.0-beta.6 | Fork / as `pygarment` runs it |
| --- | --- | --- |
| XPBD solver iterations | 2 | **1** |
| `collide` signature | (model, state, edge iters) | **(model, state, timestep, edge iters)** |
| Integration damping input | a plain maximum-velocity scalar | **a (factor, effective velocity, maximum) triple** |
| Velocity cap at delta application | velocity only | **velocity and position** |
| `global_collision_filter` | does not exist | **exists, with no default** — must be initialised |
| `cloth_reference_watertight_whole_shape_index` | does not exist | **exists, initialised null** — must be set |
| Particle self-collision mesh | does not exist | **built unconditionally at finalize** |
| Triangle rest shapes | from initial geometry | **from pattern edge lengths for stitch triangles** |
| Bending rest angles | from initial geometry | **zero everywhere** |
| Per-particle collision filters against a shape | does not exist | **one filter id per particle per shape** |
| Soft-contact cap / particle max velocity defaults | 65 536 / 100 000 | unchanged |
| `warp.sim.particles` | — | **behaviourally identical**; the fork's only change there is a commented-out debug print |

- **Acceptance check for this table** — each row's behaviour is verified by the acceptance check of
  its own subsection above. As a single composite check: a port that satisfies §6.1 through §6.27 and
  reproduces §8's intersection trends has, necessarily, picked up every row here, because each row is
  load-bearing for at least one of those checks. The two rows with no default of their own
  (`global_collision_filter`, `cloth_reference_watertight_whole_shape_index`) have the sharpest
  check: constructing a model and reading either field **before** the host assigns it must not fault
  in the port, whereas in the fork it would.

---

## 7. Seam's patches, as they touch the engine

All of Seam's sim-side patches live in one file and are applied by wrapping `pygarment` methods at
import time; nothing under the vendored trees is modified. **Every knob below is off by default** —
each is a no-op until a flag sets it. Seam's pattern-stage module contains **no engine surface at
all**: its stretch-on neckband operates purely on the drafted pattern and makes no simulation calls,
so it imposes no requirement here.

### 7.1 Neck hold (`--neck-hold none|ring|points`)

**What it does.** Replaces `pygarment`'s sideways collar pin (§3.6) with a **vertical half-space
hold**. The collar labels are removed from the configured attachment list so `pygarment` builds the
other attachments normally, then for each collar label present an attachment is added with:

- point **(0, level, 0)** where `level` is the **minimum Y of that label's rest cloth vertices, minus
  0.5 cm** — half a centimetre of slack below the neckline's own starting height;
- normal **+Y**, i.e. an inequality constraint meaning *these vertices may ride up but may not drop*;
- the same stiffness and damping `pygarment` would have used for that label, taken by its index in
  the original label list.

The attachment constraint is then force-enabled and the derived `min_sim_steps` recomputed.

The `points` variant additionally **narrows each collar label to twelve vertices before the labels are
saved**: it splits the neckline ring into its front and back halves by the median Z of the labelled
vertices, and at each half's innermost and outermost X extreme keeps that vertex plus its two nearest
neighbours. The `ring` variant holds the whole labelled ring.

**What the engine must offer.** Inequality attachment against an **arbitrary plane** given as a point
and a normal, with per-attachment stiffness and damping; the ability to add attachments for a chosen
subset of labelled vertices while the host's own labelling handles the rest; and attachment creation
after the garment's particles exist, since the level is computed from rest positions.

### 7.2 Neck stiffness (`--neck-stiff FACTOR`)

**What it does.** After the garment is built, finds the triangles with any vertex within **1.5 cm** of
any collar-label vertex (a k-d tree radius query) and multiplies the **first two entries of those
triangles' material tuples** — the two in-plane stiffness terms — by the given factor, leaving
damping, drag and lift untouched. It reports how many of the garment's faces were in the band.

**What the engine must offer.** Per-triangle material parameters, mutable after the garment is built
and before the model is finalised.

> **Honest finding: this flag is observably inert.** The two entries it scales are precisely the two
> that **no XPBD solver pass reads** (§3.3). The reported face count is correct and the band is
> selected correctly, but the simulation result is unchanged. This is consistent with Seam's own
> record, which reverted the hold-and-stiffness defaults and concluded that no flag-level lever in
> this stack addresses the neckline shape. A port should either implement a real in-plane constraint —
> accepting that it changes the drape and invalidates §8 — or carry this parameter as
> accepted-and-ignored and document it as such.

### 7.3 Dumps (`--dump-every N`)

**What it does.** After each frame whose index is a non-negative multiple of N, writes the cloth face
array once and the current cloth vertex positions for that frame, into the output directory.

**What the engine must offer.** Host-readable particle positions after each frame, in box-mesh vertex
order. This is already required by §2.8.

### 7.4 Material presets

**What it does.** Maps a listing's free-text material tag to a preset, which overrides material keys
in the configuration before the model is built. An unknown preset name prints a notice and falls back
to the defaults. The mapping and the presets:

| Preset | Keys set | Materials mapped to it |
| --- | --- | --- |
| `stiff` | triangle stiffness **20000**, triangle area stiffness **20000**, `garment_edge_ke` **50.0** | denim, canvas, leather, corduroy |
| `soft` | `garment_edge_ke` **0.5** | cotton, polyester, wool, nylon |
| `jersey` (also `soft_flexy`) | triangle stiffness **5000**, triangle area stiffness **5000**, `garment_edge_ke` **0.5** | fleece, jersey, cotton jersey, knit |

**What the engine must offer.** Bending stiffness and damping, spring stiffness and damping, density
and thickness settable per run.

**Honest finding.** Given §3.3, the presets differ from each other and from the default **only in
bending stiffness**: `stiff` is 50.0 against the default 1.0, and `soft` and `jersey` are both 0.5.
The triangle values in `stiff` and `jersey` have no effect, and `jersey` is therefore
behaviourally identical to `soft`. This is consistent with the observed results, where the `soft` and
`stiff` runs differ and nothing distinguishes `jersey` from `soft`.

### 7.5 Body friction (`--body-friction`)

**What it does.** Overrides `body_friction`, which becomes the body collider shape's friction
coefficient (§3.5). Upstream default **0.5**.

**What the engine must offer.** A per-shape friction coefficient. Note from §4.3 that the effective
coefficient is the **average** of this and the particle's own friction (0.5), so this flag moves the
effective value only half as far as its nominal change.

### 7.6 Hold and release (`--hold auto|on|off`, `--release-frame N`, `--no-attachment`)

**What it does.**

- `--hold on`, and `auto` for every garment kind Seam simulates, sets `attachment_frames` to
  **`max_sim_steps + 1`**, so the release frame is unreachable and **attachments hold for the whole
  sim**. This exists because `pygarment`'s default release at frame 400 let both bottoms slide off
  Seam's mannequin.
- `--release-frame N` sets `attachment_frames` directly.
- `--no-attachment` sets `enable_attachment_constraint` false, which also drives `min_sim_steps` back
  toward zero.

**What the engine must offer.** A configurable release frame with no upper bound relative to the frame
cap, and a way to disable attachments entirely. Both are already implied by §6.10, but note the
interaction: because `min_sim_steps` is `attachment_frames + 5`, a hold set beyond the frame cap makes
`min_sim_steps` exceed `max_sim_steps`, so **the static test can never fire and every held run uses
its full frame budget** and is tagged `static_equilibrium`. That is the mechanism behind §8's
universal `static_eq` tag, and it is expected behaviour, not a failure.

### 7.7 A-pose

**What it does.** Tops are simulated on a body posed with the arms **45° from vertical** — GarmentCode's
A-pose, matching the pose its patterns are drafted for — while bottoms use the unposed body. The posed
body and its measurement file are generated on demand and cached under a pose-tagged name, and the
pattern is drafted against the same posed measurements. A later stage returns the draped garment to
the web pose.

**What the engine must offer.** Nothing beyond accepting an arbitrary static body triangle mesh with a
matching vertex segmentation. The pose is entirely upstream of the sim.

### 7.8 Resolution and caps

`--res` overrides `resolution_scale`, which feeds both the box-mesh vertex density and the fallback
stitch rest edge length (§3.3). `--max-steps` overrides `max_sim_steps`. `--frame-timeout` overrides
`max_frame_time`, and on macOS the value is **forced to null** because `pygarment`'s platform test
does not match what macOS reports (§2.4), which would otherwise skip the frame entirely.

### 7.9 Non-engine patches, listed for completeness

These are needed to run the pipeline but impose no engine requirement: a missing attribute is added to
an upstream warning path that would otherwise raise when `resolution_scale` produces two-vertex edges;
the unconditional image render is replaced with a no-op; and the layering experiment merges a draped
garment into the collision body by concatenating vertices and faces and extending the segmentation's
trunk vertex list — which only requires, again, that the body collider be an arbitrary triangle mesh
with a vertex segmentation.

---

## 8. Observable baselines worth reproducing

All figures are from Seam's committed results. They are the yardstick for "the port behaves like the
fork". **Note first that the simulation is not deterministic on GPU**: the same tee specification run
three times gave body-intersection counts of 151, 97 and 92, and one of the three settled at frame
2063 while the others did not settle at all. Treat every number below as a centre, not a target.

### 8.1 Timing, frames and memory

| Source | Hardware | Sim seconds per garment | Frames | Peak VRAM |
| --- | --- | --- | --- | --- |
| Four-item PoC | RTX 3090 | 35–56 | 2399 (cap) on all four | 564–666 MB |
| Size sweep (XS/M/L/XL hoodie) | RTX 3090 | 49.0 / 54.1 / 53.9 / 56.4 | 2399 | 628 / 650 / 666 / 684 MB |
| License spike | RTX 4090 | 23.25 (tee), 14.28 (sweats) | 2399 | 730 MB, 812 MB |
| Tee-fix and neckline rounds | A40 48 GB | 20–50, every run inside its budget | — | — |
| Held-attachment control | RTX 3090 | 26.2 (sweats), 26.4 (jeans), 36.8 (tee) | — | — |
| Layer test (hoodie over draped tee) | RTX 3090 | 88.1 | — | — |
| Re-drape on a taller body | RTX 3090 | 29.4, settled at frame 693 | 693 | — |

The published GarmentCodeData figure is about 30 seconds per garment on a 3090, so 35–56 seconds for
these garments is in family. Peak VRAM stays **under 0.7 GB** on the PoC items and under 0.9 GB on
the spike items, measured by sampling the GPU and cross-checked against the reported value — so a
24 GB card is almost entirely idle and several sims could share one.

### 8.2 Intersection counts

| Item | Body intersections | Self intersections | Tags |
| --- | --- | --- | --- |
| Sweats, default | 0 | 8063 | static_eq, self |
| Tee, soft | 151 | 493 | static_eq, body, self |
| Hoodie, soft_flexy | 378 | 1230 | static_eq, body, self |
| Jeans, stiff | 0 | 9079 | static_eq, self |
| Hoodie XS / M / L / XL | 616 / 377 / 378 / 251 | 942 / 773 / 1230 / 1255 | — |
| Tee (spike, 4090) | 159 | 2 | static_eq, body |
| Sweats (spike, 4090) | 0 | 3 | static_eq |
| Both bottoms, attachments held all frames | 0 | 0 | static_eq only |
| Layer test | 2731 | 12957 | — |

Three things in this table are the real acceptance signal:

1. **Held attachments give 0 body and 0 self intersections on both bottoms.** This is the cleanest
   available target: a port whose waist hold works and whose self-collision works should reproduce
   zero on both counters for a held bottom.
2. **Body contact falls monotonically with garment size** (616 → 377 → 378 → 251 from XS to XL) while
   **self contact rises** (942 → 1255). A bigger garment touches the body less and bunches more. A
   port that inverts either trend has a sign error somewhere in §4.
3. **The thresholds over-report.** Every run trips `static_equilibrium` (explained in §7.6), and the
   hoodie — the item Seam judged to read correctly, with hood, folds and ribbed cuffs — trips all
   three tags. The counts are useful as **relative** measures; the pass/fail tags are not a port
   acceptance criterion.

The zero-body-intersection rows for the unheld bottoms are a trap: they are zero because the garment
**left the body entirely** and fell (final Y from −22 to 14 cm for the sweats, −28 to 16 cm for the
jeans, with ground disabled per §6.26), not because it draped well. Always read the counts together
with the garment's final Y extent.

### 8.3 Behavioural baselines

- **Gravity-free stitching works**: panels close over the first frames and the garment is assembled
  before it is dropped.
- **Unheld bottoms slide off** this mannequin after the frame-400 release, on two different body
  shapes, and this was traced to release behaviour rather than sizing — the control with attachments
  held for all frames reads as "baggy cuffed track pants" and "wide-leg jeans".
- **The size ladder reads correctly**: XS fitted with tight sleeves and a hip-level hem, XL oversized
  with fuller longer sleeves, more folds and a lower hem.
- **Shoulder coverage is a measurement property, not a sim property.** Seam's shoulder failures were
  fixed entirely in the body measurement export, moving the shoulder seam from 3.5 cm below the
  acromion to 1.5–1.8 cm above it and taking cap coverage from 0–63 % to 100 % on every top in both
  poses, with no sim change. A port should not expect to fix placement problems in the solver.
- **Layering through a merged collision body does not work**: the hoodie slid down over the draped
  tee with the hood off the head, at 2731 body and 12957 self intersections.
- **Per-sim penetration fractions** on the final tops are 0.000–0.159 % of vertices, against a 0.1 %
  gate — so a well-behaved drape has essentially no residual penetration.

---

## 9. Provenance

### 9.1 Files opened to write this specification

The sim fork, at `/Users/anjelo/Github/seam-tee-collar/gen3d/drape/vendor/NvidiaWarp-GarmentCode`,
commit `63baf6855efdd89b2834b74640f84b3bb0d86b50` — read by this author only:

- `warp/sim/model.py`
- `warp/sim/collide.py`
- `warp/sim/integrator_xpbd.py`
- `warp/sim/integrator_euler.py`
- `warp/sim/utils.py`
- `warp/sim/particles.py`
- `warp/collision/panel_assignment.py`
- `warp/native/mesh.h`
- `warp/native/exports.h`
- `warp/builtins.py`

Upstream NVIDIA Warp at tag `v1.0.0-beta.6`, shallow-cloned into scratch purely to isolate the fork's
deltas, and deleted afterwards:

- `warp/sim/model.py`
- `warp/sim/collide.py`
- `warp/sim/integrator_xpbd.py`
- `warp/sim/integrator_euler.py`
- `warp/sim/particles.py`

`pygarment` / GarmentCode (MIT), at
`/Users/anjelo/Github/seam-newton/gen3d/drape/vendor/GarmentCode`, commit
`d449629979028123a5c4dc9e732a2ec19b7fce31`:

- `pygarment/meshgen/garment.py`
- `pygarment/meshgen/simulation.py` — carries an NVIDIA proprietary copyright header; implementers are
  forbidden to open it, which is why §2 specifies its behaviour in full
- `pygarment/meshgen/sim_config.py`
- `assets/Sim_props/default_sim_props.yaml`
- `README.md`

Seam's own code and documents, at `/Users/anjelo/Github/seam-newton/gen3d/drape`:

- `drape/drape.py`
- `drape/pattern.py`
- `drape/gates.json` — read only, to confirm its checksum is unchanged
- `LICENSE_SPIKE.md`
- `RESULTS.md`
- `RESULTS_TEE_FIX.md`
- `GPU_RUN.md`

External, for citation accuracy only:

- The GarmentCodeData paper and supplemental material (arXiv:2405.17609 v3; ECCV 2024), consulted to
  confirm the real section names cited in §0 rather than invent them.

`pygarment/meshgen/boxmeshgen.py` was **not** opened; the box mesh is treated here as an input whose
contract is given by the files it writes, which is all the engine port needs.

### 9.2 Statement

**This file contains no fork code.** It contains no code of any language: no code fences, no function
or kernel definitions, no pseudocode, no kernel bodies, and no variable-by-variable transcriptions of
fork formulas. Fork-internal kernel, helper and local-variable names are not used. The only
identifiers that appear are public API names that `pygarment` itself calls, configuration keys, and
Model and config field names that `pygarment` sets or reads — that is, the interface the Newton port
must provide. Numeric rules are stated as observable behaviour in standard notation and in the
author's own words. Where a feature implements a published method, the method is cited and only the
fork's deviation from it is described.

No fork contents were written to notes, temporary files or reports. The scratch directory used to
hold the upstream clone was deleted.
