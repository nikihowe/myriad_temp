# -*- coding: utf-8 -*-
"""Hermite-Simpson Direct Collocation.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/12jt50nC7ufeeeQPsPLRIJAuuiL_XSU1B
"""

import numpy as onp
from scipy.optimize import minimize

import jax
import jax.numpy as np
from jax.flatten_util import ravel_pytree # for putting in scipy minimize form

from jax.config import config
config.update("jax_enable_x64", True)

# Makes a cartpole function, given parameters
# mc:      mass of cart
# mp:      mass of pole
# length:  length of pole
# gravity: g
def make_cartpole(mc=2., mp=0.5, length=0.5, gravity=9.81):
    # Given state and control, returns velocities and accelerations
    def f(state, control):
        _, theta, x_vel, theta_vel = state
        # Page 868 of tutorial
        x_accel = (
            1/(mc + mp*(np.sin(theta)**2))
            * (
                control + mp*np.sin(theta)
                * (length*(theta_vel**2) + gravity*np.cos(theta))
            )
        )
        # Page 869 of tutorial
        theta_accel = (
            1/(length*(mc + mp*(np.sin(theta)**2)))
            * (-control*np.cos(theta) - mp*length*(theta_vel**2)*np.cos(theta)*np.sin(theta) - (mc + mp)*gravity*np.sin(theta))
        )
        return np.asarray([x_vel, theta_vel, x_accel, theta_accel])
    return f

def make_hs_nlp(horizon, nintervals, unravel):
    nvars = nintervals + 1
    interval_duration = horizon/nintervals

    f = make_cartpole()

    # Why do we del x?
    def cost(x, u):
        del x # good practice when you have a function that doesn't take an argument
        return u**2

    # # Hermite-Simpson midpoint
    # def midpoint_state(state, next_state, control, next_control):
    #     return ((1/2) * (state + next_state)
    #             + (interval_duration/8) * (f(state, control) - f(next_state, next_control)))

    # Hermite-Simpson collocation constraints (calculates midpoint constraints on-the-fly)
    def hs_defect(state, mid_state, next_state, control, mid_control, next_control):
        rhs = next_state - state
        lhs = (interval_duration / 6) \
            * ( f(state, control)
                + 4 * f(mid_state, mid_control)
                + f(next_state, next_control) )
        return rhs - lhs

    # Hermite-Simpson interpolation constraints
    def hs_interpolation(state, mid_state, next_state, control, mid_cotrol, next_control):
        return (mid_state
                - (1/2) * (state + next_state)
                - (interval_duration/8) * (f(state, control) - f(next_state, next_control)))

    # This is the "J" from the tutorial (6.5)
    def hs_cost(state, mid_state, next_state, control, mid_control, next_control):
        return (interval_duration/6) \
                * ( cost(state, control)
                    + 4 * cost(mid_state, mid_control)
                    + cost(next_state, next_control) )

    # Vectorizes the functions
    batched_cost = jax.vmap(hs_cost)
    batched_defects = jax.vmap(hs_defect)
    batched_interpolations = jax.vmap(hs_interpolation)

    def objective(flat_variables):
        states, mid_states, controls, mid_controls = unravel(flat_variables)
        return np.sum(batched_cost(states[:-1],   mid_states,   states[1:],
                                   controls[:-1], mid_controls, controls[1:]))

    def equality_constraints(flat_variables):
        states, mid_states, controls, mid_controls = unravel(flat_variables)
        return np.ravel(batched_defects(states[:-1],   mid_states,   states[1:],
                                        controls[:-1], mid_controls, controls[1:]))

    def interpolation_constraints(flat_variables):
        states, mid_states, controls, mid_controls = unravel(flat_variables)
        return np.ravel(batched_interpolations(states[:-1],   mid_states,   states[1:],
                                               controls[:-1], mid_controls, controls[1:]))



    dist = 0.8
    umax = 100
    state_bounds = onp.empty((nvars, 8))
    # list of tuples, where each variable is a single scalar
    # it's a grid, because each row is the state vector at that time step
    # horizontal axis is 2x the number of variables in the state
    state_bounds[:, 0] = -2*dist # sets whole first column to -2*dist
    state_bounds[:, 1] = 2*dist

    state_bounds[:, 2] = -2*onp.pi
    state_bounds[:, 3] = 2*onp.pi

    state_bounds[:, 4] = -onp.inf
    state_bounds[:, 5] = onp.inf

    state_bounds[:, 6] = -onp.inf
    state_bounds[:, 7] = onp.inf

    state_bounds[0, :] = 0
    state_bounds[-1, :] = 0
    state_bounds[-1, 0] = dist
    state_bounds[-1, 1] = dist
    state_bounds[-1, 2] = np.pi
    state_bounds[-1, 3] = np.pi

    # Set the mid state bounds
    mid_state_bounds = onp.zeros_like(state_bounds[:-1])
    mid_state_bounds[:] = [-2*dist, 2*dist, -2*onp.pi, 2*onp.pi, -onp.inf, onp.inf, -onp.inf, onp.inf]


    # print("setting up state bounds")
    # print(state_bounds)

    # Set the control bounds
    control_bounds = onp.empty((nvars, 2))
    control_bounds[:] = [-umax, umax]

    # Set the mid control bounds
    mid_control_bounds = onp.empty((nvars - 1, 2))
    mid_control_bounds[:] = [-umax, umax]

    # print("setting up control bounds")
    # print(control_bounds)

    # reshape is to make it two long lists (one of upper bounds, one of lower bounds)
    return objective, equality_constraints, interpolation_constraints, np.vstack(
        (np.reshape(state_bounds, (-1, 2)),
         np.reshape(mid_state_bounds, (-1, 2)),
         control_bounds,
         mid_control_bounds))

