from dataclasses import dataclass
from typing import Optional

import jax.numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .config import DynamicsType, HParams


@dataclass
class FiniteHorizonControlSystem(object):
  x_0: np.array # state at time 0
  x_T: Optional[np.array] # state at time T
  T: np.float64 # duration of trajectory
  bounds: np.ndarray # State and control bounds

  def __post_init__(self):
    if self.x_T is not None:
      assert self.x_0.shape == self.x_T.shape
    assert self.bounds.shape == (self.x_0.shape[0]+1, 2)
    assert self.T > 0

  def dynamics(self, x_t: np.ndarray, u_t: np.float64) -> np.ndarray:
    raise NotImplementedError
  
  def cost(self, x_t: np.ndarray, u_t: np.float64) -> np.float64:
    raise NotImplementedError

  def plot_solution(self, x: np.ndarray) -> None:
    raise NotImplementedError


def get_system(hp: HParams) -> FiniteHorizonControlSystem:
  if hp.dynamics == DynamicsType.CARTPOLE:
    return CartPole()
  elif hp.dynamics == DynamicsType.VANDERPOL:
    return VanDerPol()
  elif hp.dynamics == DynamicsType.SEIR:
    return SEIR()
  else:
    raise KeyError


class CartPole(FiniteHorizonControlSystem):
  def __init__(self):
    # Physical parameters for the cart-pole example (Table 3)
    self.m1 = 1.0 #kg mass of cart
    self.m2 = 0.3 #kg mass of pole
    self.l = 0.5 #m pole length
    self.g = 9.81 #m/s^2 gravity acceleration
    self.u_max = 20 #N maximum actuator force
    self.d_max = 2.0 #m extent of the rail that cart travels on
    self.d = 1.0 #m distance traveled during swing-up

    super().__init__(
      x_0 = np.zeros(4), # Starting state (Eq. 6.9)
      x_T = np.array([self.d,np.pi,0,0]), # Ending state (Eq. 6.9)
      T = 2.0, #s duration of swing-up,
      bounds = np.array([
        [-self.d_max, self.d_max], # Eq. 6.7
        [-2*np.pi, 2*np.pi],
        [np.nan, np.nan],
        [np.nan, np.nan],
        [-self.u_max, self.u_max], # Control bounds (Eq. 6.8)
      ]),
    )

  # Cart-Pole Example: System Dynamics (Section 6.1)
  def dynamics(self, x_t: np.ndarray, u_t: np.float64) -> np.ndarray:
    q1, q2, q̇1, q̇2 = x_t
    # Eq. 6.1
    q̈1 = (self.l * self.m2 * np.sin(q2) * q̇2**2 + u_t + self.m2 * self.g * np.cos(q2) * np.sin(q2)) / (self.m1 + self.m2 * (1 - np.cos(q2)**2))
    q̈1 = np.squeeze(q̈1)
    # Eq. 6.2
    q̈2 = - (self.l * self.m2 * np.cos(q2) * q̇2**2 + u_t * np.cos(q2) + (self.m1 + self.m2) * self.g * np.sin(q2)) / (self.l * self.m1 + self.l * self.m2 * (1 - np.cos(q2)**2))
    q̈2 = np.squeeze(q̈2)
    return np.array([q̇1, q̇2, q̈1, q̈2])
  
  def cost(self, x_t: np.ndarray, u_t: np.float64) -> np.float64:
    # Eq. 6.3
    return u_t ** 2
  
  def plot_solution(self, x):
    x = pd.DataFrame(x, columns=['q1','q2','q̈1','q̈2','u'])

    # Plot optimal trajectory (Figure 10)
    sns.set(style='darkgrid')
    plt.figure(figsize=(9,6))
    ts = np.linspace(0,self.T,x.shape[0])

    plt.subplot(3,1,1)
    plt.ylabel('position (m)')
    plt.xlim(0,2)
    plt.ylim(0,1.5)
    plt.plot(ts, x['q1'], '-bo', clip_on=False, zorder=10)

    plt.subplot(3,1,2)
    plt.ylabel('angle (rad)')
    plt.plot(ts, x['q2'], '-bo', clip_on=False, zorder=10)
    plt.xlim(0,2)
    plt.ylim(-2,4)

    plt.subplot(3,1,3)
    plt.ylabel('force (N)')
    plt.plot(ts, x['u'], '-bo', clip_on=False, zorder=10)
    plt.xlim(0,2)
    plt.ylim(-20,10)

    plt.xlabel('time (s)')
    plt.tight_layout()
    plt.show()


