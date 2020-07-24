# -*- coding: utf-8 -*-
"""jax + SciPy Van der Pol Single Shooting.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1E5SbnHQIo6WkHpvOk8e2bcBxISyLq5Et

Translated by Niki from Pierre-Luc's NumPy [version](https://colab.research.google.com/drive/1uXYTpBojFW2bf5dQEUwnGk2WQBccxtFx?usp=sharing).
"""

import numpy as onp
from scipy.optimize import minimize

import jax
import jax.numpy as np
from jax import jit, vmap, lax

from jax.config import config
config.update("jax_enable_x64", True)

horizon = 10                              # how many unit time we simulate for
num_control_intervals = 20                # how many intervals of control
step_size = horizon/num_control_intervals # how long to hold each control value

control_bounds = onp.empty((num_control_intervals, 2))
control_bounds[:] = [-0.75, 1.0]
# (^ this can stay an onp array)

x0 = np.array([0., 1.]) # start state
xf = np.array([0., 0.]) # end state

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

vector_c = jit(vmap(c))

# Integrate from the start state, using controls, to the final state
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

  last_state_and_all_xs = lax.scan(fn, x0, us)
  return last_state_and_all_xs

# Calculate cost over entire trajectory
@jit
def objective(us):
  _, xs = integrate_fwd(us)
  all_costs = vector_c(xs, us)
  return np.sum(all_costs) + np.dot(x0, x0) # add in cost of start state (will make no difference)

# Calculate defect of final state
@jit
def equality_constraints(us):
  final_state, _ = integrate_fwd(us)
  return final_state - xf

rng = jax.random.PRNGKey(42)
# rng, rng_input = jax.random.split(rng)
initial_controls_guess = jax.random.uniform(rng, shape=(num_control_intervals,), minval=-0.76, maxval=0.9)

constraints = ({'type': 'eq',
                'fun': equality_constraints,
                'jac': jax.jit(jax.jacrev(equality_constraints))
                })

options = {'maxiter': 500, 'ftol': 1e-6}

solution = minimize(fun=objective,
                    x0=initial_controls_guess,
                    method='SLSQP',
                    constraints=constraints,
                    bounds=control_bounds,
                    jac=jax.jit(jax.grad(objective)),
                    options=options)
print(solution)

opt_controls = solution.x

import matplotlib.pyplot as plt

fig = plt.figure()
ax = fig.add_subplot(1, 1, 1)
time_axis = [horizon/num_control_intervals*k for k in range(num_control_intervals)]
ax.step(time_axis, opt_controls, where="post", label="optimal controls")
ax.grid()
plt.xticks(np.arange(0, 10, step=1))
plt.legend()
plt.show()

