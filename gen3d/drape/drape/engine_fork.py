from pathlib import Path

import yaml

FORK_HINT = (
    "--engine fork needs warp.sim, which only the NvidiaWarp-GarmentCode source build provides. "
    "Run it in the fork venv (on the GPU pod /workspace/seam/gen3d/drape/.venv) or pass --engine newton."
)

_installed = False
_run_sim = None


def install() -> None:
    global _installed, _run_sim
    if _installed:
        return
    try:
        from warp.sim import ModelBuilder
    except ModuleNotFoundError as exc:
        raise ImportError(FORK_HINT) from exc

    import pygarment.meshgen.simulation as sim_mod
    from pygarment.meshgen.garment import Cloth

    from drape import drape as driver

    sim_mod.render_images = lambda *a, **k: None
    _run_sim = sim_mod.run_sim

    _cloth_attach = Cloth._add_attachment_labels
    _cloth_build = Cloth.build_stage
    _cloth_update = Cloth.update
    _add_cloth_mesh = ModelBuilder.add_cloth_mesh_sewing_spring

    # --neck-hold: upstream pins the collar sideways, hold it above the neck base instead
    def _add_attachment_labels(self, builder, config):
        if driver.NECK["hold"] == "none":
            return _cloth_attach(self, builder, config)
        import numpy as np
        import warp as wp

        names = list(config.attachment_labels)
        config.attachment_labels = [n for n in names if n not in driver.COLLAR_LABELS]
        _cloth_attach(self, builder, config)
        config.attachment_labels = names
        labels = yaml.safe_load(Path(self.paths.g_vert_labels).read_text()) or {}
        for name in driver.COLLAR_LABELS:
            ids = labels.get(name) or []
            if not ids or name not in names:
                continue
            i = names.index(name)
            # slack below the neckline's own rest height: it may ride up, not drop
            level = float(np.asarray(self.v_cloth_init)[ids][:, 1].min()) - 0.5
            builder.add_attachment(
                ids, wp.vec3(0.0, level, 0.0), wp.vec3(0.0, 1.0, 0.0),
                stiffness=config.attachment_stiffness[i], damping=config.attachment_damping[i],
            )
            config.enable_attachment_constraint = True
            print(f"neck-hold {driver.NECK['hold']}: {name} {len(ids)} verts held above y={level:.2f}")
        config.update_min_steps()

    def _build_stage(self, config):
        driver.NECK["cloth"] = self
        _cloth_build(self, config)

    # --neck-stiff: warp takes per-triangle stiffness, raise it in the neckline band only
    def _add_cloth_mesh_sewing_spring(self, *a, **kw):
        n0 = len(self.tri_indices)
        out = _add_cloth_mesh(self, *a, **kw)
        cloth, factor = driver.NECK["cloth"], driver.NECK["stiff"]
        if not factor or cloth is None:
            return out
        labels = yaml.safe_load(Path(cloth.paths.g_vert_labels).read_text()) or {}
        ids = sorted({v for n in driver.COLLAR_LABELS for v in (labels.get(n) or [])})
        tris = self.tri_indices[n0:]
        hit = driver.neck_band_faces(self.particle_q, tris, ids)
        for i in hit:
            ke, ka, kd, drag, lift = self.tri_materials[n0 + i]
            self.tri_materials[n0 + i] = (ke * factor, ka * factor, kd, drag, lift)
        print(f"neck-stiff {factor}x: {len(hit)} of {len(tris)} faces "
              f"in the {driver.NECK_BAND_CM} cm neckline band")
        return out

    # --dump-every: cloth vertex positions per N frames, for the slide-frame metric
    def _update(self, frame):
        _cloth_update(self, frame)
        every = driver.NECK["dump"]
        if not every or frame < 0 or frame % every:
            return
        import numpy as np

        d = Path(self.paths.out)
        d.mkdir(parents=True, exist_ok=True)
        if not (d / "dump_faces.npy").exists():
            np.save(d / "dump_faces.npy", np.asarray(self.f_cloth))
        np.save(d / f"dump_f{frame:05d}.npy", np.asarray(self.current_verts))

    Cloth._add_attachment_labels = _add_attachment_labels
    Cloth.build_stage = _build_stage
    Cloth.update = _update
    ModelBuilder.add_cloth_mesh_sewing_spring = _add_cloth_mesh_sewing_spring
    _installed = True


def run_sim(*args, **kwargs):
    install()
    return _run_sim(*args, **kwargs)