# Just a simple linear interpolation function
def hs_control_interpolation(controls, mid_controls, interval_duration):
    def u(t):
        # Find which interval we're in (which two collocation points we're between
        kstart, kend = int(np.floor(t/interval_duration)), int(np.ceil(t/interval_duration))

        # If we're right on a collocation point, return the control value there
        if kstart == kend:
            return controls[kstart]

        # Starting time
        tstart = interval_duration * kstart
        tau = t - tstart

        # Equation 4.10, page 862
        first_term = (2/(interval_duration**2)
                      * (tau - interval_duration/2)
                      * (tau - interval_duration) 
                      * controls[kstart])

        second_term = (4/(interval_duration**2)
                       * tau
                       * (tau - interval_duration)
                       * mid_controls[kstart])
        
        third_term = (2/(interval_duration**2)
                      * tau
                      * (tau - interval_duration/2)
                      * controls[kend])

        return first_term - second_term + third_term
    return u

# n: Interpolate the state
def hs_state_interpolation(states, mid_states, controls, mid_controls, interval_duration):
    def x(t):
        # We need the system dynamics to interpolate :)
        # TODO n: is there a nicer way to do this?
        f = make_cartpole()

        # Find which interval we're in (which two collocation points we're between
        kstart, kend = int(np.floor(t/interval_duration)), int(np.ceil(t/interval_duration))

        # If we're right on a collocation point, return the control value there
        if kstart == kend:
            return states[kstart]

        # Starting time
        tstart = interval_duration * kstart

        # Useful quantities
        tau = t - tstart
        fk = f(states[kstart], controls[kstart])
        fk_plus_half = f(mid_states[kstart], mid_controls[kstart])
        fk_plus_one = f(states[kend], controls[kend])



        # Equation 4.13, page 863
        first_term = states[kstart]
        
        second_term = fk * tau

        third_term = 1/2 * ((-3) * fk + 4 * fk_plus_half - fk_plus_one) * (tau**2) / interval_duration

        fourth_term = 1/3 * (2 * fk - 4 * fk_plus_half + 2 * fk_plus_one) * (tau**3) / (interval_duration**2)

        return first_term + second_term + third_term + fourth_term
    return x

import matplotlib.pyplot as plt

horizon = 2
intervals = 20

nvars = intervals + 1

dist = 0.8
# gives [0., 0.05, 0.1, ..., 0.9, 0.95, 1.]
linear_interpolation = np.arange(nvars)/(nvars-1)

# gives 21 rows of [0.8, pi, 0., 0.]
initial_states = np.tile(np.array([dist, np.pi, 0, 0]), (nvars, 1))

# multiply the above two, with broadcasting, to give
# (there are 20 timesteps, so 21 entries)
# [[0.   * 0.8, 0.   * pi, 0.   * 0., 0.   * 0.]
#  [0.05 * 0.8, 0.05 * pi, 0.05 * 0., 0.05 * 0.]
#  ...
#  [0.95 * 0.8, 0.95 * pi, 0.95 * 0., 0.95 * 0.]]
#  [1.   * 0.8, 1.   * pi, 1.   * 0., 1.   * 0.]]
# it's a linear interpolation in state between where we start and where we end
initial_states = linear_interpolation[:, np.newaxis] * initial_states

# make the mid states linear too (interpolate between collocation points)
mid_states = onp.copy((initial_states[:-1] + initial_states[1:])/2)

# a tuple, with (initial states, initial mid states, initial controls, initial mid controls)
initial_variables = (initial_states, mid_states, np.zeros(nvars), np.zeros(nvars - 1))

# flattens the initial variables into a big list
flat_initial_variables, unravel = ravel_pytree(initial_variables)

