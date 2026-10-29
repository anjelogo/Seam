import gstaichi as ti
import numpy as np


_SCAN_CHUNK = 128


def _next_power_of_two(value: int) -> int:
    return 1 << max(0, value - 1).bit_length()


def _grid_shape(x: np.ndarray, faces: np.ndarray) -> tuple[np.float32, int]:
    if len(faces) == 0:
        return np.float32(1.0), 1
    triangles = x[faces]
    edges = np.concatenate(
        (
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 1],
            triangles[:, 0] - triangles[:, 2],
        )
    )
    squared = np.sum(edges * edges, axis=1, dtype=np.float32)
    cell_size = np.mean(np.sqrt(squared, dtype=np.float32), dtype=np.float32)
    if not np.isfinite(cell_size) or cell_size <= np.float32(1.0e-6):
        cell_size = np.float32(1.0)

    cell_lo = np.floor(np.min(triangles, axis=1) / cell_size).astype(np.int32)
    cell_hi = np.floor(np.max(triangles, axis=1) / cell_size).astype(np.int32)
    spans = cell_hi - cell_lo + 1
    entries = int(
        np.sum(
            spans[:, 0].astype(np.int64)
            * spans[:, 1].astype(np.int64)
            * spans[:, 2].astype(np.int64)
        )
    )
    return cell_size, max(entries * 2, len(faces) * 16, 1)


