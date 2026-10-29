from typing import TYPE_CHECKING

import gstaichi as ti

if TYPE_CHECKING:
    from .solver import Sim


# Adapted from Newton 1.7.0 XPBD kernels, Apache-2.0.


@ti.func
def _atomic_add_vec(field, index, value):
    for axis in ti.static(range(3)):
        ti.atomic_add(field[index][axis], value[axis])


@ti.kernel
def clear_constraint_state(
    delta: ti.template(),
    spring_lambda: ti.template(),
    bend_lambda: ti.template(),
    att_lambda: ti.template(),
    particles: ti.i32,
    springs: ti.i32,
    bends: ti.i32,
    attachments: ti.i32,
):
    for particle in range(particles):
        delta[particle] = ti.Vector.zero(ti.f32, 3)
    for spring in range(springs):
        spring_lambda[spring] = 0.0
    for bend in range(bends):
        bend_lambda[bend] = 0.0
    for attachment in range(attachments):
        att_lambda[attachment] = 0.0


@ti.kernel
def solve_springs(
    x: ti.template(),
    v: ti.template(),
    inv_mass: ti.template(),
    indices: ti.template(),
    rest_length: ti.template(),
    stiffness: ti.template(),
    damping: ti.template(),
    dt: ti.f32,
    lambdas: ti.template(),
    delta: ti.template(),
    count: ti.i32,
):
    for spring in range(count):
        i = indices[spring][0]
        j = indices[spring][1]
        ke = stiffness[spring]
        kd = damping[spring]
        xij = x[i] - x[j]
        vij = v[i] - v[j]
        length = xij.norm()
        if length != 0.0:
            normal = xij / length
            constraint = length - rest_length[spring]
            wi = inv_mass[i]
            wj = inv_mass[j]
            denominator = wi + wj
            if denominator > 0.0 and ke > 0.0 and kd >= 0.0:
                alpha = 1.0 / (ke * dt * dt)
                gamma = kd / (ke * dt)
                grad_dot_v = dt * normal.dot(vij)
                multiplier = -(constraint + alpha * lambdas[spring] + gamma * grad_dot_v) / (
                    (1.0 + gamma) * denominator + alpha
                )
                dxi = wi * multiplier * normal
                dxj = -wj * multiplier * normal
                lambdas[spring] += multiplier
                _atomic_add_vec(delta, i, dxi)
                _atomic_add_vec(delta, j, dxj)


@ti.kernel
def solve_bending(
    x: ti.template(),
    v: ti.template(),
    inv_mass: ti.template(),
    indices: ti.template(),
    rest: ti.template(),
    stiffness: ti.template(),
    damping: ti.template(),
    dt: ti.f32,
    lambdas: ti.template(),
    delta: ti.template(),
    count: ti.i32,
):
    for bend in range(count):
        i = indices[bend][0]
        j = indices[bend][1]
        k = indices[bend][2]
        l = indices[bend][3]
        if i != -1 and j != -1 and k != -1 and l != -1:
            x1, x2, x3, x4 = x[i], x[j], x[k], x[l]
            n1 = (x3 - x1).cross(x4 - x1)
            n2 = (x4 - x2).cross(x3 - x2)
            edge = x4 - x3
            n1_length = n1.norm()
            n2_length = n2.norm()
            edge_length = edge.norm()
            if n1_length >= 1.0e-6 and n2_length >= 1.0e-6 and edge_length >= 1.0e-6:
                n1_hat = n1 / n1_length
                n2_hat = n2 / n2_length
                edge_hat = edge / edge_length
                cosine = n1_hat.dot(n2_hat)
                sine = n1_hat.cross(n2_hat).dot(edge_hat)
                constraint = ti.atan2(sine, cosine) - rest[bend]
                grad1 = -n1_hat * edge_length
                grad2 = -n2_hat * edge_length
                grad3 = -n1_hat * (x1 - x4).dot(edge_hat) - n2_hat * (x2 - x4).dot(edge_hat)
                grad4 = -n1_hat * (x3 - x1).dot(edge_hat) - n2_hat * (x3 - x2).dot(edge_hat)
                w1, w2, w3, w4 = inv_mass[i], inv_mass[j], inv_mass[k], inv_mass[l]
                denominator = (
                    w1 * grad1.norm_sqr()
                    + w2 * grad2.norm_sqr()
                    + w3 * grad3.norm_sqr()
                    + w4 * grad4.norm_sqr()
                )
                ke = stiffness[bend]
                kd = damping[bend]
                if denominator > 0.0 and ke > 0.0 and kd >= 0.0:
                    alpha = 1.0 / (ke * dt * dt)
                    gamma = kd / (ke * dt)
                    grad_dot_v = dt * (
                        grad1.dot(v[i]) + grad2.dot(v[j]) + grad3.dot(v[k]) + grad4.dot(v[l])
                    )
                    multiplier = -(constraint + alpha * lambdas[bend] + gamma * grad_dot_v) / (
                        (1.0 + gamma) * denominator + alpha
                    )
                    lambdas[bend] += multiplier
                    _atomic_add_vec(delta, i, w1 * multiplier * grad1)
                    _atomic_add_vec(delta, j, w2 * multiplier * grad2)
                    _atomic_add_vec(delta, k, w3 * multiplier * grad3)
                    _atomic_add_vec(delta, l, w4 * multiplier * grad4)


@ti.kernel
def apply_particle_deltas(
    x_orig: ti.template(),
    x_pred: ti.template(),
    flags: ti.template(),
    delta: ti.template(),
    dt: ti.f32,
    max_velocity: ti.f32,
    x_out: ti.template(),
    v_out: ti.template(),
    count: ti.i32,
):
    for particle in range(count):
        if flags[particle] & 1:
            x0 = x_orig[particle]
            x_new = x_pred[particle] + delta[particle]
            v_new = (x_new - x0) / dt
            speed = v_new.norm()
            if speed > max_velocity:
                v_new *= max_velocity / speed
                x_new = x0 + v_new * dt
            x_out[particle] = x_new
            v_out[particle] = v_new


def clear(sim: "Sim") -> None:
    clear_constraint_state(
        sim.delta,
        sim.spring_lambda,
        sim.bend_lambda,
        sim.att_lambda,
        sim.n,
        sim.n_springs,
        sim.n_bends,
        sim.n_attachments,
    )


def solve_internal(sim: "Sim", dt: float) -> None:
    if sim.n_springs:
        solve_springs(
            sim.x_out, sim.v_out, sim.inv_mass, sim.springs, sim.spring_rest, sim.spring_ke,
            sim.spring_kd, dt, sim.spring_lambda, sim.delta, sim.n_springs,
        )
    if sim.n_bends:
        solve_bending(
            sim.x_out, sim.v_out, sim.inv_mass, sim.bend, sim.bend_rest, sim.bend_ke,
            sim.bend_kd, dt, sim.bend_lambda, sim.delta, sim.n_bends,
        )


def apply(sim: "Sim", dt: float) -> None:
    apply_particle_deltas(
        sim.x_in, sim.x_out, sim.flags, sim.delta, dt, sim.particle_max_velocity,
        sim.x_in, sim.v_in, sim.n,
    )
