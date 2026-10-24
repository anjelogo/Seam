import warp as wp
from newton import ParticleFlags


@wp.kernel
def _integrate(
    x: wp.array(dtype=wp.vec3),
    v: wp.array(dtype=wp.vec3),
    f: wp.array(dtype=wp.vec3),
    w: wp.array(dtype=float),
    particle_flags: wp.array(dtype=wp.int32),
    particle_world: wp.array(dtype=wp.int32),
    gravity: wp.array(dtype=wp.vec3),
    dt: float,
    damping_factor: float,
    effective_velocity: float,
    max_velocity: float,
    x_new: wp.array(dtype=wp.vec3),
    v_new: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    x0 = x[tid]
    if (particle_flags[tid] & ParticleFlags.ACTIVE) == 0:
        x_new[tid] = x0
        return

    inv_mass = w[tid]
    world_g = gravity[particle_world[tid]]
    v1 = v[tid] + (f[tid] * inv_mass + world_g * wp.step(-inv_mass)) * dt

    # both tests take the pre-damping speed, so the cap is not re-evaluated against the damped velocity
    speed = wp.length(v1)
    if damping_factor > 0.0 and speed > effective_velocity:
        v1 = v1 * wp.exp(-damping_factor * speed * dt)
    if max_velocity > 0.0 and speed > max_velocity:
        v1 = wp.normalize(v1) * max_velocity

    x_new[tid] = x0 + v1 * dt
    v_new[tid] = v1


def integrate(ctx, dt: float) -> None:
    model = ctx.model
    factor, effective, maximum = ctx.global_viscous_damping
    wp.launch(
        _integrate,
        dim=model.particle_count,
        inputs=[
            ctx.state_in.particle_q, ctx.state_in.particle_qd, ctx.state_in.particle_f,
            model.particle_inv_mass, model.particle_flags, model.particle_world, model.gravity,
            dt, factor, effective, maximum,
        ],
        outputs=[ctx.state_out.particle_q, ctx.state_out.particle_qd],
        device=model.device,
    )
