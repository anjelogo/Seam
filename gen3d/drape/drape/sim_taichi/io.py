from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class SceneFormatError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Scene:
    arrays: dict[str, np.ndarray]
    meta: dict[str, Any]

    @property
    def sim(self) -> dict[str, Any]:
        return self.meta["sim"]


_DTYPES = {
    "x0": "<f4", "v0": "<f4", "mass": "<f4", "inv_mass": "<f4", "radius": "<f4",
    "flags": "<i4", "faces": "<i4", "tri_ke": "<f4", "tri_ka": "<f4", "tri_kd": "<f4",
    "tri_rest_pose": "<f4", "tri_rest_area": "<f4", "springs": "<i4", "spring_rest": "<f4",
    "spring_ke": "<f4", "spring_kd": "<f4", "bend": "<i4", "bend_rest": "<f4",
    "bend_ke": "<f4", "bend_kd": "<f4", "stitch": "<i4", "panel_id": "<i4", "body_v": "<f4",
    "body_f": "<i4", "face_filters": "|u1", "particle_filter_id": "<i4", "ref_v": "<f4",
    "ref_f": "<i4", "ref_v_off": "<i4", "ref_f_off": "<i4", "ref_label": "<i4",
    "allow_pairs": "<i4", "att_particle": "<i4", "att_point": "<f4", "att_normal": "<f4",
    "att_ke": "<f4", "att_kd": "<f4", "boxmesh_obj": "|u1",
}
_SHAPES = {
    "x0": (-1, 3), "v0": (-1, 3), "mass": (-1,), "inv_mass": (-1,), "radius": (-1,),
    "flags": (-1,), "faces": (-1, 3), "tri_ke": (-1,), "tri_ka": (-1,), "tri_kd": (-1,),
    "tri_rest_pose": (-1, 2, 2), "tri_rest_area": (-1,), "springs": (-1, 2), "spring_rest": (-1,),
    "spring_ke": (-1,), "spring_kd": (-1,), "bend": (-1, 4), "bend_rest": (-1,), "bend_ke": (-1,),
    "bend_kd": (-1,), "stitch": (-1,), "panel_id": (-1,), "body_v": (-1, 3), "body_f": (-1, 3),
    "face_filters": (-1, -1), "particle_filter_id": (-1,), "ref_v": (-1, 3), "ref_f": (-1, 3),
    "ref_v_off": (-1,), "ref_f_off": (-1,), "ref_label": (-1,), "allow_pairs": (-1, 2),
    "att_particle": (-1,), "att_point": (-1, 3), "att_normal": (-1, 3), "att_ke": (-1,),
    "att_kd": (-1,), "boxmesh_obj": (-1,),
}


def _paths(path: str | Path) -> tuple[Path, Path]:
    source = Path(path)
    if source.suffix == ".npz":
        return source, source.with_suffix(".json")
    if source.suffix == ".json":
        return source.with_suffix(".npz"), source
    raise SceneFormatError(f"scene path must end in .npz or .json: {source}")


def _validate_array(name: str, value: np.ndarray) -> None:
    expected_dtype = _DTYPES[name]
    if value.dtype.str != expected_dtype:
        raise SceneFormatError(f"{name}: expected dtype {expected_dtype}, got {value.dtype.str}")
    expected_shape = _SHAPES[name]
    if len(value.shape) != len(expected_shape) or any(want >= 0 and got != want for got, want in zip(value.shape, expected_shape)):
        raise SceneFormatError(f"{name}: expected shape {expected_shape}, got {value.shape}")


def load_scene(path: str | Path) -> Scene:
    npz_path, json_path = _paths(path)
    with json_path.open(encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("format") != "seam-scene/1":
        raise SceneFormatError(f"unsupported scene format {meta.get('format')!r}")
    if meta.get("build_error") is not None and not npz_path.exists():
        return Scene({}, meta)
    with np.load(npz_path, allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    missing = _DTYPES.keys() - arrays.keys()
    if missing:
        raise SceneFormatError(f"scene arrays missing: {', '.join(sorted(missing))}")
    checksums = meta.get("sha256")
    if not isinstance(checksums, dict) or checksums.keys() != arrays.keys():
        raise SceneFormatError("sha256 keys do not match npz keys")
    for name, value in arrays.items():
        if name in _DTYPES:
            _validate_array(name, value)
        actual = hashlib.sha256(value.tobytes(order="C")).hexdigest()
        if actual != checksums[name]:
            raise SceneFormatError(f"sha256 mismatch for {name}")
    return Scene(arrays, meta)


def write_sim_obj(boxmesh_obj: bytes, verts: np.ndarray, path: str | Path) -> None:
    lines = boxmesh_obj.decode("utf-8").splitlines(keepends=True)
    vertex = 0
    with Path(path).open("w", encoding="utf-8") as handle:
        for line in lines:
            if line.startswith("v "):
                p = verts[vertex]
                handle.write(f"v {p[0]} {p[1]} {p[2]}\n")
                vertex += 1
            else:
                handle.write(line)
    if vertex != len(verts):
        raise SceneFormatError(f"OBJ has {vertex} vertices, simulation has {len(verts)}")


def write_dump(out: str | Path, faces: np.ndarray, verts: np.ndarray, frame: int) -> None:
    directory = Path(out)
    face_path = directory / "dump_faces.npy"
    if not face_path.exists():
        np.save(face_path, np.asarray(faces, dtype=np.int32))
    np.save(directory / f"dump_f{frame:05d}.npy", np.asarray(verts, dtype=np.float32))