# objective takes flatten(state, control) variables, as does equality_constraints
# bounds takes the concatenated state and control bounds and packages them
# in groups of two [lower, upper], all in a long list. So the pairs of (parts of) state bounds all appear first,
# and the pairs of control bounds appears later in the long list
objective, equality_constraints, interpolation_constraints, bounds = make_hs_nlp(horizon, intervals, unravel)
# "horizon"   is the total time that you spend moving (here, 1)
# "intervals" is the number of intervals you divide the time into
# "unravel"   tells jax how to turn the variables into a form recognized by the NLP solver

# print("objective", objective)
# print("equality constraints", equality_constraints)
# print("bounds", bounds)

# Constraints is a list (or tuple) of dictionaries. We will have one for the
# collocation points (equality constraints),
# and one for the interpolated points (interpolation constraints)
# Note: equality constraints are expressed as the quantity having to
#       be equal to zero
constraints = ({
                    'type': 'eq',
                    'fun': jax.jit(equality_constraints),
                    'jac': jax.jit(jax.jacrev(equality_constraints))
                },

                {
                    'type': 'eq',
                    'fun': jax.jit(interpolation_constraints),
                    'jac': jax.jit(jax.jacrev(interpolation_constraints))
                }
                )

options = {'maxiter': 5000, 'ftol': 1e-6}

solution = minimize(fun=jax.jit(objective),
                    x0=flat_initial_variables,
                    method='SLSQP',
                    constraints=constraints,
                    bounds=bounds,
                    jac=jax.jit(jax.grad(objective)),
                    options=options)

# print("solution", solution)
opt_states, opt_mid_states, opt_controls, opt_mid_controls = unravel(solution.x)

# print(opt_states.shape)
# print(opt_controls.shape)

# Start the plot

fig, axs = plt.subplots(2, figsize=(8, 6))
fig.suptitle("Hermite-Simpson Collocation Method")

time_axis = np.array([(horizon/intervals) * k for k in range(nvars)])

# Plot the collocation points
major_ticks = np.arange(-1, 2.1, 0.2)
minor_ticks = np.arange(-1, 2.1, 0.05)
y_ticks = np.arange(-2, 4, 0.2)
minor_y_ticks = np.arange(-2, 4, 0.1)

axs[0].set_xticks(major_ticks)
axs[0].set_xticks(minor_ticks, minor=True)
axs[0].set_yticks(y_ticks)
axs[0].set_yticks(minor_y_ticks, minor=True)

major_ticks2 = np.arange(-30, 30, 10)
minor_ticks2 = np.arange(-30, 30, 5)

axs[1].set_xticks(major_ticks)
axs[1].set_xticks(minor_ticks, minor=True)
axs[1].set_yticks(major_ticks2)
axs[1].set_yticks(minor_ticks2, minor=True)

# ax.plot(time_axis, opt_states[:, 1], 'o', color="green", label="angle") # Angle
# ax.plot(time_axis[:-1] + 0.05, opt_mid_states[:, 1], '.', color="green", label="angle (mid)") # Angle

# ax.plot(time_axis, opt_controls, 'o', color="red")       # Control

# Generate denser points for interpolation between collocation points
time_dense = np.linspace(0, horizon, 201)

# Get interpolation functions for control (linear) and state (quadratic)
quadratic_control = hs_control_interpolation(opt_controls, opt_mid_controls, horizon/intervals)
cubic_state = hs_state_interpolation(opt_states, opt_mid_states, opt_controls, opt_mid_controls, horizon/intervals)

# Get the interpolated control and state values
controls = np.array([quadratic_control(t) for t in time_dense])
states = np.array([cubic_state(t) for t in time_dense])
# ax.plot(time_dense, states[:,1], '-', color="green") # Angle

# Plot state
axs[0].plot(time_axis, opt_states[:, 0], 'o', color="blue", fillstyle="none", label="position (collocation)")  # Position
axs[0].plot(time_axis[:-1] + 0.05, opt_mid_states[:, 0], 'o', markersize=3, color="blue", label="position (midpoint)")  # Position
axs[0].plot(time_dense, states[:,0], '.', markersize=3, color="blue", alpha=0.5, label="position (interpolated)")  # Position

# Plot control
axs[1].plot(time_axis, opt_controls, 'o', color="red", fillstyle="none", label="control (collocation)")  # Control
axs[1].plot(time_axis[:-1] + 0.05, opt_mid_controls, 'o', markersize=3, color="red", label="control (midpoint)")  # Control
axs[1].plot(time_dense, controls, '.', markersize=3, color="red", alpha=0.5, label="control (interpolated)")      # Control

# Add legend, grid, and show plot
for ax in axs:
    ax.legend(loc=4)

axs[1].set(xlabel='time', ylabel='')
axs[1].set_ylim([-30, 22])

axs[0].grid(which="both")
axs[0].grid(which='minor', alpha=0.2)
axs[0].grid(which='major', alpha=0.5)
axs[1].grid(which='major', alpha=0.5)
axs[1].grid(which='minor', alpha=0.2)
plt.show()

