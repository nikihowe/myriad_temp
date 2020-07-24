# -*- coding: utf-8 -*-
"""jax + SciPy Van der Pol Multiple Shooting.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1R5kdLeiMxCDPbGJCFDgcBrLqc8ncTMpt

Developed from the Single Shooting [Notebook](https://colab.research.google.com/drive/1E5SbnHQIo6WkHpvOk8e2bcBxISyLq5Et?usp=sharing).

This is an implementation of multiple shooting. It requires that there be exactly one control value per shooting interval. The [next version](https://colab.research.google.com/drive/158eCoIwzwSM63gC_szYUkArlpO_W0_pl?usp=sharing) of this code allows for an arbitrary number of control values per shooting interval.
"""

import numpy as onp
from scipy.optimize import minimize

import jax
import jax.numpy as np
from jax import jit, vmap, lax
from jax.flatten_util import ravel_pytree

from jax.config import config
config.update("jax_enable_x64", True)

horizon = 10                              # how many unit time we simulate for
num_control_intervals = 20                # how many intervals of control
step_size = horizon/num_control_intervals # how long to hold each control value

###################################
# Initial State and Control Guess #
###################################

rng = jax.random.PRNGKey(42)
rng, rng_input = jax.random.split(rng)

x0 = np.array([0., 1.])# start state
xf = np.array([0., 0.]) # end state
middle_xs = jax.random.uniform(rng_input, shape=(num_control_intervals-1, 2), minval=0., maxval=0.5)
starting_xs = np.concatenate((x0[np.newaxis], middle_xs))

initial_controls_guess = jax.random.uniform(rng, shape=(num_control_intervals,), minval=-0.76, maxval=0.9)

first_guess_xs_and_initial_controls, unravel = ravel_pytree((starting_xs, initial_controls_guess))

print("first guess", first_guess_xs_and_initial_controls.shape)

############################
# State and Control Bounds #
############################

# Control bounds are applied to controls at every point in time
control_bounds = onp.empty((num_control_intervals, 2))
control_bounds[:] = [-0.75, 1.0]

# State bounds are applied to the start state and all
# intermediate states, but not to the end state
state_bounds = onp.empty((num_control_intervals, 4))
state_bounds[:,0] = state_bounds[:,2] = -onp.inf
state_bounds[:,1] = state_bounds[:,3] = onp.inf

# Set start state bounds
# (final state dealt with in equality constraints)
state_bounds[0, 0] = state_bounds[0, 1] = x0[0]
state_bounds[0, 2] = state_bounds[0, 3] = x0[1]

state_bounds = state_bounds.reshape(-1, 2)

all_bounds = onp.vstack((state_bounds, control_bounds))
print("all bounds", all_bounds.shape)

# Dynamics function
@jit
def f(x, u):
  x0 = x[0]
  x1 = x[1]
  return np.asarray([(1. - x1**2) * x0 - x1 + u, x0])

# Instantaneous cost
@jit
def c(x, u):
  return np.dot(x, x) + u**2

# Cost over entire (states, controls) trajectory
vector_c = jit(vmap(c))

# Integrate from the very start state, using controls, to the very final state
@jit
def integrate_fwd(us):
  def rk4_step(x, u):
    k1 = f(x, u)
    k2 = f(x + step_size * k1/2, u)
    k3 = f(x + step_size * k2/2, u)
    k4 = f(x + step_size * k3  , u)
    return x + (step_size/6)*(k1 + 2*k2 + 2*k3 + k4)

  def fn(carried_state, u):
    one_step_forward = rk4_step(carried_state, u)
    return one_step_forward, one_step_forward # (carry, y)

  last_state, all_next_xs = lax.scan(fn, x0, us)
  return last_state, all_next_xs

@jit
def single_rk4_step(x, u):
  k1 = f(x, u)
  k2 = f(x + step_size * k1/2, u)
  k3 = f(x + step_size * k2/2, u)
  k4 = f(x + step_size * k3  , u)
  return x + (step_size/6)*(k1 + 2*k2 + 2*k3 + k4)

# Step all starting states one step forward, to all ending states
parallel_rk4_step = jit(vmap(single_rk4_step))

# Calculate cost over entire trajectory
@jit
def objective(starting_xs_and_current_us):
  _, us = unravel(starting_xs_and_current_us)
  _, xs = integrate_fwd(us)                 # integrates from start state through to the end
  all_costs = vector_c(xs, us)              # calculate cost from states and controls
  return np.sum(all_costs) + np.dot(x0, x0) # add in cost of start state (will make no difference)

# Calculate defect of intermediate and final states
@jit
def equality_constraints(starting_xs_and_current_us):
  starting_xs, us = unravel(starting_xs_and_current_us)
  predicted_next_states = parallel_rk4_step(starting_xs, us)
  ending_xs = np.concatenate((starting_xs[1:], xf[np.newaxis]))
  return np.ravel(predicted_next_states - ending_xs) # we must flatten this to get dimensions to match up

constraints = ({'type': 'eq',
                'fun': equality_constraints,
                'jac': jax.jit(jax.jacrev(equality_constraints))
                })

options = {'maxiter': 500, 'ftol': 1e-6}

solution = minimize(fun=objective,
                    x0=first_guess_xs_and_initial_controls,
                    method='SLSQP',
                    constraints=constraints,
                    bounds=all_bounds,
                    jac=jax.jit(jax.grad(objective)),
                    options=options)
print(solution)

opt_controls = solution.x

import matplotlib.pyplot as plt

fig = plt.figure()
ax = fig.add_subplot(1, 1, 1)
time_axis = [horizon/(num_control_intervals)*k for k in range(num_control_intervals)]
ax.step(time_axis, opt_controls[-num_control_intervals:], where="post", label="optimal controls")
ax.grid()
plt.xticks(np.arange(0, 10, step=1))
plt.legend()
plt.show()

