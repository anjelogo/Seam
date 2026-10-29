from typing import TYPE_CHECKING

import gstaichi as ti

if TYPE_CHECKING:
    from .solver import Sim


@ti.kernel
def copy_frame_state(
    x: ti.template(),
    v: ti.template(),
    x_frame0: ti.template(),
    v_frame0: ti.template(),
    count: ti.i32,
):
    for particle in range(count):
        x_frame0[particle] = x[particle]
        v_frame0[particle] = v[particle]


@ti.kernel
def integrate_particles(
    x: ti.template(),
    v: ti.template(),
    inv_mass: ti.template(),
    flags: ti.template(),
    gravity: ti.template(),
    dt: ti.f32,
    damping_factor: ti.f32,
    effective_velocity: ti.f32,
    max_velocity: ti.f32,
    x_new: ti.template(),
    v_new: ti.template(),
    count: ti.i32,
):
    for particle in range(count):
        x0 = x[particle]
        if flags[particle] & 1:
            weight = inv_mass[particle]
            gravity_scale = ti.cast(weight > 0.0, ti.f32)
            velocity = v[particle] + gravity[0] * gravity_scale * dt
            speed = velocity.norm()
            if damping_factor > 0.0 and speed > effective_velocity:
                velocity *= ti.exp(-damping_factor * speed * dt)
            if max_velocity > 0.0 and speed > max_velocity:
                velocity *= max_velocity / speed
            x_new[particle] = x0 + velocity * dt
            v_new[particle] = velocity
        else:
            x_new[particle] = x0


def snapshot(sim: "Sim") -> None:
    copy_frame_state(sim.x_in, sim.v_in, sim.x_frame0, sim.v_frame0, sim.n)


def integrate(sim: "Sim", dt: float) -> None:
    factor, effective, maximum = sim.damping
    integrate_particles(
        sim.x_in,
        sim.v_in,
        sim.inv_mass,
        sim.flags,
        sim.gravity,
        dt,
        factor,
        effective,
        maximum,
        sim.x_out,
        sim.v_out,
        sim.n,
    )
