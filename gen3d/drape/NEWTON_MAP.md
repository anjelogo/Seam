# Newton 1.7.0 port map

Clean-room survey of Newton 1.7.0 (Apache-2.0) + PyPI warp-lang 1.18.0 against the cloth features
`pygarment` needs, written without reading the NVIDIA fork. Sources: the installed Newton and warp
packages, Newton's own examples, and the MIT pygarment call sites
(`vendor/GarmentCode/pygarment/meshgen/garment.py`, `meshgen/sim_config.py`,
`assets/Sim_props/default_sim_props.yaml`). Every API below was either executed (local CPU, macOS
arm64) or benchmarked (A40 pod); the numbers in [Solver decision](#solver-decision) are measured.

Paths are relative to `gen3d/drape/.venv/lib/python3.12/site-packages/`.

**Lead's note, after SIM_SPEC.md was cleared.** This survey was written before its author could read
the behaviour spec. Where they disagree, SIM_SPEC.md wins on behaviour and this file stays the API
locator. The solver decision is overridden (see [Solver decision](#solver-decision)), and four
routes below change:

- Half-space attachments (feature 5) are an XPBD constraint summed into the shared delta buffer,
  active only on the plane's negative side, multiplier not accumulated (SIM_SPEC §3.6), not a force.
- Body-part drag (feature 6) projects the full distance to the target surface; `cloth_reference_k` is
  never read (SIM_SPEC §4.6).
- Global viscous damping (feature 8) runs inside integration, between the velocity and position
  updates, as v ← v·exp(−factor·|v|·Δt) when |v| exceeds the effective velocity, then the cap
  (SIM_SPEC §4.2), not as a post-step factor.
- Body collision filters (feature 2) drop a particle's contact when its closest body face is filtered
  for that particle (SIM_SPEC §3.5, §4.3), so the body stays one shape with one closest-point query.

Headline: the port no longer needs a source build. The one fork feature that forced 112 lines of
CUDA — a segment-vs-mesh query — ships as a prebuilt warp builtin
(`wp.mesh_query_ray_anyhit`, `warp/__init__.pyi:7380`), and Newton ships a standalone cloth
self-collision detector (`TriMeshCollisionDetector`) that is callable outside its solvers.

## Conventions

| Thing | pygarment / fork | Newton 1.7.0 | Note |
| --- | --- | --- | --- |
| Length unit | cm (body obj ×100) | documented as metres, but unit-agnostic | keep cm; every stiffness/margin is read as-is |
| Up axis | y | **`Axis.Z` by default** | `ModelBuilder(up_axis=Axis.Y, gravity=(0.0, -9.81, 0.0))`, `newton/_src/sim/builder.py:1489` |
| Gravity | `model.gravity = np.array((0,-9.81,0))` | `wp.array[wp.vec3]`, one entry per world (+1 global), `model.py:1215` | ran verified: `-9.81` with cm lengths = 9.81 cm/s², exactly the fork's numerics. Change it with `model.gravity.assign(...)` / `fill_`, not by rebinding |
| World grouping | none | entities default to world `-1` (global) | measured: gravity and particle-shape contacts work with everything at `-1`; `begin_world()/end_world()` is optional here |
| Transforms | `pos=`, `rot=` args | single `xform: wp.transform` on shapes | `add_shape_mesh(body, xform=..., mesh=..., cfg=...)`, `builder.py:8424` |
| Body mesh | `wp.sim.Mesh(verts, indices)` | `newton.Mesh(vertices, indices, compute_inertia=False, is_solid=False)`, `newton/_src/geometry/types.py:133` | pass `compute_inertia=False` for a static collider; CCW winding is required (normals drive back-face culling) |
| Static collider | `add_shape_mesh(body=-1, ...)` | same, `body=-1` | verified |
| Kinematic particle | mass 0 | mass 0 → `particle_inv_mass` 0, plus `ParticleFlags.ACTIVE` in `model.particle_flags` (`geometry/flags.py:8`, `model.py:662`) | `add_cloth_grid` also has `fix_left/right/top/bottom` |
| Per-shape contact material | `thickness=`, `mu=` on `add_shape_mesh` | `ModelBuilder.ShapeConfig` (`builder.py:791`): `.margin` ← body_thickness 0.25, `.mu` ← body_friction 0.5, `.ke/.kd/.kf`, `.has_particle_collision` | `ShapeConfig.margin` is the outward collision offset, i.e. the fork's body thickness |
| Cloth↔body contact coefficients | `model.soft_contact_{ke,kd,kf,mu}` | identical global scalars, `model.py:1197` | 1:1 with the fork's 1000 / 10 / 1000 / 0.5 |
| `soft_contact_margin` 0.2 | `Model` field | **moved and renamed**: `CollisionPipeline(model, soft_contact_gap=0.2)` (`collide.py:1271`); `soft_contact_margin=` still accepted as a deprecated alias (`collide.py:1489`) | detection radius = particle radius + `ShapeConfig.margin` + `soft_contact_gap` |
| Collision | `wp.sim.collide(model, state, dt)` | `pipeline = newton.CollisionPipeline(model, ...)`, `contacts = pipeline.contacts()`, `pipeline.collide(state, contacts)` (`collide.py:1250/2009/2269`) | contacts are an explicit object now, allocated once; `Contacts` at `sim/contacts.py:118` |
| Step | `integrator.simulate(model, s0, s1, dt)` | `solver.step(state_in, state_out, control, contacts, dt)` | `control = model.control()` is required (may be empty) |
| Particle velocity clamp | fork patch applying `max_velocity` to position | **already upstream**: `apply_particle_deltas` clamps `v` then rewrites `x = x0 + v*dt` (`solvers/xpbd/kernels.py:836`); `model.particle_max_velocity` (`model.py:664`, default 1e5 → set 25) | the fork's fix #6 is unnecessary |
| Graph capture | `wp.capture_begin()/capture_end()` | `with wp.ScopedCapture() as cap: ...; cap.graph`, replay `wp.capture_launch(cap.graph)` | verified on the pod for XPBD, VBD and Style3D |

## Feature map

### 1. Cloth mesh with sewing

`ModelBuilder.add_cloth_mesh(pos, rot, scale, vel, vertices, indices, density, tri_ke, tri_ka,
tri_kd, tri_drag, tri_lift, edge_ke, edge_kd, add_springs, spring_ke, spring_kd, particle_radius,
...)` — `builder.py:11014`. Covers everything in the fork's `add_cloth_mesh_sewing_spring` call
**except the two sewing arguments** (`orig_lens`, `stitching_vertices`).

- Materials map 1:1: `tri_ke/tri_ka` 10000, `tri_kd` 1, drag/lift 0, `edge_ke` (1.0 default,
  presets 0.5/50), `edge_kd` 10, `density` 1.0, `particle_radius` ← fabric_thickness 0.1.
  Stored as `model.tri_materials` (`model.py:909`) and `model.edge_bending_properties`
  (`model.py:926`), both per-element and writable.
- `add_springs=True` builds springs over triangle edges **plus the two diagonals of every bending
  edge** (`builder.py:11158-11172`) — more springs than mesh edges alone (measured: 59 080 edges →
  117 600 springs on a 140×140 grid). Rest length comes from the initial configuration
  (`add_spring`, `builder.py:10313`).
- **Coverage: good / gap is sewing.** Route: no kernel needed. `builder.spring_rest_length` is a
  plain Python list before `finalize()` (verified) — build the mesh, then overwrite the entries whose
  particle pair is a stitched seam with the length from the boxmesh `*_orig_lens.pickle`, and raise
  only those springs to `spring_ke` 5e4 / `spring_kd` 10. Post-finalize the same array is
  `model.spring_rest_length` (`model.py:877`) and still writable, so a seam can be relaxed mid-sim.
  Add seam springs that are not mesh edges with `add_spring(i, j, ke, kd, control)` and then fix their
  rest length the same way.

### 2. Body contact

`add_shape_mesh(body=-1, mesh=newton.Mesh(...), cfg=ShapeConfig(...))` + `CollisionPipeline`.
Narrow phase is `create_soft_contacts` (`geometry/kernels.py:1137`): per (particle, shape) pair it
runs `mesh_query_point_sign` (`kernels.py:1001`) with
`max_dist = soft_contact_gap + ShapeConfig.margin/min_scale + particle_radius/min_scale`, keeps the
hit when `d < gap + margin + radius`, and signs `d` so an inside particle gives a negative distance.

- Coefficients: `ShapeConfig.ke/kd/kf/mu` per shape, `model.soft_contact_ke/kd/kf/mu` globally —
  both present, same meaning as the fork's.
- **Gap: the body collision filters.** The fork passes `face_filters` (per-body-face) and
  `model_particle_filter_ids` (per-cloth-particle) into `add_shape_mesh`; Newton has no such
  arguments. `add_shape_collision_filter_pair(shape_a, shape_b)` (`builder.py:2184`) filters
  *shape pairs*, not faces-vs-particles, so it does not substitute.
- Route: split the body into **several shapes instead of filtering faces** — one
  `add_shape_mesh` per body part (arms, legs, torso, and one for `face_internal`) using
  `assign.extract_submesh`-style submeshes, then give the parts that must be ignored
  `ShapeConfig.collision_group = 0` or `has_particle_collision = False` for the groups that need
  them off. Where a filter must be per-particle rather than per-shape, the cheap route is a custom
  particle attribute + our own kernel that zeroes those contact records between
  `pipeline.collide()` and `solver.step()`; the contact arrays (`contacts.soft_contact_particle`,
  `soft_contact_shape`, `soft_contact_count`) are public (`contacts.py:403-433`).

### 3. Body collision constraint (push cloth found inside the body back out)

Not in Newton. Newton's own particle-mesh contact silently misses deep penetration: the
closest-point query is bounded by `max_dist` (0.55 cm with our numbers), so a particle more than
that inside the body generates no contact at all — confirmed by reading `create_soft_contacts` and
reproduced locally.

- Route: **our own warp kernel**, one thread per particle, using
  `wp.mesh_query_point_sign_winding_number(mesh_id, p, max_dist, accuracy, threshold)`
  (`warp/__init__.pyi:7259`) on a `wp.Mesh` built with `support_winding_number=True`. Its sign
  classification examines the whole mesh and **is not bounded by `max_dist`**, so it answers
  inside/outside for arbitrarily deep particles; `face`/`u`/`v` + `wp.mesh_eval_position` give the
  surface point to project onto. Verified running locally.
- Cheaper alternatives if the winding number proves slow: `wp.mesh_query_point_sign_parity`
  (`:7051`, correct for watertight meshes), `wp.mesh_query_ray_count_intersections` (`:7424`, ray
  parity), or `mesh_query_point_sign_normal` (`:7205`). Newton's own enum for this choice is
  `MeshSignMethod` (`geometry/flags.py:48`).

### 4. Self-collision

Two independent routes, both built in.

- **In-solver (recommended):** `SolverVBD(..., particle_enable_self_contact=True,
  particle_self_contact_margin=..., particle_self_contact_gap=...)`
  (`solvers/vbd/solver_vbd.py:363`). It covers point-triangle **and** edge-edge in one pass
  (`accumulate_self_contact_force_and_hessian`, `solver_vbd.py:3887`) and adds a
  Divide-and-Truncate step that makes the result penetration-free. Extra knobs the fork does not
  have: `particle_topological_contact_filter_threshold` (skip n-ring neighbours),
  `particle_rest_shape_contact_exclusion_radius`, and
  `particle_external_{vertex,edge}_contact_filtering_map` — the last is the natural home for the
  fork's global collision filter.
- **Standalone:** `newton.geometry.TriMeshCollisionInfo` and
  `newton._src.geometry.tri_mesh_collision.TriMeshCollisionDetector`
  (`geometry/tri_mesh_collision.py:30/371`), with `vertex_triangle_collision_detection()` (`:913`),
  `edge_edge_collision_detection()` (`:974`), `triangle_triangle_intersection_detection()`
  (`:1020`), `refit()` (`:888`) and `set_collision_filter_list()` (`:735`). It lives in the
  geometry layer precisely so the sim layer can use it without importing a solver, and it
  constructed successfully outside any solver in our local run. Filters can be generated with
  `build_vertex_n_ring_tris_collision_filter` (`:207`) and
  `build_edge_n_ring_edge_collision_filter` (`:237`).
- Particle-particle contact (off by default in the fork) exists only in XPBD
  (`solve_particle_particle_contacts`, `solvers/xpbd/kernels.py:246`, needs
  `model.particle_grid.build(...)`). Leaving it off, as the fork does, costs nothing.
- `SolverStyle3D` has its own always-on self-collision with a private BVH
  (`Collision`, `solvers/style3d/collision/collision.py:21`, wired at `solver_style3d.py:138`);
  it cannot be split into point-triangle / edge-edge toggles.
- `SolverSemiImplicit` has `eval_triangle_contact_forces` (`semi_implicit/kernels_contact.py:644`),
  a force-level triangle-particle self contact — the closest analogue to the fork's
  `enable_triangle_particle_collisions` outside VBD.

### 5. Attachments (pin and half-space)

- **Equality / pin:** `ModelBuilder.add_attachment_particle_body(particle, body, body_point=...,
  stiffness=1e4, damping=0.0, enabled=True)` — `builder.py:10234`. Compliant (quadratic penalty),
  translational, and **implemented only by `SolverVBD`** (and the experimental coupled ADMM
  solver); its docstring says so explicitly. It needs a rigid body, so pinning to a world point
  means `add_body()` for a static anchor. `model.attachment_particle_body_enabled`
  (`model.py:898`) is a device array, so the fork's `attachment_frames` release is a
  `fill_(False)` — no model rebuild, but it does invalidate a captured graph.
- Alternative that works in every solver: a zero-rest-length `add_spring` to a mass-0 particle
  placed at the target point. Stiffness/damping map directly onto the fork's 1000 / 10.
- **Inequality / half-space (waist `y ≥ waist_level`, collars `x ≤ ∓neck_w/2`): not in Newton at
  all.** This is the fork's `add_attachment(verts, point, normal, stiffness, damping)` with a
  one-sided test, and it is what keeps bottoms on our mannequin (`RESULTS.md`, held attachments)
  and what `drape.py`'s `--neck-hold` uses.
  Route: **our own warp kernel**, ~30 lines — one thread per constrained particle, evaluate
  `s = dot(p - point, normal)`, and when `s < 0` add `stiffness * (-s) * normal` to
  `state.particle_f` plus a damping term. With VBD a force-only kernel is not enough (VBD solves
  per-vertex Newton steps, not forces), so either write it as a position projection applied after
  `solver.step()` or carry it as an extra force/hessian contribution; the simplest correct form is
  a post-step clamp of the violating particles, which is what the constraint physically is.

### 6. Body-part drag (panel → body-part assignment, pull free)

Nothing in Newton: no `panel_assignment`, no `cloth_reference_*`. `add_cloth_reference_shape_mesh`
and `add_cloth_reference_labels` have no counterpart.

- Route: **ours, mostly Python plus one kernel.** The assignment itself (panel label → body part,
  per-particle reference label, submesh extraction) is CPU numpy/igl work that never touched warp
  internals, so it is a straight rewrite against our own body segmentation
  (`runs/bodies/ggg_body_segmentation.json`). The drag is then one kernel per frame: for each
  particle with a reference label, query that part's `wp.Mesh` with
  `wp.mesh_query_point_sign_winding_number` (or `mesh_query_point_no_sign`, `:7116`, when the
  part submesh is open), and if the particle is inside or within `cloth_reference_margin` 0.1,
  push it toward the closest surface point with `cloth_reference_k` 1e7. One `wp.Mesh` per body
  part; the parts are static, so they are built once.

### 7. Edge/segment vs mesh intersection counters

**The fork's native `mesh_query_edge()` is not needed.** warp 1.18.0 ships
`wp.mesh_query_ray_anyhit(id, start, dir, max_t)` (`warp/__init__.pyi:7380`), documented as
returning as soon as any face within `max_t` is found. Normalising `dir` and passing
`max_t = |edge|` is exactly a segment-vs-triangle-mesh test, which is all the two counters need.

- `count_body_cloth_intersections` → one thread per cloth spring/edge, `mesh_query_ray_anyhit`
  against the body `wp.Mesh`, `wp.atomic_add` into a counter. Written and **ran locally** against
  `wearer_masc_a45.obj` (9 630 verts / 19 232 tris) over ~20 k segments.
- `count_self_intersections` → either the same trick against a `wp.Mesh` rebuilt from the cloth
  each time it is measured, or better,
  `TriMeshCollisionDetector.triangle_triangle_intersection_detection()`
  (`tri_mesh_collision.py:1020`), which is Newton's own triangle-triangle intersection pass and
  needs no extra mesh. `wp.intersect_tri_tri` (`:8042`) is the underlying builtin if we want our
  own count.
- Also available and prebuilt: `mesh_query_ray` with `max_t` (`:7323`),
  `mesh_query_ray_count_intersections` (`:7424`), `mesh_query_aabb` (`:7482`),
  `bvh_query_aabb/ray/sphere/capsule` (`:6313/6361/6412/6466`), `closest_point_edge_edge`
  (`:8277`).

### 8. Integration extras

| Fork behaviour | Newton |
| --- | --- |
| `particle_max_velocity` 25 applied to positions | **built in**: `model.particle_max_velocity` (`model.py:664`) + `apply_particle_deltas` (`solvers/xpbd/kernels.py:836`). VBD applies the same limit in its own update |
| `global_viscous_damping` (factor 0.25, effective vel 0, max vel 25) | **absent** — no `global_viscous_damping`, no particle drag field anywhere in Newton (grepped). Route: our own kernel, one thread per particle, run on `state.particle_qd` after `solver.step()`: `if |v| > v_eff: v *= (1 - factor)`, then clamp to `v_max`. ~10 lines, graph-capturable. Partial substitutes that already exist: `tri_kd`, `edge_kd`, `spring_kd` |
| gravity 0 for 10 frames, then −9.81 | `model.gravity.assign(...)` / `fill_(...)` (`model.py:1903-1918`) |
| 60 fps × 10 substeps, ~2400 frames | plain Python loop; dt is a `step()` argument |
| per-frame CUDA graph, recaptured on gravity/attachment change | `wp.ScopedCapture`; recapture on the same events. Gravity and `attachment_particle_body_enabled` are device arrays, so writing them does **not** require recapture — but it does require the write to happen outside the graph, or the old value is baked in |

### 9. Body smoothing and mesh point replacement

- `implicit_laplacian_smoothing`: absent. Route: ours, pure CPU numpy/scipy (cotangent Laplacian,
  one sparse solve per step) — it never used warp. Off in our config
  (`enable_body_smoothing: false`), so this is the lowest-priority item.
- `replace_mesh_points` + BVH refit: **built in** at the warp level —
  `mesh.points.assign(new_points)` then `mesh.refit()`. Verified locally. Newton's own
  `TriMeshCollisionDetector.refit()`/`rebuild()` (`tri_mesh_collision.py:888/851`) and
  `SolverStyle3D.rebuild_bvh(state)` (`solver_style3d.py:371`) are the equivalents on the cloth
  side.

### 10. Seam's own patches

| `drape.py` flag | Newton route |
| --- | --- |
| `--neck-stiff` (per-triangle stiffness multiplier on neckline faces) | direct: `model.tri_materials` is a per-triangle `wp.array2d` (`model.py:909`); scale rows in place, or pass per-triangle lists to `add_triangles(tri_ke=[...], tri_ka=[...])` (`builder.py:10456`) |
| `--dump-every` (vertex dumps) | `state.particle_q.numpy()` — unchanged |
| material presets (tri_ke/ka, edge_ke) | unchanged, same field names |
| `--body-friction` | `ShapeConfig.mu` per body shape, or `model.shape_material_mu` (`model.py:706`) post-finalize |
| `--neck-hold` / `--release-frame` | rides on feature 5; the hold itself is the half-space kernel |
| A-pose body | pattern/body stage, no sim API involved |

## Solver decision

**Decision (lead): our own XPBD substep loop on Newton's XPBD kernels, not `SolverVBD`.** The survey
below recommended VBD. SIM_SPEC.md removed its premise:

- The fork's XPBD has no triangle constraint either (SIM_SPEC §3.3). `tri_ke`/`tri_ka` are inert,
  and all in-plane behaviour is the spring net (triangle edges plus bending-pair diagonals at
  `spring_ke` 5e4). That is exactly what Newton's XPBD solves. VBD and Style3D would switch on a
  membrane FEM and change the drape, against a shape target of 0.306 cm (2 × the re-measured fork
  noise floor of 0.153 cm).
- Newton's XPBD particle kernels match the fork's described behaviour term by term:
  - `solve_springs` (`solvers/xpbd/kernels.py:320`) and `bending_constraint` (`:386`) use
    compliance 1/(k·Δt²) and damping c/(k·Δt);
  - `solve_particle_shape_contacts` (`:121`) averages particle and shape friction, skips contacts
    beyond `particle_adhesion` and applies the 0.9 relaxation;
  - `apply_particle_deltas` (`:836`) caps the speed and rewrites the position.
- The XPBD rows in the table below don't represent our garments. The test sheet had ~0.26 cm
  cells, so particle masses (density × area ÷ 3) were roughly 15× smaller than on a ~1 cm boxmesh,
  and the same `spring_ke` acted far stiffer. The fork also runs 1 iteration per substep
  (SIM_SPEC §1.5), not 2 or 10. Real-garment numbers come from the port (RESULTS_NEWTON.md).

So the backend uses Newton's `ModelBuilder`, `Model`, `State`, mesh queries, and its XPBD contact,
spring, bending and delta kernels. Our own warp kernels cover the rest:

- once-per-frame body contact generation with face filters and the inside flag;
- the piercing survey;
- predictive point–triangle and edge–edge self-contact;
- body-part drag and the inside-body push-out;
- half-space attachments;
- the damped integration step.

All of it runs in the fork's order (SIM_SPEC §4.1). `SolverXPBD.step` itself is not called, because
the fork's extra constraints must sum into the same delta buffer before one `apply_particle_deltas`.

S2's micro-benchmark, kept for the record (flat sheet, see the caveat above). Measured on the pod (A40 48 GB, warp 1.18.0 / newton 1.7.0), 19 881 cloth
particles / 39 200 triangles / 59 080 bending edges / 117 600 springs, dropped on
`wearer_masc_a45.obj` scaled to cm, `CollisionPipeline(soft_contact_gap=0.2)`,
`ShapeConfig.margin=0.25`, one CUDA graph per frame, 400 timed frames:

| solver | substeps × iters | self-contact | ms/frame | 2400 frames | peak VRAM | drape at +100 frames |
| --- | --- | --- | --- | --- | --- | --- |
| XPBD | 10 × 2 | — | 3.22 | 7.7 s | 401 MB | **none**: sheet locked at y 174.4–176.1, 0 body contacts |
| XPBD | 10 × 10 | — | 11.22 | 26.9 s | 405 MB | **none**: y 173.0–178.7 after 25 s of sim, still flat |
| VBD | 10 × 10 | off | 23.68 | 56.8 s | 379 MB | drapes, y 120.4–175.1 |
| VBD | 2 × 10 | off | 4.89 | 11.7 s | 369 MB | drapes but slides off (y → −0.6) |
| VBD | 2 × 10 | **on** | 15.87 | 38.1 s | 401 MB | drapes, slides (y 39.8–82.4) |
| VBD | 4 × 10 | **on** | 34.19 | 82.1 s | 405 MB | drapes and settles, y 122.8–174.6 |
| VBD | 10 × 10 | **on** | 82.47 | 197.9 s | 417 MB | drapes and settles, y 122.4–175.0 |
| Style3D | 2 × 10 | always on | 11.52 | 27.7 s | 447 MB | drapes and settles, y 119.5–175.2 |

Budget is ≤2× the fork's 20–55 s per item and ≤4 GB. Every configuration is ~0.4 GB, so VRAM is a
non-issue; the choice is cost versus coverage.

The rest of this section is S2's original argument. The lead's decision above supersedes it; it
stays here because the measurements are real.

**Why VBD and not XPBD (superseded).** This is not a speed argument, it is a correctness one.
Newton's XPBD has **no triangle constraint at all** — its particle path is springs
(`solvers/xpbd/kernels.py:320`), bending (`:386`), particle-shape contacts (`:121`) and
particle-particle contacts (`:246`), and nothing reads `model.tri_materials`. So the fork's whole
stretch/shear material (`garment_tri_ke`/`garment_tri_ka` 10000, the only knobs our presets move)
is silently ignored, and the cloth becomes a spring net at `spring_ke` 5e4. Measured consequence:
the sheet behaves as a rigid membrane that never conforms to the body and never sags, at 2 and at
10 iterations, over 25 s of simulated time. XPBD also has no self-contact and no attachment
support. It is the wrong target even though it is the fastest number in the table.

**Why VBD fits.**

- It is the only solver that reads the fork's full material set: `tri_materials` and
  `edge_bending_properties` in `solve_elasticity` (`solver_vbd.py:3949`), and springs with
  explicit `spring_rest_length` in `accumulate_spring_force_and_hessian` (`solver_vbd.py:3867`,
  kernel at `particle_vbd_kernels.py:1706`) — which is exactly where our sewing rest lengths land.
- It is the only solver that implements `add_attachment_particle_body`, i.e. feature 5's equality
  half.
- Its self-contact is point-triangle **and** edge-edge in one switch, penetration-free by
  construction, with topological and external filters — a superset of the fork's two toggles plus
  its global filter.
- Cost: 38 s/2400 frames at 2 substeps, 82 s at 4. The fork takes 20–50 s on this same A40
  (`RESULTS_TEE_FIX.md`). So 2 substeps is comfortably inside 2× and 4 substeps sits at its edge.
  Real garments are not flat sheets and have held attachments, so the substep count needed for
  stability has to be re-measured on a real boxmesh before fixing it.

**Compliance vs stiffness, against the fork.** The fork is XPBD, where `spring_ke`/`edge_ke` enter
as compliance `1/k` inside a position projection. VBD is implicit Newton per vertex: the same
`k` enters a quadratic energy, and damping is absolute rather than a per-substep factor. So
identical numbers will not give identical drape — expect to re-tune `tri_ke/tri_ka`, `edge_ke` and
`spring_ke` once against the fork's reference drapes (mean surface distance ≤ 2 × 1.35 cm), rather
than porting the yaml values and assuming they hold. Our material presets
(`stiff`/`soft`/`jersey`) are the natural place for the retune.

**Style3D is the documented fallback, and may end up better.** `SolverStyle3D`
(`solvers/style3d/solver_style3d.py:36`) is the solver Newton's own garment-on-body example uses
(`newton/examples/cloth/example_cloth_h1.py`), it is the fastest configuration that actually
drapes (27.7 s), it was the most stable at low substeps in our run, and its cloth is authored in
**panel space**: `style3d.add_cloth_mesh(builder, panel_verts=<2D UVs>, panel_indices=...,
tri_aniso_ke=(weft, warp, shear), edge_aniso_ke=...)` (`solvers/style3d/cloth.py:180`) — which is
precisely what a pygarment boxmesh already carries. It even has sewing machinery internally
(`compute_sew_v`, `cloth.py:540`), though it is not exposed through the public helper. Against it:
no attachment support (so feature 5 becomes entirely ours), self-collision is always on with no
per-type toggles, it needs `SolverStyle3D.register_custom_attributes(builder)` before the cloth is
added, and it makes host-side calls (PCG dot products, BVH refit) so CPU graph capture is
impossible — CUDA capture worked. Worth a second measurement on a real boxmesh once one exists;
if VBD's substep cost or stability disappoints, this is where to go.

`SolverSemiImplicit` (`solvers/semi_implicit/solver_semi_implicit.py:34`) covers every material
(`eval_spring_forces`, `eval_triangle_forces`, `eval_bending_forces`) and has a triangle-particle
self contact, but it is explicit, so it needs far smaller timesteps. Not measured; not recommended.

**If we end up on a solver without built-in self-contact**, the detector is portable:
construct `TriMeshCollisionDetector(model)` ourselves, call `refit()` +
`vertex_triangle_collision_detection()` + `edge_edge_collision_detection()` once per frame, and
read the public CSR buffers (`vertex_colliding_triangles`, `edge_colliding_edges`, and their
`*_offsets` / `*_count` / `*_min_dist`) in our own response kernel. That is how VBD itself uses it
(`solver_vbd.py:1071`).

## Pitfalls

- **Up axis.** `ModelBuilder` defaults to `Axis.Z`. Forgetting `up_axis=Axis.Y` puts gravity along
  the wrong axis and the body mesh on its side.
- **`add_shape_mesh` signature changed.** `pos=`/`rot=` are gone (one `xform=`), `thickness=` and
  `mu=` moved into `cfg: ShapeConfig` (`.margin`, `.mu`), and `face_filters` /
  `model_particle_filter_ids` do not exist. `scale` is a `Vec3`.
- **`soft_contact_margin` moved off `Model`** onto `CollisionPipeline` and was renamed
  `soft_contact_gap`; the old name still works but warns (`collide.py:1489`).
- **`builder.color()` is required for VBD and is not implicit.** `finalize()` does not colour the
  model (`builder.py:12152`); VBD raises without `particle_color_groups`. Call
  `color(include_bending=True)` when bending edges are active. Two traps: the colouring graph is
  built from triangles and (optionally) bending edges only — **springs are never in it**
  (`builder.py:12212`), so `add_cloth_mesh`'s diagonal springs can join two same-colour particles
  and degrade to Jacobi-like convergence; and triangles with `tri_ke * tri_ka == 0` are dropped
  from the graph entirely.
- **Contact count reads 0 in steady state under XPBD.** Resolved contacts are pushed to exactly
  `gap + margin + radius`, and detection uses a strict `<` (`geometry/kernels.py` in
  `create_soft_contacts`), so a settled garment can report zero body contacts while still being
  supported. Do not build the intersection/quality metrics on `contacts.soft_contact_count`; use
  feature 7's own counters.
- **Deep penetration is invisible to the contact pipeline** (feature 3). Anything more than
  `gap + margin + radius` (0.55 cm with our numbers) inside the body generates no contact, so a
  garment that starts intersecting the body stays intersecting. The fork's reference drag and
  inside-projection are not optional extras; they are what makes initialisation work.
- **Graph capture.** Use an even number of substeps when swapping `state_in`/`state_out` inside the
  captured region, or the ping-pong ends on the wrong buffer (Newton's own example notes this).
  Recapture when the *structure* changes; plain value writes to device arrays
  (`model.gravity`, `attachment_particle_body_enabled`, `tri_materials`) must happen outside the
  graph but need no recapture. VBD grows some buffers lazily on first `step()`, and with
  `rigid_contact_history=True` that allocation must happen before capture — build
  `CollisionPipeline` → `contacts()` → solver, then run one uncaptured step, then capture.
  `SolverStyle3D` makes host calls, so CPU capture is impossible.
- **First-run kernel compile.** With a warm warp cache, XPBD and plain VBD were ~0.1–0.2 s to first
  frame on the pod. Cold paths cost real time: VBD's self-contact kernels took 6.9–9.5 s
  (constructor + first frame) and Style3D 17 s. On a cold `~/.cache/warp` expect the ~90 s figure
  from the earlier VBD run; cache the directory on the pod image.
- **`newton-physics` on PyPI is a rename stub.** The installable package is `newton` (already in
  `LICENSE_SPIKE.md`).
- **Newton's public API is re-exported from `newton/_src/`.** `newton.ModelBuilder`,
  `newton.Mesh`, `newton.CollisionPipeline`, `newton.solvers.Solver*`,
  `newton.geometry.TriMeshCollisionInfo` are public; `TriMeshCollisionDetector` is reachable only
  as `newton._src.geometry.tri_mesh_collision.TriMeshCollisionDetector` (also re-exported from
  `newton._src.solvers.vbd.tri_mesh_collision`), so that one import is on a private path and may
  move.

## What we have to write ourselves

In order of how much they block a working drape:

1. **Half-space (inequality) attachment** — feature 5. No Newton equivalent; it is what holds
   bottoms at the waist and the collar. One small kernel plus the release logic.
2. **Body-inside projection and body-part reference drag** — features 3 and 6. The contact
   pipeline cannot see deep penetration, so without these the garment starts and stays
   intersecting. Built on `wp.mesh_query_point_sign_winding_number`, one `wp.Mesh` per body part.
3. **Global viscous damping** — feature 8. Ten lines on `state.particle_qd`, but the fork's
   factor 0.25 is load-bearing for stability at 10 substeps, so it is not optional.

Then, smaller: per-particle body-face filtering (feature 2, if splitting the body into shapes is
not enough), the two intersection counters (feature 7, thin wrappers over
`mesh_query_ray_anyhit` and `triangle_triangle_intersection_detection`), and the Laplacian body
smoothing (feature 9, CPU-only and off in our config).

No custom CUDA builtin is needed, and neither warp nor Newton has to be built from source.

## Reproducing the measurements

Local API checks ran from `gen3d/drape` with `uv run --no-sync python <scratch>/probe_api.py
runs/bodies/wearer_masc_a45.obj` (CPU, no GPU). The pod benchmark ran as
`flock /workspace/seam/.gpu.lock /workspace/seam/gen3d/drape/.venv-newton/bin/python bench.py
--solver {xpbd,vbd,style3d} --substeps N --iterations M [--self-contact] --frames 400` from
`/workspace/s2`. Both scripts were scratch and are deleted; the configurations are fully described
by the table above and this document's conventions section.
