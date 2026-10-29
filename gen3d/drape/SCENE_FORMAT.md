# Portable sim scene format

One scene = `<name>_scene.npz` + `<name>_scene.json`, written by `python -m drape.scene export` at the
moment the Newton backend has finished `build_scene` and before frame 0. It carries every array and
setting the cloth sim reads, so a sim engine needs only `numpy` to load it. Both `--engine newton
--scene` and `drape.sim_taichi.run --scene` start from these bytes.

Units cm, y-up, seconds. Floats are little-endian `float32`, indices `int32`, unless noted. Arrays are
taken from the finalized Newton model and context, not recomputed, so they are exactly what Newton
simulates.

## npz arrays

V particles, F cloth triangles, S springs, E bending elements, B body vertices, BF body faces,
A attachment entries, R reference shapes.

| key | shape, dtype | source |
| --- | --- | --- |
| `x0` | (V,3) f32 | `model.particle_q` at build (cloth box mesh, y-shifted) |
| `v0` | (V,3) f32 | `model.particle_qd` at build (zeros) |
| `mass` | (V,) f32 | `model.particle_mass` |
| `inv_mass` | (V,) f32 | `model.particle_inv_mass` |
| `radius` | (V,) f32 | `model.particle_radius` |
| `flags` | (V,) i32 | `model.particle_flags` (bit 0 = active) |
| `faces` | (F,3) i32 | cloth triangles, box-mesh order |
| `tri_ke`, `tri_ka`, `tri_kd` | (F,) f32 | per-triangle stiffness after overrides (`--neck-stiff`); no XPBD pass reads them (SIM_SPEC §3.3) |
| `tri_rest_pose` | (F,2,2) f32 | rest basis incl. stitch triangles |
| `tri_rest_area` | (F,) f32 | rest area incl. stitch triangles |
| `springs` | (S,2) i32 | `model.spring_indices` |
| `spring_rest` | (S,) f32 | `model.spring_rest_length` (sewing lengths applied) |
| `spring_ke`, `spring_kd` | (S,) f32 | `model.spring_stiffness`, `model.spring_damping` |
| `bend` | (E,4) i32 | `model.edge_indices` (i_opp, j_opp, k, l) |
| `bend_rest` | (E,) f32 | `model.edge_rest_angle` |
| `bend_ke`, `bend_kd` | (E,) f32 | `model.edge_bending_properties[:,0]`, `[:,1]` |
| `stitch` | (K,) i32 | stitching vertex ids |
| `panel_id` | (V,) i32 | index into json `panels`, -1 for stitch-only vertices |
| `body_v` | (B,3) f32 | body collider points (x100, y-shifted, smoothing start shape) |
| `body_f` | (BF,3) i32 | body faces |
| `face_filters` | (nfilt,BF) u8 | `ctx.face_filters`; nonzero = face hidden from that filter id |
| `particle_filter_id` | (V,) i32 | `ctx.particle_filter_id`, -1 = no filter |
| `ref_v` | (sum,3) f32 | reference-shape submesh points, concatenated |
| `ref_f` | (sum,3) i32 | reference-shape faces, local to their shape |
| `ref_v_off`, `ref_f_off` | (R+1,) i32 | offsets into `ref_v` / `ref_f` |
| `ref_label` | (V,) i32 | `ctx.ref_label`, -1 = none |
| `allow_pairs` | (P,2) i32 | `ctx.allow_pairs` |
| `att_particle` | (A,) i32 | attachment particle |
| `att_point`, `att_normal` | (A,3) f32 | target point; unit normal, zero = equality |
| `att_ke`, `att_kd` | (A,) f32 | stiffness, damping |
| `smooth_frames` | (K,) i32 | body smoothing frames; absent when smoothing is off |
| `smooth_verts` | (K,B,3) f32 | body points to load on each of those frames; absent when off |
| `boxmesh_obj` | (bytes,) u8 | the box-mesh OBJ text; `*_sim.obj` is written by replacing its `v` lines |

## json

