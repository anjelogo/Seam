import numpy as np
import warp as wp
from newton._src.solvers.xpbd.kernels import (
    apply_particle_deltas,
    bending_constraint,
    solve_springs,
)

from .builder import Components, Ctx, SimParams


class Solver:
    def __init__(self, ctx: Ctx, components: Components, config, params: SimParams) -> None:
        self.ctx = ctx
        self.c = components
        self.config = config
        self.params = params
        self.frame_dt = 1.0 / float(config.sim_fps)
        self.sub_dt = self.frame_dt / params.substeps
        self.detect_dt = self.sub_dt * params.substeps    # §10.12, the product as computed
        self.n_particles = ctx.model.particle_count
        self.n_springs = ctx.model.spring_count
        self.n_edges = ctx.model.edge_count
        self.use_graph = ctx.model.device.is_cuda
        self.graph = None
        self._overflow = {"soft_contact": 0, "point_triangle": 0, "edge_edge": 0}

    def invalidate_graph(self) -> None:
        self.graph = None

    def step_frame(self, frame: int) -> None:
        ctx = self.ctx
        if frame == int(self.config.zero_gravity_steps):                     # §2.2.2
            ctx.model.gravity.fill_(wp.vec3(*self.params.gravity_on))
            self.invalidate_graph()
        smoother = self.c.smoother
        if smoother is not None and frame in smoother.frames:                # §2.2.3
            verts = smoother.verts_for_frame(frame)
            if verts is not None:
                self.c.body.replace_points(verts)
                self.invalidate_graph()
        if ctx.attachment_constraint and frame >= int(self.config.attachment_frames):  # §2.2.4
            ctx.attachment_constraint = False
            self.invalidate_graph()

        if not self.use_graph:
            self._frame_body(self.detect_dt, self.sub_dt)
            return
        if self.graph is None:
            with wp.ScopedCapture() as capture:
                self._frame_body(self.detect_dt, self.sub_dt)
            self.graph = capture.graph
        wp.capture_launch(self.graph)

    def _frame_body(self, detect_dt: float, sub_dt: float) -> None:
        ctx, c = self.ctx, self.c
        wp.copy(ctx.x_frame0, ctx.state_in.particle_q)
        wp.copy(ctx.v_frame0, ctx.state_in.particle_qd)
        c.self_contact.clear_flags()
        c.body.generate()
        if ctx.global_collision_filter:
            c.self_contact.piercing_survey()
        if self.n_springs:
            c.self_contact.detect_edge_edge(detect_dt)
        c.self_contact.detect_point_triangle(detect_dt)
        for _ in range(self.params.substeps):
            self._substep(sub_dt)

    def _substep(self, dt: float) -> None:
        ctx, c = self.ctx, self.c
        model = ctx.model
        ctx.state_in.particle_f.zero_()
        c.integrate(ctx, dt)
        ctx.lambda_spring.zero_()
        ctx.lambda_bend.zero_()
        c.attach.zero_lambdas()
        ctx.delta.zero_()

        c.body.solve(dt, self.params.soft_contact_relaxation)
        if ctx.cloth_reference_drag:
            c.drag.solve(dt)
        if ctx.enable_triangle_particle_collisions:
            c.self_contact.solve_point_triangle()
        if self.n_springs and ctx.enable_edge_edge_collisions:
            c.self_contact.solve_edge_edge()
        if self.n_springs:
            wp.launch(
                solve_springs,
                dim=self.n_springs,
                inputs=[
                    ctx.state_out.particle_q, ctx.state_out.particle_qd, model.particle_inv_mass,
                    ctx.springs, model.spring_rest_length, model.spring_stiffness, model.spring_damping,
                    dt, ctx.lambda_spring, ctx.delta,
                ],
                device=model.device,
            )
        if self.n_edges:
            wp.launch(
                bending_constraint,
                dim=self.n_edges,
                inputs=[
                    ctx.state_out.particle_q, ctx.state_out.particle_qd, model.particle_inv_mass,
                    ctx.edges2d, ctx.edge_rest, ctx.edge_props, dt, ctx.lambda_bend, ctx.delta,
                ],
                device=model.device,
            )
        if ctx.attachment_constraint:
            c.attach.solve(dt)

        wp.launch(
            apply_particle_deltas,
            dim=self.n_particles,
            inputs=[
                ctx.state_in.particle_q, ctx.state_out.particle_q, model.particle_flags, ctx.delta,
                dt, ctx.particle_max_velocity, ctx.x_tmp, ctx.state_out.particle_qd,
            ],
            device=model.device,
        )
        wp.copy(ctx.state_out.particle_q, ctx.x_tmp)
        wp.copy(ctx.cloth_mesh.points, ctx.state_out.particle_q)
        ctx.cloth_mesh.refit()
        ctx.state_in, ctx.state_out = ctx.state_out, ctx.state_in      # D7

    def read_overflow(self) -> dict[str, int]:
        ctx = self.ctx
        now = {
            "soft_contact": int(ctx.soft_contact_overflow.numpy()[0]),
            "point_triangle": int(ctx.pt_overflow.numpy()[0]),
            "edge_edge": int(ctx.ee_overflow.numpy()[0]),
        }
        new = {k: v - self._overflow[k] for k, v in now.items() if v > self._overflow[k]}
        self._overflow = now
        return new

    def positions(self) -> np.ndarray:
        # copy: on CPU numpy() is a view of the live buffer
        return self.ctx.state_in.particle_q.numpy().copy()

    def count_self_intersections(self) -> int:
        return self.c.self_contact.count_self_intersections()

    def count_body_intersections(self) -> int:
        return self.c.body.count_body_intersections()
