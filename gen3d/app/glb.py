import json
import struct
from pathlib import Path

import numpy as np

ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
_COMPONENT = {np.float32: 5126, np.uint32: 5125, np.uint16: 5123, np.uint8: 5121}
_DTYPE = {v: k for k, v in _COMPONENT.items()}
_TYPE = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}
_WIDTH = {v: k for k, v in _TYPE.items()}


def new_gltf() -> tuple[dict, bytearray]:
    return {"asset": {"version": "2.0", "generator": "seam"}, "bufferViews": [], "accessors": []}, bytearray()


def read_glb(path: Path) -> tuple[dict, bytearray]:
    data = Path(path).read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20 : 20 + json_len])
    blob = bytearray()
    if len(data) >= 28 + json_len:
        bin_len = struct.unpack_from("<I", data, 20 + json_len)[0]
        blob = bytearray(data[28 + json_len : 28 + json_len + bin_len])
    return gltf, blob


def write_glb(path: Path, gltf: dict, blob: bytearray) -> Path:
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    if blob:
        gltf["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js
    if blob:
        body += struct.pack("<I4s", len(blob), b"BIN\0") + blob
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)
    return Path(path)


def add_bytes(gltf: dict, blob: bytearray, data: bytes, target: int | None = None) -> int:
    blob.extend(b"\0" * (-len(blob) % 4))
    view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
    if target:
        view["target"] = target
    blob.extend(data)
    gltf.setdefault("bufferViews", []).append(view)
    return len(gltf["bufferViews"]) - 1


def add_accessor(gltf: dict, blob: bytearray, array: np.ndarray, indices: bool = False) -> int:
    array = np.ascontiguousarray(array)
    flat = array.reshape(len(array), -1)
    view = add_bytes(gltf, blob, array.tobytes(), ELEMENT_ARRAY_BUFFER if indices else ARRAY_BUFFER)
    gltf.setdefault("accessors", []).append({
        "bufferView": view,
        "componentType": _COMPONENT[array.dtype.type],
        "count": len(array),
        "type": _TYPE[flat.shape[1]],
        "min": flat.min(axis=0).tolist(),
        "max": flat.max(axis=0).tolist(),
    })
    return len(gltf["accessors"]) - 1


def read_accessor(gltf: dict, blob: bytes, index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    dtype, width = np.dtype(_DTYPE[acc["componentType"]]), _WIDTH[acc["type"]]
    offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", dtype.itemsize * width)
    arr = np.ndarray((acc["count"], width), dtype, buffer=bytes(blob), offset=offset, strides=(stride, dtype.itemsize))
    return arr[:, 0].copy() if width == 1 else arr.copy()