| key | meaning |
| --- | --- |
| `format` | `"seam-scene/1"` |
| `name`, `item`, `body` | garment name, item id, sim body name |
| `build_error` | `null`, or a fail tag raised while building (`gt_edges_creation`); then the npz is absent |
| `sim` | every scalar the loop reads (below) |
| `panels` | panel names, indexed by `panel_id` |
| `ref_names` | reference shape names, indexed by `ref_label` |
| `vertex_labels` | garment vertex labels (`lower_interface`, collars, ...) |
| `body_seg` | body segmentation, name to vertex ids |
| `record` | the timing record fields known before the sim (`resolution_scale`, `meshgen_s`, `material`, `label_verts`, `flags`) |
| `sha256` | per npz key, of the raw array bytes |

`sim` keys: `fps`, `substeps` (10), `iterations` (1), `frame_dt`, `sub_dt`, `detect_dt` (sub_dt ×
substeps as computed), `gravity` (applied from `zero_gravity_steps` on, zero before), `zero_gravity_steps`,
`max_sim_steps`, `min_sim_steps`, `attachment_enabled`, `attachment_frames` (release frame),
`max_frame_time` (null = off), `max_sim_time`, `static_threshold`, `non_static_percent`,
`max_body_collisions`, `max_self_collisions`, `damping` ([factor, effective velocity, max velocity]),
`particle_max_velocity`, `body_thickness`, `soft_contact_margin`, `body_mu` (shape friction),
`particle_mu`, `particle_adhesion`, `soft_contact_relaxation` (0.9), `self_contact_relaxation` (1.0),
`soft_contact_max`, `pt_per_particle`, `ee_per_spring`, `pt_query_radii`, `detect_band_radii`,
`cloth_reference_margin`, `ray_axes`, `enable` (`cloth_reference_drag`, `global_collision_filter`,
`triangle_particle_collisions`, `edge_edge_collisions`, `body_collision_filters`, `body_smoothing`),
`dump_every` (null = off).

## Gravity semantics (as implemented)

`model.gravity` is a `(1,) vec3f`: one entry per world, not per particle. All cloth particles share
world 0 (`model.particle_world = zeros(V, i32)`), so the integrate kernel reads a single global
vector. At build the model is created with gravity zero. The solver flips it to the scene's `gravity`
value at frame `== zero_gravity_steps`; the json `gravity` is that on-value, not what sits in
`model.gravity` at build. The gate inside the integrate kernel is `gravity * wp.step(-inv_mass)`;
warp's `wp.step(x)` returns `1.0 if x < 0.0 else 0.0`, so finite-mass particles (inv_mass > 0, hence
-inv_mass < 0) receive gravity, and fixed particles (inv_mass == 0) do not.

`bend_rest` is zeros on every cloth we have exported: `add_cloth_sewing` builds bending with
`rest=[0.0]*n_e` (flat everywhere, SIM_SPEC §3.3). It is stored anyway so a future non-flat rest
would ride through unchanged.

`ref_v_off` and `ref_f_off` have `R+1` entries each; the submesh for ref `r` is
`ref_v[ref_v_off[r]:ref_v_off[r+1]]` and `ref_f[ref_f_off[r]:ref_f_off[r+1]]`, with face indices
already local to that submesh.

`smooth_frames` / `smooth_verts` are omitted entirely (not just empty) when body smoothing is off,
which is the default in `default_sim_props.yaml`.

## Run output

`--out` is a run's `<part>/<safe>/sim` directory, the layout `drape.parity`, `drape.coverage` and
`drape.sheet` read, the same as `drape.drape` writes:

- `<out>/<name>/<name>_sim.obj`
- `<out>/<name>/`: the spec, box mesh, labels and segmentation copied from the scene's directory
- `<out>/dump_faces.npy`, `<out>/dump_f{frame:05d}.npy` when `dump_every` is set
- `<out>/<name>/sim_record.json`: the timing record (`sim_s`, `spf`, `frames`, `body_collisions`,
  `self_collisions`, `fails`, `vram_mb`, `device`, overflow totals, NaN count), also appended to
  `--timings` (a run's `<part>/timings.json`) when given

Export a reference run's own box mesh instead of re-meshing with `--reuse-mesh` after copying its
`pattern/` and `sim/<name>/` files in: the mesher's float output differs across machines in the last
digits, and in vertex order across environments, so scenes built against a reference must reuse it.
