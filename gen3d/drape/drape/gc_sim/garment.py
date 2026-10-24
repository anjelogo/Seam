# Adapted from GarmentCode pygarment/meshgen/garment.py, Copyright (c) 2024 Maria Korosteleva, MIT License (see LICENSE)
import json
import pickle

import igl
import numpy as np
import warp as wp
import yaml

from pygarment.meshgen.sim_config import PathCofig, SimConfig
from pygarment.pattern.core import BasicPattern

from drape.sim_newton import ClothData, SimParams, Solver, build_scene


class Cloth:
    def __init__(self, name, config: SimConfig, paths: PathCofig, caching: bool = False):
        self.caching = caching
        self.paths = paths
        self.name = name
        self.config = config

        self.sim_fps = config.sim_fps
        self.sim_substeps = config.sim_substeps
        self.zero_gravity_steps = config.zero_gravity_steps
        self.sim_dt = (1.0 / self.sim_fps) / self.sim_substeps
        self.device = wp.get_device() if wp.get_device().is_cuda else "cpu"
        self.frame = -1

        self.c_scale = 1.0
        self.b_scale = 100.0
        self.body_path = paths.in_body_obj
        self.body_shape_index = 0

        self.enable_body_smoothing = config.enable_body_smoothing
        self.enable_cloth_reference_drag = config.enable_cloth_reference_drag
        self.params = SimParams()

        self.build_stage(config)

        self.last_verts = None
        self.current_verts = self.solver.positions()

    def build_stage(self, config: SimConfig) -> None:
        from drape.sim_newton.attach import Attachments
        from drape.sim_newton.panel_drag import read_segmentation

        body_vertices, body_indices, body_faces = self.load_obj(self.paths.in_body_obj)
        body_seg = self.read_json(self.paths.body_seg)
        body_vertices = body_vertices * self.b_scale
        self.shift_y = self.get_shift_param(body_vertices)
        if self.shift_y:
            body_vertices[:, 1] = body_vertices[:, 1] + self.shift_y
        self.v_body = body_vertices
        self.f_body = body_faces
        self.body_indices = body_indices

        cloth_vertices, cloth_indices, cloth_faces = self.load_obj(self.paths.g_box_mesh)
        cloth_seg_dict = read_segmentation(self.paths.g_mesh_segmentation)
        self.cloth_seg_dict = cloth_seg_dict
        stitching_vertices = cloth_seg_dict.get("stitch", [])

        cloth_vertices = cloth_vertices * self.c_scale
        if self.shift_y:
            cloth_vertices[:, 1] = cloth_vertices[:, 1] + self.shift_y
        self.v_cloth_init = cloth_vertices
        self.f_cloth = cloth_faces

        if not self.paths.g_orig_edge_len.exists():
            orig_lens = {}
            print("no original length dict found")
        else:
            # written by our own box-mesh stage
            with open(self.paths.g_orig_edge_len, "rb") as handle:
                orig_lens = {(int(a), int(b)): float(v) for (a, b), v in pickle.load(handle).items()}

        with open(self.paths.in_body_mes) as handle:
            measurements = yaml.load(handle, Loader=yaml.SafeLoader)["body"]
        with open(self.paths.g_vert_labels) as handle:
            vertex_labels = yaml.load(handle, Loader=yaml.SafeLoader) or {}

        self.cloth = ClothData(
            verts=cloth_vertices, faces=cloth_faces, stitch_set=frozenset(int(v) for v in stitching_vertices),
            labels=cloth_seg_dict, panel_of_vertex=[None] * len(cloth_vertices),
            panel_pref_label=self._load_panel_labels(), vertex_labels=vertex_labels,
            measurements=measurements, body_verts=body_vertices, body_faces=body_faces,
            body_seg=body_seg, y_shift=self.shift_y, boxmesh_obj_path=self.paths.g_box_mesh,
            orig_lens=orig_lens,
        )

        attachments = Attachments()
        if config.enable_attachment_constraint:
            self._add_attachment_labels(attachments, config)

        self.ctx, self.components = build_scene(self.cloth, config, self.params, self.device,
                                                attachments=attachments)
        self.model = self.ctx.model
        self.solver = Solver(self.ctx, self.components, config, self.params)

    def _add_attachment_labels(self, attachments, config: SimConfig) -> None:
        body_dict = self.cloth.measurements
        vertex_labels = self.cloth.vertex_labels

        labels_present = False
        for i, attach_label in enumerate(config.attachment_labels):
            verts = vertex_labels.get(attach_label) or []
            if not verts:
                continue
            if attach_label == "lower_interface":
                level = body_dict.get("_waist_level")
                if level is None:
                    level = body_dict["height"] - body_dict["head_l"] - body_dict["waist_line"]
                point, normal = wp.vec3(0.0, float(level), 0.0), wp.vec3(0.0, 1.0, 0.0)
            elif attach_label == "right_collar":
                neck_w = body_dict["neck_w"] - 2
                point, normal = wp.vec3(-neck_w / 2.0, 0.0, 0.0), wp.vec3(1.0, 0.0, 0.0)
            elif attach_label == "left_collar":
                neck_w = body_dict["neck_w"] - 2
                point, normal = wp.vec3(neck_w / 2.0, 0.0, 0.0), wp.vec3(-1.0, 0.0, 0.0)
            elif attach_label == "strapless_top":
                level = body_dict["height"] - body_dict["head_l"] - body_dict["armscye_depth"]
                point, normal = wp.vec3(0.0, float(level), 0.0), wp.vec3(0.0, 1.0, 0.0)
            else:
                print(f"{self.name}::WARNING::Requested attachment label {attach_label} is not supported. Skipped")
                continue
            labels_present = True
            attachments.add(verts, point, normal, stiffness=config.attachment_stiffness[i],
                            damping=config.attachment_damping[i])
            print(f"Using attachment for {attach_label} with {len(verts)} vertices")

        if not labels_present:
            config.enable_attachment_constraint = False
            config.update_min_steps()
            print(f"{self.name}::WARNING::Requested attachment labels {config.attachment_labels} "
                  "are not present. Attachment is turned off")

    def _load_panel_labels(self) -> dict:
        pattern = BasicPattern(self.paths.g_specs)
        return {name: panel.get("label", "") for name, panel in pattern.pattern["panels"].items()}

    def update(self, frame: int) -> None:
        self.frame = frame
        self.solver.step_frame(frame)
        dropped = self.solver.read_overflow()
        if dropped:
            print(f"frame {frame}: contact buffer overflow, elements dropped {dropped}")
        self.last_verts = self.current_verts
        self.current_verts = self.solver.positions()

    def run_frame(self) -> None:
        self.update(self.frame)

    def is_static(self):
        threshold = self.config.static_threshold
        non_static_percent = self.config.non_static_percent
        current = self.current_verts
        if self.last_verts is None:
            return False, len(current)
        diff_l1 = np.sum(np.abs(current - self.last_verts), axis=1)
        non_static_len = int((diff_l1 > threshold).sum())
        if non_static_len == 0 or non_static_len < len(current) * 0.01 * non_static_percent:
            print(f"\nStatic with {non_static_len} non-static vertices out of {len(current)}")
            return True, non_static_len
        return False, non_static_len

    def count_self_intersections(self) -> int:
        return self.solver.count_self_intersections()

    def count_body_intersections(self) -> int:
        return self.solver.count_body_intersections()

    def read_json(self, path):
        with open(path) as handle:
            return json.load(handle)

    def load_obj(self, path):
        v, f = igl.read_triangle_mesh(str(path))
        return v, f.flatten(), f

    def get_shift_param(self, body_vertices) -> float:
        min_y = float(np.asarray(body_vertices)[:, 1].min())
        return abs(min_y) if min_y < 0 else 0.0

    def calc_norm(self, a, b, c):
        n = np.cross(np.array(b - a), np.array(c - a))
        return n / np.linalg.norm(n)

    def calc_vertex_norms(self):
        normals = np.zeros((len(self.v_cloth_init), 4))
        verts = np.asarray(self.current_verts)
        for face in self.f_cloth:
            v0, v1, v2 = verts[face]
            normals[face] += list(self.calc_norm(v0, v1, v2)) + [1]
        return normals[:, :3] / normals[:, 3][:, np.newaxis]

    def save_frame(self, save_v_norms: bool = False) -> None:
        vertex_normals = self.calc_vertex_norms() if save_v_norms else None
        verts = self.current_verts
        with open(self.paths.g_box_mesh) as obj_file:
            lines = obj_file.readlines()
        with open(self.paths.g_sim, "w") as obj_file:
            v_idx = 0
            vn_idx = 0
            for line in lines:
                if line.startswith("v "):
                    p = verts[v_idx]
                    obj_file.write(f"v {p[0]} {p[1]} {p[2]}\n")
                    v_idx += 1
                elif line.startswith("vn "):
                    if save_v_norms:
                        n = vertex_normals[vn_idx]
                        obj_file.write(f"vn {n[0]} {n[1]} {n[2]}\n")
                        vn_idx += 1
                else:
                    obj_file.write(line)
