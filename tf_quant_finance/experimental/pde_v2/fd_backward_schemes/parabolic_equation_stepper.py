# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python2, python3
"""Stepper for parabolic PDEs solving."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf


def parabolic_equation_step(
    time,
    next_time,
    coord_grid,
    value_grid,
    boundary_conditions,
    second_order_coeff_fn,
    first_order_coeff_fn,
    zeroth_order_coeff_fn,
    time_marching_scheme,
    dtype=None,
    name=None):
  """Performs one step of the parabolic PDE solver.

  For a given solution (given by the `value_grid`) of a parabolic PDE at a given
  `time` on a given `coord_grid` computes an approximate solution at the
  `next_time` on the same coordinate grid. The parabolic differential equation
  is of the form:

  ```none
   V_{t} + a(t, x) * V_{xx} + b(t, x) * V_{x} + c(t, x) * V = 0
  ```

  Here `V = V(t, x)` is a solution to the 2-dimensional PDE. `V_{t}` is the
  derivative over time and `V_{x}` and `V_{xx}` are the first and second
  derivatives over the space component. For a solution to be well-defined, it is
  required for `a` to be positive on its domain. Henceforth, `a(t, x)`,
  `b(t, x)`, and `c(t, x)` are referred to as second order, first order and
  zeroth order coefficients, respectively.

  See `fd_solvers.step_back` for an example use case.

  Args:
    time: Real positive scalar `Tensor`. The start time of the grid.
      Corresponds to time `t0` above.
    next_time: Real scalar `Tensor` smaller than the `start_time` and greater
      than zero. The time to step back to. Corresponds to time `t1` above.
    coord_grid: List of `n` rank 1 real `Tensor`s. `n` is the dimension of the
      domain. The i-th `Tensor` has shape, `[d_i]` where `d_i` is the size of
      the grid along axis `i`. The coordinates of the grid points. Corresponds
      to the spatial grid `G` above.
    value_grid: Real `Tensor` containing the function values at time
      `start_time` which have to be stepped back to time `end_time`. The shape
      of the `Tensor` must broadcast with `[K, d_1, d_2, ..., d_n]`. The first
      axis of size `K` is the values batch dimension and allows multiple
      functions (with potentially different boundary/final conditions) to be
      stepped back simultaneously.
    boundary_conditions: The boundary conditions. Only rectangular boundary
      conditions are supported. A list of tuples of size 1. The list element is
      a tuple that consists of two callables representing the
      boundary conditions at the minimum and maximum values of the spatial
      variable indexed by the position in the list. `boundary_conditions[0][0]`
      describes the boundary at `x_min`, and `boundary_conditions[0][1]` the
      boundary at `x_max`. The boundary conditions are accepted in the form
      `alpha(t) V + beta(t) V_n = gamma(t)`, where `V_n` is the derivative
      with respect to the exterior normal to the boundary.
      Each callable receives the current time `t` and the `coord_grid` at the
      current time, and should return a tuple of `alpha`, `beta`, and `gamma`.
      Each can be a number, a zero-rank `Tensor` or a `Tensor` of the batch
      shape.
      For example, for a grid of shape `(b, n)`, where `b` is the batch size,
      `boundary_conditions[0][0]` should return a tuple of either numbers,
      zero-rank tensors or tensors of shape `(b, n)`.
      `alpha` and `beta` can also be `None` in case of Neumann and
      Dirichlet conditions, respectively.
    second_order_coeff_fn: Callable returning the second order coefficient
      `a(t, r)` evaluated at given time `t`.
      The callable accepts the following arguments:
        `t`: The time at which the coefficient should be evaluated.
        `locations_grid`: a `Tensor` representing a grid of locations `r` at
          which the coefficient should be evaluated.
      Returns an object `A` such that `A[0][0]` is defined and equals
      `a(r, t)`. `A[0][0]` should be a Number, a `Tensor` broadcastable to the
      shape of `locations_grid`, or `None` if corresponding term is absent in
      the equation. Also, the callable itself may be None, meaning there are no
      second-order derivatives in the equation.
    first_order_coeff_fn: Callable returning the first order coefficient
      `b(t, r)` evaluated at given time `t`.
      The callable accepts the following arguments:
        `t`: The time at which the coefficient should be evaluated.
        `locations_grid`: a `Tensor` representing a grid of locations `r` at
          which the coefficient should be evaluated.
      Returns a list or an 1D `Tensor`, `0`-th element of which represents
      `b(t, r)`. This element should be a Number, a `Tensor` broadcastable
       to the shape of `locations_grid`, or None if corresponding term is absent
       in the equation. The callable itself may be None, meaning there are no
       first-order derivatives in the equation.
    zeroth_order_coeff_fn: Callable returning the zeroth order coefficient
      `c(t, r)` evaluated at given time `t`.
      The callable accepts the following arguments:
        `t`: The time at which the coefficient should be evaluated.
        `locations_grid`: a `Tensor` representing a grid of locations `r` at
          which the coefficient should be evaluated.
      Should return a Number or a `Tensor` broadcastable to the shape of
      `locations_grid`. May also return None or be None if the shift term is
      absent in the equation.
    time_marching_scheme: A callable which represents the time marching scheme
      for solving the PDE equation. If `u(t)` is space-discretized vector of the
      solution of the PDE, this callable approximately solves the equation
      `du/dt = A(t) u(t)` for `u(t1)` given `u(t2)`. Here `A` is a tridiagonal
      matrix. The callable consumes the following arguments by keyword:
        1. inner_value_grid: Grid of solution values at the current time of
          the same `dtype` as `value_grid` and shape of `value_grid[..., 1:-1]`.
        2. t1: Lesser of the two times defining the step.
        3. t2: Greater of the two times defining the step.
        4. equation_params_fn: A callable that takes a scalar `Tensor` argument
          representing time, and constructs the tridiagonal matrix `A`
          (a tuple of three `Tensor`s, main, upper, and lower diagonals)
          and the inhomogeneous term `b`. All of the `Tensor`s are of the same
          `dtype` as `values_inner_value_gridgrid` and of the shape
          broadcastable with the shape of `inner_value_grid`.
      The callable should return a `Tensor` of the same shape and `dtype` a
      `value_grid` and represents an approximate solution of the PDE after one
      iteraton.
    dtype: The dtype to use.
    name: The name to give to the ops.
      Default value: None which means `parabolic_equation_step` is used.

  Returns:
    A sequence of two `Tensor`s. The first one is a `Tensor` of the same
    `dtype` and `shape` as `coord_grid` and represents a new coordinate grid
    after one iteration. The second `Tensor` is of the same shape and `dtype`
    as`value_grid` and represents an approximate solution of the equation after
    one iteration.
  """
  with tf.compat.v1.name_scope(name, 'parabolic_equation_step',
                               [time, next_time, coord_grid, value_grid]):
    time = tf.convert_to_tensor(time, dtype=dtype, name='time')
    next_time = tf.convert_to_tensor(next_time, dtype=dtype, name='next_time')
    coord_grid = [tf.convert_to_tensor(x, dtype=dtype,
                                       name='coord_grid_axis_{}'.format(ind))
                  for ind, x in enumerate(coord_grid)]
    value_grid = tf.convert_to_tensor(value_grid, dtype=dtype,
                                      name='value_grid')

    first_order_coeff_fn = first_order_coeff_fn or (lambda *args: [0.0])
    zeroth_order_coeff_fn = zeroth_order_coeff_fn or (lambda *args: 0.0)

    inner_grid_in = value_grid[..., 1:-1]
    coord_grid_deltas = coord_grid[0][1:] - coord_grid[0][:-1]

    def equation_params_fn(t):
      return _construct_space_discretized_eqn_params(coord_grid,
                                                     coord_grid_deltas,
                                                     value_grid,
                                                     boundary_conditions,
                                                     second_order_coeff_fn,
                                                     first_order_coeff_fn,
                                                     zeroth_order_coeff_fn,
                                                     t)
    inner_grid_out = time_marching_scheme(
        value_grid=inner_grid_in,
        t1=next_time,
        t2=time,
        equation_params_fn=equation_params_fn,
        backwards=True)

    updated_value_grid = _apply_boundary_conditions_after_step(
        inner_grid_out, boundary_conditions,
        coord_grid, coord_grid_deltas, next_time)
    return coord_grid, updated_value_grid


def _construct_space_discretized_eqn_params(coord_grid,
                                            coord_grid_deltas,
                                            value_grid,
                                            boundary_conditions,
                                            second_order_coeff_fn,
                                            first_order_coeff_fn,
                                            zeroth_order_coeff_fn,
                                            t):
  """Constructs the tridiagonal matrix and the inhomogeneous term."""
  # The space-discretized PDE has the form dv/dt = A(t) v(t) + b(t), where
  # v(t) is V(t, x) discretized by x, A(t) is a tridiagonal matrix and b(t) is
  # a vector. A(t) and b(t) depend on the PDE coefficients and the boundary
  # conditions. This function constructs A(t) and b(t). See construction of
  # A(t) e.g. in [Forsyth, Vetzal][1] (we denote `beta` and `gamma` from the
  # paper as `dx_coef` and `dxdx_coef`).

  # Get forward, backward and total differences.
  forward_deltas = coord_grid_deltas[1:]
  backward_deltas = coord_grid_deltas[:-1]
  # Note that sum_deltas = 2 * central_deltas.
  sum_deltas = forward_deltas + backward_deltas

  # 3-diagonal matrix construction. See matrix `M` in [Forsyth, Vetzal][1].
  #  The `tridiagonal` matrix is of shape
  # `[value_dim, 3, num_grid_points]`.

  # Get the PDE coefficients and broadcast them to the shape of value grid.
  second_order_coeff = _prepare_pde_coeffs(
      second_order_coeff_fn(t, coord_grid)[0][0], value_grid)
  first_order_coeff = _prepare_pde_coeffs(
      first_order_coeff_fn(t, coord_grid)[0], value_grid)
  zeroth_order_coeff = _prepare_pde_coeffs(zeroth_order_coeff_fn(t, coord_grid),
                                           value_grid)

  # Here `dxdx_coef` is coming from the discretization of `V_{xx}` and
  # `dx_coef` is from discretization of `V_{x}`.
  temp = 2 * second_order_coeff / sum_deltas
  dxdx_coef_1 = temp / forward_deltas
  dxdx_coef_2 = temp / backward_deltas
  dx_coef = first_order_coeff / sum_deltas

  # The 3 main diagonals are constructed below. Note that all the diagonals
  # are of the same length
  upper_diagonal = (-dx_coef - dxdx_coef_1)
  lower_diagonal = (dx_coef - dxdx_coef_2)
  diagonal = -zeroth_order_coeff - upper_diagonal - lower_diagonal

  return _apply_boundary_conditions_to_discretized_equation(
      boundary_conditions,
      coord_grid, coord_grid_deltas,
      diagonal, upper_diagonal, lower_diagonal, t)


def _apply_boundary_conditions_to_discretized_equation(
    boundary_conditions,
    coord_grid, coord_grid_deltas, diagonal, upper_diagonal, lower_diagonal, t):
  """Updates space-discretized equation according to boundary conditions."""
  # Without taking into account the boundary conditions, the space-discretized
  # PDE has the form dv/dt = A(t) v(t), where v(t) is V(t, x) discretized by
  # x, and A is the tridiagonal matrix defined by coefficients of the PDE.
  # Boundary conditions change the first and the last row of A and introduce
  # the inhomogeneous term, so the equation becomes dv/dt = A'(t) v(t) + b(t),
  # where A' is the modified matrix, and b is a vector.
  # This function receives A and returns A' and b.

  # Retrieve the boundary conditions in the form alpha V + beta V' = gamma.
  alpha_l, beta_l, gamma_l = boundary_conditions[0][0](t, coord_grid)
  alpha_u, beta_u, gamma_u = boundary_conditions[0][1](t, coord_grid)

  if beta_l is None and beta_u is None:
    # Dirichlet conditions on both boundaries. In this case there are no
    # corrections to the tridiagonal matrix, so we can take a shortcut.
    first_inhomog_element = lower_diagonal[..., 0] * gamma_l / alpha_l
    last_inhomog_element = upper_diagonal[..., -1] * gamma_u / alpha_u
    inhomog_term = _append_first_and_last(first_inhomog_element,
                                          tf.zeros_like(diagonal[..., 1:-1]),
                                          last_inhomog_element)
    return (diagonal, upper_diagonal, lower_diagonal), inhomog_term

  # Convert the boundary conditions into the form v0 = xi1 v1 + xi2 v2 + eta,
  # and calculate corrections to the tridiagonal matrix and the inhomogeneous
  # term.
  xi1, xi2, eta = _discretize_boundary_conditions(coord_grid_deltas[0],
                                                  coord_grid_deltas[1],
                                                  alpha_l,
                                                  beta_l, gamma_l)
  diag_first_correction = lower_diagonal[..., 0] * xi1
  upper_diag_correction = lower_diagonal[..., 0] * xi2
  first_inhomog_element = lower_diagonal[..., 0] * eta
  xi1, xi2, eta = _discretize_boundary_conditions(coord_grid_deltas[-1],
                                                  coord_grid_deltas[-2],
                                                  alpha_u,
                                                  beta_u, gamma_u)
  diag_last_correction = upper_diagonal[..., -1] * xi1
  lower_diag_correction = upper_diagonal[..., -1] * xi2
  last_inhomog_element = upper_diagonal[..., -1] * eta
  diagonal = _append_first_and_last(diagonal[..., 0] + diag_first_correction,
                                    diagonal[..., 1:-1],
                                    diagonal[..., -1] + diag_last_correction)
  upper_diagonal = _append_first(
      upper_diagonal[..., 0] + upper_diag_correction, upper_diagonal[..., 1:])
  lower_diagonal = _append_last(
      lower_diagonal[..., :-1],
      lower_diagonal[..., -1] + lower_diag_correction)
  inhomog_term = _append_first_and_last(first_inhomog_element,
                                        tf.zeros_like(diagonal[..., 1:-1]),
                                        last_inhomog_element)
  return (diagonal, upper_diagonal, lower_diagonal), inhomog_term


def _apply_boundary_conditions_after_step(
    inner_grid_out, boundary_conditions,
    coord_grid, coord_grid_deltas, time_after_step):
  """Calculates and appends boundary values after making a step."""
  # After we've updated the values in the inner part of the grid according to
  # the PDE, we append the boundary values calculated using the boundary
  # conditions.
  # This is done using the discretized form of the boundary conditions,
  # v0 = xi1 v1 + xi2 v2 + eta.

  alpha, beta, gamma = boundary_conditions[0][0](time_after_step,
                                                 coord_grid[0][0])
  xi1, xi2, eta = _discretize_boundary_conditions(coord_grid_deltas[0],
                                                  coord_grid_deltas[1],
                                                  alpha, beta, gamma)
  first_value = (
      xi1 * inner_grid_out[..., 0] + xi2 * inner_grid_out[..., 1] + eta)
  alpha, beta, gamma = boundary_conditions[0][1](time_after_step,
                                                 coord_grid)
  xi1, xi2, eta = _discretize_boundary_conditions(coord_grid_deltas[-1],
                                                  coord_grid_deltas[-2],
                                                  alpha, beta, gamma)
  last_value = (
      xi1 * inner_grid_out[..., -1] + xi2 * inner_grid_out[..., -2] + eta)
  return _append_first_and_last(first_value, inner_grid_out, last_value)


def _prepare_pde_coeffs(raw_coeffs, value_grid):
  """Prepares values received from second_order_coeff_fn and similar."""
  dtype = value_grid.dtype
  coeffs = tf.convert_to_tensor(raw_coeffs, dtype=dtype)

  broadcast_shape = tf.shape(value_grid)
  coeffs = tf.broadcast_to(coeffs, broadcast_shape)

  # Trim coefficients on boundaries. We don't need them, because the boundary
  # values don't satisfy the PDE, they are restored using boundary conditions
  # instead.
  coeffs = coeffs[..., 1:-1]
  return coeffs


def _discretize_boundary_conditions(dx0, dx1, alpha, beta, gamma):
  """Discretizes boundary conditions."""
  # Converts a boundary condition given as alpha V + beta V_n = gamma,
  # where V_n is the derivative w.r.t. the normal to the boundary into
  # v0 = xi1 v1 + xi2 v2 + eta,
  # where v0 is the value on the boundary point of the grid, v1 and v2 - values
  # on the next two points on the grid.
  # The expressions are exactly the same for both boundaries.

  if beta is None:
    # Dirichlet condition.
    if alpha is None:
      raise ValueError(
          "Invalid boundary conditions: alpha and beta can't both be None.")
    zeros = tf.zeros_like(gamma)
    return zeros, zeros, gamma / alpha

  denom = beta * dx1 * (2 * dx0 + dx1)
  if alpha is not None:
    denom += alpha * dx0 * dx1 * (dx0 + dx1)
  xi1 = beta * (dx0 + dx1) * (dx0 + dx1) / denom
  xi2 = -beta * dx0 * dx0 / denom
  eta = gamma * dx0 * dx1 * (dx0 + dx1) / denom
  return xi1, xi2, eta


def _append_first_and_last(first, inner, last):
  return tf.concat((tf.expand_dims(first, -1), inner, tf.expand_dims(last, -1)),
                   -1)


def _append_first(first, rest):
  return tf.concat((tf.expand_dims(first, -1), rest), -1)


def _append_last(rest, last):
  return tf.concat((rest, tf.expand_dims(last, -1)), -1)