class VanDerPol(FiniteHorizonControlSystem):
  def __init__(self):
    super().__init__(
      x_0 = np.array([0., 1.]),
      x_T = np.zeros(2),
      T = 10.0,
      bounds = np.array([
        [np.nan, np.nan],
        [np.nan, np.nan],
        [-0.75, 1.0],
      ]),
    )

  def dynamics(self, x_t: np.ndarray, u_t: np.float64) -> np.ndarray:
    x0, x1 = x_t
    _x0 = np.squeeze((1. - x1**2) * x0 - x1 + u_t)
    _x1 = np.squeeze(x0)
    return np.asarray([_x0, _x1])
  
  def cost(self, x_t: np.ndarray, u_t: np.float64) -> np.float64:
    return x_t.T @ x_t + u_t ** 2

  def plot_solution(self, x: np.ndarray) -> None:
    x = pd.DataFrame(x, columns=['x0','x1','u'])

    sns.set(style='darkgrid')
    plt.figure(figsize=(9,4))

    plt.subplot(1,2,1)
    plt.plot(x['x0'], x['x1'])
    
    plt.subplot(1,2,2)
    plt.plot(np.linspace(0, self.T, x['u'].shape[0]), x['u'])
    plt.xlabel('time (s)')

    plt.tight_layout()
    plt.show()


class SEIR(FiniteHorizonControlSystem):
  def __init__(self):
    self.b = 0.525
    self.d = 0.5
    self.c = 0.0001
    self.e = 0.5

    self.g = 0.1
    self.a = 0.2

    self.S_0 = 1000
    self.E_0 = 100
    self.I_0 = 50
    self.R_0 = 15
    self.N_0 = self.S_0 + self.E_0 + self.I_0 + self.R_0

    self.A = 0.1
    self.M = 1000

    super().__init__(
      x_0 = np.array([self.S_0, self.E_0, self.I_0, self.N_0], dtype=np.float64),
      x_T = None,
      T = 20,
      bounds = np.array([
        [np.nan, np.nan],
        [np.nan, np.nan],
        [np.nan, np.nan],
        [np.nan, np.nan],
        [0.0, 1.0],
      ]),
    )

  def dynamics(self, y_t: np.ndarray, u_t: np.float64) -> np.ndarray:
    S, E, I, N = y_t

    Ṡ = np.squeeze(self.b*N - self.d*S - self.c*S*I - u_t*S)
    Ė = np.squeeze(self.c*S*I - (self.e+self.d)*E)
    İ = np.squeeze(self.e*E - (self.g+self.a+self.d)*I)
    Ṅ = np.squeeze((self.b-self.d)*N - self.a*I)

    ẏ_t = np.array([Ṡ, Ė, İ, Ṅ])
    return ẏ_t
  
  def cost(self, y_t: np.ndarray, u_t: np.float64) -> np.float64:
    return self.A * y_t[2] + u_t ** 2

  def plot_solution(self, x: np.ndarray) -> None:
    sns.set()
    plt.figure(figsize=(10,3))

    plt.subplot(151)
    plt.title('applied control')
    plt.plot(x[:, -1])
    plt.ylim(-0.1, 1.01)

    for idx, title in enumerate(['S', 'E', 'I', 'N']):
      plt.subplot(1,5,idx+2)
      plt.title(title)
      plt.plot(x[:, idx])

    plt.tight_layout()
    plt.show()