@ti.data_oriented
class TriangleGrid:
    def __init__(self, sim) -> None:
        self.x = sim.x_in
        self.faces = sim.faces
        self.n_faces = int(sim.n_faces)

        x0 = np.asarray(sim.scene.arrays["x0"], dtype=np.float32)
        faces = np.asarray(sim.scene.arrays["faces"], dtype=np.int32)
        cell_size, self.entry_capacity = _grid_shape(x0, faces)
        self.table_size = _next_power_of_two(max(2 * self.n_faces, 1))
        self.table_mask = self.table_size - 1
        self.n_chunks = (self.table_size + _SCAN_CHUNK - 1) // _SCAN_CHUNK

        face_shape = max(self.n_faces, 1)
        self.cell_size = ti.field(ti.f32, shape=())
        self.inv_cell_size = ti.field(ti.f32, shape=())
        self.tri_lo = ti.Vector.field(3, ti.f32, shape=face_shape)
        self.tri_hi = ti.Vector.field(3, ti.f32, shape=face_shape)
        self.counts = ti.field(ti.i32, shape=self.table_size)
        self.offsets = ti.field(ti.i32, shape=self.table_size)
        self.cursors = ti.field(ti.i32, shape=self.table_size)
        self.chunk_sums = ti.field(ti.i32, shape=self.n_chunks)
        self.chunk_offsets = ti.field(ti.i32, shape=self.n_chunks)
        self.entry_face = ti.field(ti.i32, shape=self.entry_capacity)
        self.entry_key = ti.Vector.field(3, ti.i32, shape=self.entry_capacity)
        self.overflow_count = ti.field(ti.i32, shape=1)

        self.cell_size[None] = cell_size
        self.inv_cell_size[None] = np.float32(1.0) / cell_size
        self._reported_overflow = 0

    @ti.func
    def cell(self, point):
        return ti.cast(ti.floor(point * self.inv_cell_size[None]), ti.i32)

    @ti.func
    def bucket(self, cell):
        key = (
            cell[0] * ti.i32(73856093)
            ^ cell[1] * ti.i32(19349663)
            ^ cell[2] * ti.i32(83492791)
        )
        return key & ti.i32(self.table_mask)

    @ti.func
    def query_start(self, cell):
        return self.offsets[self.bucket(cell)]

    @ti.func
    def query_end(self, cell):
        bucket = self.bucket(cell)
        return ti.min(
            self.offsets[bucket] + self.counts[bucket],
            ti.i32(self.entry_capacity),
        )

    @ti.func
    def accepts(self, entry: ti.i32, cell, query_lo, query_hi, query_cell_lo):
        face = self.entry_face[entry]
        key = self.entry_key[entry]
        accepted = (
            key[0] == cell[0]
            and key[1] == cell[1]
            and key[2] == cell[2]
            and self.tri_lo[face][0] <= query_hi[0]
            and self.tri_lo[face][1] <= query_hi[1]
            and self.tri_lo[face][2] <= query_hi[2]
            and self.tri_hi[face][0] >= query_lo[0]
            and self.tri_hi[face][1] >= query_lo[1]
            and self.tri_hi[face][2] >= query_lo[2]
        )
        if accepted:
            tri_cell_lo = self.cell(self.tri_lo[face])
            first = ti.Vector(
                [
                    ti.max(query_cell_lo[0], tri_cell_lo[0]),
                    ti.max(query_cell_lo[1], tri_cell_lo[1]),
                    ti.max(query_cell_lo[2], tri_cell_lo[2]),
                ]
            )
            accepted = (
                first[0] == cell[0]
                and first[1] == cell[1]
                and first[2] == cell[2]
            )
        return accepted

    @ti.kernel
    def _clear(self):
        for bucket in range(self.table_size):
            self.counts[bucket] = 0
            self.offsets[bucket] = 0
            self.cursors[bucket] = 0

    @ti.kernel
    def _count(self):
        for face in range(self.n_faces):
            indices = self.faces[face]
            a = self.x[indices[0]]
            b = self.x[indices[1]]
            c = self.x[indices[2]]
            lo = ti.min(a, ti.min(b, c))
            hi = ti.max(a, ti.max(b, c))
            self.tri_lo[face] = lo
            self.tri_hi[face] = hi
            cell_lo = self.cell(lo)
            cell_hi = self.cell(hi)
            for i, j, k in ti.ndrange(
                (cell_lo[0], cell_hi[0] + 1),
                (cell_lo[1], cell_hi[1] + 1),
                (cell_lo[2], cell_hi[2] + 1),
            ):
                ti.atomic_add(self.counts[self.bucket(ti.Vector([i, j, k]))], 1)

    @ti.kernel
    def _scan_local(self):
        for chunk in range(self.n_chunks):
            total = ti.i32(0)
            for local in range(_SCAN_CHUNK):
                index = chunk * _SCAN_CHUNK + local
                if index < self.table_size:
                    self.offsets[index] = total
                    total += self.counts[index]
            self.chunk_sums[chunk] = total

    @ti.kernel
    def _scan_chunks(self):
        ti.loop_config(serialize=True)
        total = ti.i32(0)
        for chunk in range(self.n_chunks):
            self.chunk_offsets[chunk] = total
            total += self.chunk_sums[chunk]

    @ti.kernel
    def _finish_scan(self):
        for bucket in range(self.table_size):
            offset = self.offsets[bucket] + self.chunk_offsets[bucket // _SCAN_CHUNK]
            self.offsets[bucket] = offset
            self.cursors[bucket] = offset

    @ti.kernel
    def _fill(self):
        for face in range(self.n_faces):
            cell_lo = self.cell(self.tri_lo[face])
            cell_hi = self.cell(self.tri_hi[face])
            for i, j, k in ti.ndrange(
                (cell_lo[0], cell_hi[0] + 1),
                (cell_lo[1], cell_hi[1] + 1),
                (cell_lo[2], cell_hi[2] + 1),
            ):
                cell = ti.Vector([i, j, k])
                slot = ti.atomic_add(self.cursors[self.bucket(cell)], 1)
                if slot < self.entry_capacity:
                    self.entry_face[slot] = face
                    self.entry_key[slot] = cell
                else:
                    ti.atomic_add(self.overflow_count[0], 1)

    def rebuild(self) -> None:
        self._clear()
        self._count()
        self._scan_local()
        self._scan_chunks()
        self._finish_scan()
        self._fill()

    def overflow(self) -> int:
        overflow = int(self.overflow_count.to_numpy()[0])
        if overflow > self._reported_overflow:
            print(f"taichi triangle grid overflow: {overflow - self._reported_overflow} entries dropped")
            self._reported_overflow = overflow
        return overflow
