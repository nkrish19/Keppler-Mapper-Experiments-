# -*- coding: utf-8 -*-
"""pllay

Automatically generated by Colaboratory.
"""

import numpy as np
import tensorflow.compat.v2 as tf
import gudhi
from sklearn.neighbors import NearestNeighbors
from sklearn.model_selection import ParameterGrid
import time

tf.enable_v2_behavior()
#tf.compat.v1.flags.DEFINE_string('f', '', 'kernel')

"""# Layer Definitions"""

# @tf.function
def tf_scatter(indices, updates, params_shape, batch_dims=0, name=None):
  """Inverse of tf.gather.

  Args:
    indices: tensor of shape [..., N], with values in in [0, M)
    updates: tensor of shape [..., N, ...] indices.shape + params_shape[batch_dims + 1:]
    params_shape: target tensor shape [..., M, ...]
    batch_dims: int. The first batch_dims axes of indices and updates must match exactly

  Returns:
    params: tensor of shape params_shape

  """

  # params_shape = list(params_shape)
  B = tf.reduce_prod(indices.shape[:batch_dims])
  T = B*indices.shape[batch_dims]
  flatten_indices = tf.reshape(indices, [T, 1])
  flatten_updates = tf.reshape(updates, [T] + params_shape[batch_dims+1:])
  
  prefix_indices = tf.broadcast_to(tf.expand_dims(tf.range(B), 1), [B, indices.shape[batch_dims]])
  flatten_prefix = tf.reshape(prefix_indices, [T, 1])
  full_indices = tf.concat((flatten_prefix, flatten_indices), axis=1)

  # print(full_indices.shape, flatten_updates.shape, [B] + params_shape[batch_dims:], params_shape)
  flatten_params = tf.scatter_nd(full_indices, flatten_updates, [B] + params_shape[batch_dims:])
  return tf.reshape(flatten_params, params_shape)

def tf_dtmFromKnnDistance(knnDistance, weightBound, r=2.):
  """TF Distance to measure using KNN.

  Args:
    knnDistance: Tensor of shape [..., N, k]
    weightBound: Float weight bound
    r: Int r-Norm

  Returns:
    dtmValue: Tensor of shape [..., N]
  """
  dtmValue = None
  weightSumTemp = tf.math.ceil(weightBound)
  index_int = tf.cast(weightSumTemp, tf.int32) - 1
  if r == 2.0:
    distanceTemp = tf.square(knnDistance)
    cumDistance = tf.math.cumsum(distanceTemp, -1)
    dtmValue = cumDistance[..., index_int] + distanceTemp[..., index_int] * (weightBound - weightSumTemp)
    dtmValue = tf.sqrt(dtmValue/weightBound)
  elif r == 1.0:
    distanceTemp = knnDistance
    cumDistance = tf.math.cumsum(distanceTemp, -1)
    dtmValue = cumDistance[..., index_int] + distanceTemp[..., index_int] * (weightBound - weightSumTemp)
    dtmValue = dtmValue/weightBound
  else:
    distanceTemp = tf.math.pow(knnDistance, r)
    cumDistance = tf.math.cumsum(distanceTemp, -1)
    dtmValue = cumDistance[..., index_int] + distanceTemp[..., index_int] * (weightBound - weightSumTemp)
    dtmValue = tf.math.pow(dtmValue/weightBound, 1/r)
  return dtmValue
	

def tf_dtmFromKnnDistanceWeight(knnDistance, knnIndex, weight, weightBound, r=2.):
  """TF Weighted Distance to measure using KNN.

  Args:
    knnDistance: Tensor of shape [..., N, k]
    knnIndex: Tensor of shape [..., N, k]
    weight: Tensor of shape [..., M]
    weightBound: Tensor of shape [..., 1]
    r: Int r-Norm

  Returns:
    dtmValue: Tensor of shape [..., N]
  """
  dtmValue = None
  weightBound = tf.expand_dims(weightBound, -1)
  weightTemp = tf.gather(weight, knnIndex, batch_dims=len(weight.shape)-1)  # [..., N, k]
  weightSumTemp = tf.math.cumsum(weightTemp, -1)
  index_int = tf.searchsorted(weightSumTemp, tf.repeat(weightBound, knnDistance.shape[-2], -2))  # [..., N, 1]
  if r == 2.0:
    distanceTemp = tf.square(knnDistance)
    cumDistance = tf.math.cumsum(distanceTemp * weightTemp, -1)
    dtmValue = tf.gather(cumDistance +  distanceTemp*(weightBound-weightSumTemp), index_int, batch_dims=len(knnDistance.shape)-1)
    dtmValue = tf.sqrt(dtmValue/weightBound)
  elif r == 1.0:
    distanceTemp = knnDistance
    cumDistance = tf.math.cumsum(distanceTemp * weightTemp, -1)
    dtmValue = tf.gather(cumDistance +  distanceTemp*(weightBound-weightSumTemp), index_int, batch_dims=len(knnDistance.shape)-1)
    dtmValue = dtmValue/weightBound
  else:
    distanceTemp = tf.math.pow(knnDistance, r)
    cumDistance = tf.math.cumsum(distanceTemp * weightTemp, -1)
    dtmValue = tf.gather(cumDistance +  distanceTemp*(weightBound-weightSumTemp), index_int, batch_dims=len(knnDistance.shape)-1)
    dtmValue = tf.math.pow(dtmValue/weightBound, 1/r)
  return tf.squeeze(dtmValue, -1)

def tf_knn(X, Y, k, r=2.):
  """TF Brute Force KNN.

  Args:
    X: Tensor of shape [..., M, D]
    Y: Tensor of shape [N, D]
    k: Int representing number of neighbors

  Returns:
    distance: Tensor of shape [..., N, k]
    index: Tensor of shape [..., N, k]
  """
  # print(X.shape, Y.shape)
  assert X.shape[-1] == Y.shape[1]
  d = X.shape[-1]
  if r == 2.0:
    Xr = tf.reshape(X, (-1, d))
    Yr = tf.reshape(Y, (-1, d))
    XY = tf.einsum('ik,jk->ij', Xr, Yr)
    X2 = tf.reduce_sum(tf.square(Xr), 1, keepdims=True)
    Y2 = tf.expand_dims(tf.reduce_sum(tf.square(Yr), 1), 0)
    neg_dist = - tf.sqrt(tf.maximum(X2 + Y2 - 2.0 * XY, 0.))
  elif r == 1.0:
    Xr = tf.reshape(X, (-1, 1, d))
    Yr = tf.reshape(Y, (1, -1, d))
    XY = tf.reduce_sum(tf.abs(Xr - Yr), -1)
    neg_dist = - XY
  else:
    Xr = tf.reshape(X, (-1, 1, d))
    Yr = tf.reshape(Y, (1, -1, d))
    XY = tf.reduce_sum(tf.pow(tf.abs(Xr - Yr), r), -1)
    neg_dist = - tf.math.pow(XY, 1/r)
  neg_dist = tf.reshape(neg_dist, X.shape[:-1] + Y.shape[0])  # [..., M, N]
  neg_dist = tf.transpose(neg_dist, tf.concat((tf.range(0, tf.rank(X)-2), [tf.rank(X)-1, tf.rank(X)-2]), 0) )
  distance, index = tf.math.top_k(neg_dist, k)  # [..., N, k]
  return -distance, index

def tf_gridBy(lims, by):
  if np.ndim(by) == 0:
    by = np.repeat(by, repeats=len(lims))
  expansions = [tf.range(x, y+byd, delta=byd, dtype=tf.float32) for (x, y), byd in zip(lims, by)]
  dim = [len(ex) for ex in expansions]
  grid = tf.reshape(tf.transpose(tf.stack(tf.meshgrid(*expansions, indexing='ij'), 0)), [-1, len(lims)])
  return grid, dim



class DTMLayer(tf.keras.layers.Layer):

  def __init__(self, 
               m0=0.3,
               lims=[[-1., 1.], [-1., 1.]], 
               by=1, 
               r=2.0, 
               name='dtmlayer', 
               **kwargs):
    super(DTMLayer, self).__init__(name=name)
    self.m0 = m0
    self.r = r
    self.grid, self.grid_size = tf_gridBy(lims, by)

  def dtm(self, inputs):
    """TF Without Weighted Distance to measure using KNN.

    Args:
      inputs: Tensor of shape [..., M, d]

    Returns:
      dtmValue: Tensor of shape [..., N]
      knnIndex: Tensor of shape [..., N, k]
      weightBound: Tensor of shape []
    """
    weightBound = self.m0 * inputs.shape[-2]
    weightBoundCeil = tf.math.ceil(weightBound)
    knnDistance, knnIndex = tf_knn(inputs, self.grid, tf.cast(weightBoundCeil, tf.int32))
    return tf_dtmFromKnnDistance(knnDistance, weightBound, self.r), knnIndex, weightBound

  def dtm_grad(self, inputs, dtmValue, knnIndex, weightBound):
    """TF Graident of Without Weighted Distance to measure using KNN.

    Args:
      inputs: Tensor of shape [..., M, d]
      dtmValue: Tensor of shape [..., N]
      knnIndex: Tensor of shape [..., N, k]
      weightBound: Tensor of shape []

    Returns:
      dtmDiff: Tensor of shape [..., N, M, d]
    """
    weightBoundCeil = tf.math.ceil(weightBound)

    Xa = tf.gather(inputs, knnIndex, batch_dims=len(knnIndex.shape)-2)
    dtmDiff = Xa - tf.expand_dims(self.grid, 1)  # [..., N, k, d]
    dtmLastValue = dtmDiff[..., -1:, :] * (1. + weightBound - weightBoundCeil)
    sparse_dtmDiff = tf.concat((dtmDiff[..., :-1, :], dtmLastValue), -2)

    dtmDiff = tf_scatter(knnIndex, sparse_dtmDiff, knnIndex.shape[:-1] + inputs.shape[-2:], batch_dims=len(knnIndex.shape)-1)
    dtmDiff /= (weightBound * tf.reshape(dtmValue, dtmValue.shape + [1, 1]))
    return dtmDiff

  # @tf.custom_gradient
  # def call(self, inputs):
  #   """.

  #   Args:
  #     inputs: tensor of shape [..., M, d]

  #   Returns:
  #     outputs: tensor of shape [..., N]
  #   """
  #   dtmValue, knnIndex, weightBound = self.dtm(inputs)
  #   def grad(dy):
  #     """"dy: [..., N]."""
  #     dtmDiff = self.dtm_grad(inputs, dtmValue, knnIndex, weightBound)
  #     return tf.einsum('...i,...ijk->...jk', dy, dtmDiff)
  #   return dtmValue, grad

  def call(self, inputs, weights=None):
    """.

    Args:
      inputs: tensor of shape [..., M, d]

    Returns:
      outputs: tensor of shape [..., N]
    """
    dtmValue, knnIndex, weightBound = self.dtm(inputs)
    return dtmValue



class DTMWeightLayer(tf.keras.layers.Layer):

  def __init__(self, 
               m0=0.3,
               lims=[[-1., 1.], [-1., 1.]], 
               by=1, 
               r=2.0, 
               name='dtmweightlayer', 
               **kwargs):
    super(DTMWeightLayer, self).__init__(name=name)
    self.m0 = m0
    self.r = r
    self.grid, self.grid_size = tf_gridBy(lims, by)

  def dtm(self, inputs, weight):
    """TF Weighted Distance to measure using KNN.

    Args:
      inputs: Tensor of shape [..., M, d]
      weight: Tensor of shape [..., M]

    Returns:
      dtmValue: Tensor of shape [..., N]
      knnIndex: Tensor of shape [..., N, k]
      weightBound: Tensor of shape [..., 1]
    """
    weightsort = tf.sort(weight)  # [..., M]
    weightBound = self.m0 * tf.reduce_sum(weight, -1, keepdims=True)  # [..., 1]
    weightSumTemp = tf.math.cumsum(weightsort, -1)  # [..., M]
    index_int = tf.searchsorted(weightSumTemp, weightBound) # [..., 1]
    max_index_int = tf.reduce_max(index_int) + 1
    # if (max_index_int <= 0):
    #   print("max_index_int nonpositive!")
    #   print(max_index_int)
    #   print("inputs:")
    #   print(inputs)
    #   print("weight:")
    #   print(weight)

    knnDistance, knnIndex = tf_knn(inputs, self.grid, tf.cast(max_index_int, tf.int32))

    return tf_dtmFromKnnDistanceWeight(knnDistance, knnIndex, weight, weightBound, self.r), knnIndex, weightBound

  def dtm_grad_x(self, inputs, weight, dtmValue, knnIndex, weightBound):
    """TF Graident of With Weighted Distance to measure using KNN.

    Args:
      inputs: Tensor of shape [..., M, d]
      weight: Tensor of shape [..., M]
      dtmValue: Tensor of shape [..., N]
      knnIndex: Tensor of shape [..., N, k]
      weightBound: Tensor of shape [..., 1]

    Returns:
      dtmDiff: Tensor of shape [..., N, M, d]
      index_int: Tensor of shape [..., N, 1]
      mask: Tensor of shape [..., N, k-1]
    """
    weightBound = tf.expand_dims(weightBound, -1) # [..., 1, 1]
    weightTemp = tf.gather(weight, knnIndex, batch_dims=len(weight.shape)-1)  # [..., N, k]
    weightSumTemp = tf.math.cumsum(weightTemp, -1)
    index_int = tf.searchsorted(weightSumTemp, tf.repeat(weightBound, knnIndex.shape[-2], -2))  # [..., N, 1]
    mask = tf.sequence_mask(tf.squeeze(index_int, -1), dtype=tf.float32)  # [..., N, k]

    weightBound = tf.expand_dims(weightBound, -1)  # [..., 1, 1, 1]
    weightSumTemp = tf.expand_dims(weightSumTemp, -1)  # [..., N, k, 1] 
    Xa = tf.gather(inputs, knnIndex, batch_dims=len(knnIndex.shape)-2)
    unweightDtmDiff = (Xa - tf.expand_dims(self.grid, 1))  # [..., N, k, d]
    dtmDiff = tf.expand_dims(weightTemp, -1) * unweightDtmDiff
    dtmLastValue = tf.gather(dtmDiff + unweightDtmDiff * (weightBound - weightSumTemp), index_int, batch_dims=len(knnIndex.shape)-1)
    mask_dtmDiff = dtmDiff[..., :-1, :] * tf.expand_dims(mask, -1)
    sparse_dtmDiff = tf.concat((mask_dtmDiff, dtmLastValue), -2)

    knnLastIndex = tf.gather(knnIndex, index_int, batch_dims=len(knnIndex.shape)-1)
    sparse_knnIndex = tf.concat((knnIndex[..., :-1], knnLastIndex), -1)

    dtmDiff = tf_scatter(sparse_knnIndex, sparse_dtmDiff, knnIndex.shape[:-1] + inputs.shape[-2:], batch_dims=len(knnIndex.shape)-1)
    dtmDiff /= (weightBound * tf.reshape(dtmValue, dtmValue.shape + [1, 1]))
    return dtmDiff, index_int, mask

  def dtm_grad_w(self, inputs, dtmValue, knnIndex, weightBound, index_int, mask):
    """TF Graident of With Weighted Distance to measure using KNN.

    Args:
      inputs: Tensor of shape [..., M, d]
      dtmValue: Tensor of shape [..., N]
      knnIndex: Tensor of shape [..., N, k]
      weightBound: Tensor of shape [..., 1]
      index_int: Tensor of shape [..., N, 1]
      mask: Tensor of shape [..., N, k-1]

    Returns:
      dtmDiff: Tensor of shape [..., N, M]
    """
    Xa = tf.gather(inputs, knnIndex, batch_dims=len(knnIndex.shape)-2)
    unweightDtmDiff = tf.square(Xa - tf.expand_dims(self.grid, 1))  # [..., N, k, d]
    unweightDtmDiff = tf.reduce_sum(unweightDtmDiff, -1)  # [..., N, k]

    # dtmDiff: [..., N, k]
    last_dtmDiff = tf.gather(unweightDtmDiff, index_int, batch_dims=len(knnIndex.shape)-1)  # [..., N, 1]
    mask_dtmDiff = (unweightDtmDiff[..., :-1] - last_dtmDiff)* mask  # [..., N, k-1]
    dtmDiff = tf_scatter(knnIndex[..., :-1], mask_dtmDiff, knnIndex.shape[:-1] + inputs.shape[-2:-1], batch_dims=len(knnIndex.shape)-1)

    # dtmDiff: [..., N, M]
    dtmValue = tf.expand_dims(dtmValue, -1)  # [..., N, 1]
    weightBound = tf.expand_dims(weightBound, -1)  # [..., 1, 1]
    dtmDiff = (dtmDiff + self.m0 * last_dtmDiff - self.m0 * tf.square(dtmValue)) / (2 * weightBound * dtmValue)
    return dtmDiff

  # @tf.custom_gradient
  # def call(self, inputs, weight):
  #   """.

  #   Args:
  #     inputs: tensor of shape [..., M, d]
  #     weight: tensor of shape [..., M]

  #   Returns:
  #     outputs: tensor of shape [..., N]
  #   """
  #   dtmValue, knnIndex, weightBound = self.dtm(inputs, weight)
  #   def grad(dy):
  #     """"dy: [..., N]."""
  #     dtmDiff_x, index_int, mask = self.dtm_grad_x(inputs, weight, dtmValue, knnIndex, weightBound)
  #     dtmDiff_w = self.dtm_grad_w(inputs, dtmValue, knnIndex, weightBound, index_int, mask)
  #     return tf.einsum('...i,...ijk->...jk', dy, dtmDiff_x), tf.einsum('...i,...ij->...j', dy, dtmDiff_w)
  #   return dtmValue, grad

  def call(self, inputs, weight):
    """.

    Args:
      inputs: tensor of shape [..., M, d]
      weight: tensor of shape [..., M]

    Returns:
      outputs: tensor of shape [..., N]
    """
    dtmValue, knnIndex, weightBound = self.dtm(inputs, weight)
    return dtmValue



class PersistenceLandscapeLayer(tf.keras.layers.Layer):

  def __init__(self, 
               tseq=[0.5, 0.7, 0.9],
               KK=[0,1], 
               grid_size=[3, 3],
               dimensions=[0, 1], 
               dtype='float32',
               name='persistencelandscapelayer', 
               **kwargs):
    super(PersistenceLandscapeLayer, self).__init__(name=name)
    self.dtype == dtype
    self.tseq = np.array(tseq, dtype=dtype)
    self.KK = np.array(KK, dtype=np.int32)
    self.grid_size = grid_size
    self.dimensions = dimensions

  def python_op_diag_landscape(self, fun_value):
    """Python domain function to compute landscape.
    
    It also computes things needed for gradient, as we don't want to enter
    python multiple times.
    Args:
      FUNvalue: numpy array of shape [N]

    Returns:
      land: numpy array of shape [len(dims), len(tseq), len(KK)]
      diff: numpy array of shape [N, len(dims), len(tseq), len(KK)]
    """
    # Use gudhi to compute persistence diagram
    # print('fun_value', fun_value.shape, repr(fun_value))
    cubCpx = gudhi.CubicalComplex(dimensions=self.grid_size, top_dimensional_cells=fun_value)
    pDiag = cubCpx.persistence(homology_coeff_field=2, min_persistence=0)
    # print('pDiag', pDiag)
    location = cubCpx.cofaces_of_persistence_pairs()
    if location[0]:
      locationVstack = [np.vstack(location[0]), np.vstack(location[1])]
    else:
      locationVstack = [np.zeros((0, 2), dtype=np.int32), np.vstack(location[1])]
    locationBirth = np.concatenate((locationVstack[0][:, 0], locationVstack[1][:, 0])).astype(np.int32)
    # locationBirth = np.concatenate((np.vstack(location[0])[:, 0], 
    #                                 np.vstack(location[1])[:, 0])).astype(np.int32)
    locationDeath = locationVstack[0][:, 1].astype(np.int32)

    # lengths
    len_dim = len(self.dimensions)
    len_tseq = len(self.tseq)
    len_KK = len(self.KK)
    len_pDiag = len(pDiag)

    land = np.zeros((len_dim, len_tseq, len_KK), dtype=self.dtype)
    landDiffBirth = np.zeros((len_dim, len_tseq, len_KK, len_pDiag), dtype=self.dtype)
    landDiffDeath = np.zeros((len_dim, len_tseq, len_KK, len_pDiag), dtype=self.dtype)

    for iDim, dim in enumerate(self.dimensions):
      # select 0 dimension feature
      pDiagDim = [pair for pair in pDiag if pair[0] == dim]
      pDiagDimIds = np.array([iDiag for iDiag, pair in enumerate(pDiag) if pair[0] == dim], dtype=np.int32)

      # local lengths
      len_pDiagDim = len(pDiagDim)

      # Arrange it
      # print(len_pDiag, len_pDiagDim, len_tseq, len_KK)
      fab = np.zeros((len_tseq, max(len_pDiagDim, np.max(self.KK)+1)), dtype=self.dtype)
      for iDiagDim in range(len_pDiagDim):
        for iT in range(len_tseq):
          fab[iT, iDiagDim] = max(min(self.tseq[iT] - pDiagDim[iDiagDim][1][0], pDiagDim[iDiagDim][1][1] - self.tseq[iT]), 0)

      # return
      land[iDim] = -np.sort(-fab, axis=-1)[:, self.KK]
      landIndex = np.argsort(-fab, axis = -1)[:, self.KK]

      fabDiffBirth = np.zeros((len_tseq, len_pDiagDim), dtype=self.dtype)
      for iDiagDim in range(len_pDiagDim):
          fabDiffBirth[:, iDiagDim] = np.where((self.tseq > pDiagDim[iDiagDim][1][0]) & (2 * self.tseq < pDiagDim[iDiagDim][1][0] + pDiagDim[iDiagDim][1][1]), -1., 0.)
      fabDiffDeath = np.zeros((len_tseq, len_pDiagDim), dtype=self.dtype)
      for iDiagDim in range(len_pDiagDim):
          fabDiffDeath[:, iDiagDim] = np.where((self.tseq < pDiagDim[iDiagDim][1][1]) & (2 * self.tseq > pDiagDim[iDiagDim][1][0] + pDiagDim[iDiagDim][1][1]), 1., 0.)

      for iDiagDim in range(len_pDiagDim):
          landDiffBirth[iDim, :, :, pDiagDimIds[iDiagDim]] = np.where(iDiagDim == landIndex, np.repeat(np.expand_dims(fabDiffBirth[:, iDiagDim], -1), len_KK, -1), 0)
      for iDiagDim in range(len_pDiagDim):
          landDiffDeath[iDim, :, :, pDiagDimIds[iDiagDim]] = np.where(iDiagDim == landIndex, np.repeat(np.expand_dims(fabDiffDeath[:, iDiagDim], -1), len_KK, -1), 0)

    DiagFUNDiffBirth = np.zeros((len_pDiag, len(fun_value)), dtype=self.dtype)
    for iBirth in range(len(locationBirth)):
        DiagFUNDiffBirth[iBirth, locationBirth[iBirth]] = 1
    DiagFUNDiffDeath = np.zeros((len_pDiag, len(fun_value)), dtype=self.dtype)
    for iDeath in range(len(locationDeath)):
        DiagFUNDiffDeath[iDeath, locationDeath[iDeath]] = 1	

    if location[0]:
      dimension = np.concatenate((np.hstack([np.repeat(ldim, len(location[0][ldim])) for ldim in range(len(location[0]))]),
                                  np.hstack([np.repeat(ldim, len(location[1][ldim])) for ldim in range(len(location[1]))])))
    else:
      dimension = np.hstack([np.repeat(ldim, len(location[1][ldim])) for ldim in range(len(location[1]))])
    if len(locationDeath) > 0:
      persistence = np.concatenate((fun_value[locationDeath], np.repeat(np.infty, len(np.vstack(location[1]))))) - fun_value[locationBirth]
    else:
      persistence = np.repeat(np.infty, len(np.vstack(location[1])))
    order = np.lexsort((-persistence, -dimension))
    
    diff = np.dot(landDiffBirth, DiagFUNDiffBirth[order, :]) + np.dot(landDiffDeath, DiagFUNDiffDeath[order, :])
    # print(landDiffBirth.dtype, DiagFUNDiffBirth.dtype, landDiffDeath.dtype, DiagFUNDiffDeath.dtype)
    # print(land.shape, landDiffBirth.shape, DiagFUNDiffBirth[order, :].shape, landDiffDeath.shape, DiagFUNDiffDeath[order, :].shape, diff.shape)
    return land, diff

  @tf.custom_gradient
  def call(self, inputs):
    """.

    Args:
      inputs: tensor of shape [..., N]

    Returns:
      outputs: tensor of shape [..., len(tseq), len(KK)]
    """
    land, dLdf = tf.map_fn(
        lambda x: tf.compat.v1.py_func(self.python_op_diag_landscape, 
                                       [x], [tf.float32, tf.float32], stateful=False), 
                     inputs, [tf.float32, tf.float32], parallel_iterations=10, back_prop=False)
    # aa = [tf.compat.v1.py_func(self.python_op_diag_landscape, 
    #                                    [x], [tf.float32, tf.float32], stateful=False) for x in tf.unstack(inputs)]
    # land, dLdf = zip(*aa)
    # land = tf.stack(land)
    # dLdf = tf.stack(dLdf)
    # land, dLdf = tf.vectorized_map(lambda x: tf.compat.v1.py_func(self.python_op_diag_landscape, 
    #                                    [x], [tf.float32, tf.float32], stateful=False), 
    #                  inputs,)
    land.set_shape(inputs.shape[:-1] + [len(self.dimensions), len(self.tseq), len(self.KK)])
    dLdf.set_shape(inputs.shape[:-1] + [len(self.dimensions), len(self.tseq), len(self.KK)] + inputs.shape[-1:])
    def grad(dy):
      return tf.einsum('...ijk,...ijkl->...l', dy, dLdf)
    return land, grad



class PersistenceDiagramLayer(tf.keras.layers.Layer):

  def __init__(self, 
               grid_size=[3, 3],
               dimensions=[0, 1], 
               nmax_diag=100,
               dtype='float32',
               name='persistencediagramlayer', 
               **kwargs):
    super(PersistenceDiagramLayer, self).__init__(name=name)
    self.dtype == dtype
    self.grid_size = grid_size
    self.dimensions = dimensions
    self.nmax_diag = nmax_diag
  def python_op_diag(self, fun_value):
    """Python domain function to compute landscape.
    
    It also computes things needed for gradient, as we don't want to enter
    python multiple times.
    Args:
      FUNvalue: numpy array of shape [N]

    Returns:
    """
    # Use gudhi to compute persistence diagram
    # print('fun_value', fun_value.shape, repr(fun_value))

    cubCpx = gudhi.CubicalComplex(dimensions=self.grid_size, top_dimensional_cells=fun_value)
    pDiag = cubCpx.persistence(homology_coeff_field=2, min_persistence=0)

    pDiagList = [None] * len(self.dimensions)
    for iDim, dim in enumerate(self.dimensions):
      # select 0 dimension feature
      pDiagDim = [pair[1] for pair in pDiag if pair[0] == dim]
      pDiagList[iDim] = pDiagDim
    
    diag = np.zeros((len(self.dimensions), self.nmax_diag, 2), dtype='float32')
    for iDim in range(len(self.dimensions)):
      nDimDiag = min(len(pDiagList[iDim]), self.nmax_diag)
      if (nDimDiag > 0):
        diag[iDim][0:nDimDiag] = pDiagList[iDim][0:nDimDiag]

    # return pDiagList
    # return np.pad(pDiagList[0], ((0, 30-len(pDiagList[0])), (0, 0))).astype('float32'), np.pad(pDiagList[1], ((0, 30-len(pDiagList[0])), (0, 0))).astype('float32')
    return diag


  def call(self, inputs):
    """.

    Args:
      inputs: tensor of shape [..., N]

    Returns:
      outputs: tensor of shape [..., len(tseq), len(KK)]
    """
    diag = tf.map_fn(
        lambda x: tf.compat.v1.py_func(self.python_op_diag, 
                                       [x], tf.float32, stateful=False), 
                     inputs, tf.float32, parallel_iterations=10, back_prop=False)
    # aa = [tf.compat.v1.py_func(self.python_op_diag_landscape, 
    #                                    [x], [tf.float32, tf.float32], stateful=False) for x in tf.unstack(inputs)]
    # land, dLdf = zip(*aa)
    # land = tf.stack(land)
    # dLdf = tf.stack(dLdf)
    # land, dLdf = tf.vectorized_map(lambda x: tf.compat.v1.py_func(self.python_op_diag_landscape, 
    #                                    [x], [tf.float32, tf.float32], stateful=False), 
    #                  inputs,)
    # land.set_shape(inputs.shape[:-1] + [len(self.dimensions), len(self.tseq), len(self.KK)])
    # dLdf.set_shape(inputs.shape[:-1] + [len(self.dimensions), len(self.tseq), len(self.KK)] + inputs.shape[-1:])
    diag.set_shape(inputs.shape[:-1] + [len(self.dimensions), self.nmax_diag, 2])
    return diag



class DTMWeightWrapperLayer(tf.keras.layers.Layer):

  def __init__(self, name='dtmweightwrapperlayer', **kwargs):
    super(DTMWeightWrapperLayer, self).__init__(name=name)
    self.dtm_layer = DTMWeightLayer(**kwargs) #DTMWeightLayer(**kwargs)

  def call(self, inputs, weight=None):
    """.

    Args:
      inputs: tensor of shape [..., M]

    Returns:
      outputs: tensor of shape [..., units]
    """
    # print(inputs.shape, self.dtm_layer.grid.shape, inputs.shape + self.dtm_layer.grid.shape[-1])
    X = tf.broadcast_to(self.dtm_layer.grid, inputs.shape + self.dtm_layer.grid.shape[-1])
    # print(X.shape, inputs.shape)
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs=X, weight=inputs)
    outputs = dtmVal
    
    return outputs



class GThetaLayer(tf.keras.layers.Layer):

  def __init__(self, units=10, name='gthetalayer', **kwargs):
    super(GThetaLayer, self).__init__(name=name)
    self.g_layer = tf.keras.layers.Dense(units)

  def call(self, inputs, weight=None):
    """.

    Args:
      inputs: tensor of shape [..., M]

    Returns:
      outputs: tensor of shape [..., units]
    """
    # step 2 compute differential map g_theta
    g_theta = self.g_layer(inputs)
    outputs = g_theta

    return outputs



class TopoFunLayer(tf.keras.layers.Layer):

  def __init__(self, units=10, name='topofunlayer', **kwargs):
    super(TopoFunLayer, self).__init__(name=name)
    self.landscape_layer = PersistenceLandscapeLayer(**kwargs)
    self.g_layer = tf.keras.layers.Dense(units)

  def call(self, inputs, weight=None):
    """.

    Args:
      inputs: tensor of shape [..., M]

    Returns:
      outputs: tensor of shape [..., units]
    """
    # step 1 compute persistence diagram and landscape lambda together
    land = self.landscape_layer(inputs)
    # step 2 compute differential map g_theta: combine dim, tseq, KK axis
    g_theta = self.g_layer(tf.reshape(land, land.shape[:-3] + land.shape[-3]*land.shape[-2]*land.shape[-1]))
    outputs = g_theta
    # outputs = tf.concat((tf.reshape(inputs, inputs.shape[:-2] + inputs.shape[-2] * inputs.shape[-1]), g_theta), -1)

    return outputs



class TopoLayer(tf.keras.layers.Layer):

  def __init__(self, units=10, name='topolayer', **kwargs):
    super(TopoLayer, self).__init__(name=name)
    self.dtm_layer = DTMLayer(**kwargs) #DTMWeightLayer(**kwargs)
    self.diagram_layer = PersistenceDiagramLayer(grid_size=self.dtm_layer.grid_size, **kwargs)
    self.landscape_layer = PersistenceLandscapeLayer(grid_size=self.dtm_layer.grid_size, **kwargs)
    self.g_layer = tf.keras.layers.Dense(units)

  def compute_diagram(self, inputs):
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs)
    # step 1 compute persistence diagram
    diag = self.diagram_layer(dtmVal)

    return diag

  def compute_landscape(self, inputs):
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs)
    # step 1 compute persistence diagram and landscape lambda together
    land = self.landscape_layer(dtmVal)

    return land

  def call(self, inputs, weight=None):
    """.

    Args:
      inputs: tensor of shape [..., M, d]

    Returns:
      outputs: tensor of shape [..., units]
    """
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs, weight)
    # step 1 compute persistence diagram and landscape lambda together
    land = self.landscape_layer(dtmVal)
    # step 2 compute differential map g_theta: combine dim, tseq, KK axis
    g_theta = self.g_layer(tf.reshape(land, land.shape[:-3] + land.shape[-3]*land.shape[-2]*land.shape[-1]))
    outputs = g_theta
    # outputs = tf.concat((tf.reshape(inputs, inputs.shape[:-2] + inputs.shape[-2] * inputs.shape[-1]), g_theta), -1)

    return outputs



class TopoWeightLayer(tf.keras.layers.Layer):

  def __init__(self, units=10, name='topoWlayer', **kwargs):
    super(TopoWeightLayer, self).__init__(name=name)
    self.dtm_layer = DTMWeightLayer(**kwargs) #DTMWeightLayer(**kwargs)
    self.diagram_layer = PersistenceDiagramLayer(grid_size=self.dtm_layer.grid_size, **kwargs)
    self.landscape_layer = PersistenceLandscapeLayer(grid_size=self.dtm_layer.grid_size, **kwargs)
    self.g_layer = tf.keras.layers.Dense(units)

  def compute_diagram(self, inputs):
    X = tf.broadcast_to(self.dtm_layer.grid, inputs.shape + self.dtm_layer.grid.shape[-1])
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs=X, weight=inputs)
    # step 1 compute persistence diagram
    diag = self.diagram_layer(dtmVal)

    return diag

  def compute_landscape(self, inputs):
    X = tf.broadcast_to(self.dtm_layer.grid, inputs.shape + self.dtm_layer.grid.shape[-1])
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs=X, weight=inputs)
    # step 1 compute persistence diagram and landscape lambda together
    land = self.landscape_layer(dtmVal)

    return land

  def call(self, inputs, weight=None):
    """.

    Args:
      inputs: tensor of shape [..., M]

    Returns:
      outputs: tensor of shape [..., units]
    """
    # print(inputs.shape, self.dtm_layer.grid.shape, inputs.shape + self.dtm_layer.grid.shape[-1])
    X = tf.broadcast_to(self.dtm_layer.grid, inputs.shape + self.dtm_layer.grid.shape[-1])
    # print(X.shape, inputs.shape)
    # step 0 compute distance to measure
    dtmVal = self.dtm_layer(inputs=X, weight=inputs)
    # dtmVal = self.dtm_layer(inputs, weight)
    # step 1 compute persistence diagram and landscape lambda together
    land = self.landscape_layer(dtmVal)
    # step 2 compute differential map g_theta: combine dim, tseq, KK axis
    g_theta = self.g_layer(tf.reshape(land, land.shape[:-3] + land.shape[-3]*land.shape[-2]*land.shape[-1]))
    outputs = g_theta
    # outputs = tf.concat((inputs, g_theta), -1)
    
    return outputs



def compute_diagram_dtm(X, m0, lims, by, r, tseq, KK, dimensions, maxscale, nmax_diag, batch_size=16):
  start_time = time.time()
  print ("Computing Diagrams")

  topo_layer = TopoLayer(m0=m0, nmax_diag=nmax_diag, lims=lims, by=by, r=r, tseq=tseq, KK=KK, dimensions=dimensions)
  nX = len(X)
  diag = np.zeros((nX, len(topo_layer.diagram_layer.dimensions), nmax_diag, 2), dtype='float32')

  for iX in range(nX // batch_size):
    inputs = tf.constant(X[(batch_size * iX):(batch_size * (iX+1))], dtype='float32')
    diag[(batch_size * iX):(batch_size * (iX+1))] = np.array(topo_layer.compute_diagram(inputs))
  if ((nX // batch_size) * batch_size < nX):
    inputs = tf.constant(X[((nX // batch_size) * batch_size):nX], dtype='float32')
    diag[((nX // batch_size) * batch_size):nX] = np.array(topo_layer.compute_diagram(inputs))

  diag[diag == np.inf] = maxscale

  print("--- %s seconds ---" % (time.time() - start_time))

  iDiag_zero = np.where(np.amax(diag, axis=(0, 1, 3)) == 0)[0]
  if iDiag_zero.size > 0:
    print('Maximum number of points in a diagram: ', iDiag_zero[0])
  else:
    print('Maximum number of points in a diagram is greater or equal to nmax_diag (which is ', nmax_diag, ').')

  return diag


def compute_diagram_dtmweight(X, m0, lims, by, r, tseq, KK, dimensions, maxscale, nmax_diag, batch_size=16):
  start_time = time.time()
  print ("Computing Diagrams")

  topo_weight_layer = TopoWeightLayer(m0=m0, nmax_diag=nmax_diag, lims=lims, by=by, r=r, tseq=tseq, KK=KK, dimensions=dimensions)
  nX = len(X)
  diag = np.zeros((nX, len(topo_weight_layer.diagram_layer.dimensions), nmax_diag, 2), dtype='float32')
  dim_Xvec = np.prod(X.shape[1:])

  for iX in range(nX // batch_size):
    inputs = tf.constant(X[(batch_size * iX):(batch_size * (iX+1))].reshape(batch_size, dim_Xvec), dtype='float32')
    diag[(batch_size * iX):(batch_size * (iX+1))] = np.array(topo_weight_layer.compute_diagram(inputs))
  if ((nX // batch_size) * batch_size < nX):
    inputs = tf.constant(X[((nX//batch_size) * batch_size):nX].reshape(nX - (nX // batch_size) * batch_size, dim_Xvec), dtype='float32')
    diag[((nX // batch_size) * batch_size):nX] = np.array(topo_weight_layer.compute_diagram(inputs))

  diag[diag == np.inf] = maxscale

  print("--- %s seconds ---" % (time.time() - start_time))

  iDiag_zero = np.where(np.amax(diag, axis=(0, 1, 3)) == 0)[0]
  if iDiag_zero.size > 0:
    print('Maximum number of points in a diagram: ', iDiag_zero[0])
  else:
    print('Maximum number of points in a diagram is greater or equal to nmax_diag (which is ', nmax_diag, ').')

  return diag

def compute_landscape_dtm(X, m0, lims, by, r, tseq, KK, dimensions, batch_size=16):
  start_time = time.time()
  print ("Computing Landscape functions")

  topo_layer = TopoLayer(m0=m0, lims=lims, by=by, r=r, tseq=tseq, KK=KK, dimensions=dimensions)
  nX = len(X)
  land = np.zeros((nX, len(dimensions), len(tseq), len(KK)), dtype='float32')

  for iX in range(nX // batch_size):
    inputs = tf.constant(X[(batch_size * iX):(batch_size * (iX+1))], dtype='float32')
    land[(batch_size * iX):(batch_size * (iX+1))] = topo_layer.compute_landscape(inputs)
  if ((nX // batch_size) * batch_size < nX):
    inputs = tf.constant(X[((nX // batch_size) * batch_size):nX], dtype='float32')
    land[((nX // batch_size) * batch_size):nX] = topo_layer.compute_landscape(inputs)

  print("--- %s seconds ---" % (time.time() - start_time))

  return land


def compute_landscape_dtmweight(X, m0, lims, by, r, tseq, KK, dimensions, batch_size=16):
  start_time = time.time()
  print ("Computing Landscape functions")

  topo_weight_layer = TopoWeightLayer(m0=m0, lims=lims, by=by, r=r, tseq=tseq, KK=KK, dimensions=dimensions)
  nX = len(X)
  land = np.zeros((nX, len(dimensions), len(tseq), len(KK)), dtype='float32')
  dim_Xvec = np.prod(X.shape[1:])

  for iX in range(nX // batch_size):
    inputs = tf.constant(X[(batch_size * iX):(batch_size * (iX+1))].reshape(batch_size, dim_Xvec), dtype='float32')
    land[(batch_size * iX):(batch_size * (iX+1))] = topo_weight_layer.compute_landscape(inputs)
  if ((nX // batch_size) * batch_size < nX):
    inputs = tf.constant(X[((nX // batch_size) * batch_size):nX].reshape(nX - (nX // batch_size) * batch_size, dim_Xvec), dtype='float32')
    land[((nX // batch_size) * batch_size):nX] = topo_weight_layer.compute_landscape(inputs)

  print("--- %s seconds ---" % (time.time() - start_time))

  return land

def to_tf_dataset(x, y, batch_size=16):
  nY = (len(y) // batch_size) * batch_size
  dataset = tf.data.Dataset.from_tensor_slices((x[:nY], y[:nY]))
  dataset = dataset.batch(batch_size)
  return dataset



class HoferUnit(tf.keras.layers.Layer):
  def __init__(self, nu, name='hofer_unit'):
    self.nu = nu
    super(HoferUnit, self).__init__(name=name)
    
  def build(self, input_shape):
    self.mu0 = self.add_weight(shape=(), initializer=tf.random_uniform_initializer(minval=0, maxval=1), trainable=True)
    self.mu1 = self.add_weight(shape=(), initializer=tf.random_uniform_initializer(minval=-1, maxval=1), trainable=True)
    self.sigma0 = self.add_weight(shape=(), initializer=tf.constant_initializer(1.), trainable=True)
    self.sigma1 = self.add_weight(shape=(), initializer=tf.constant_initializer(1.), trainable=True)
    
  def call(self, inputs):
    """
    Args:
      inputs: tensor of shape (N, n_pairs, 2)
      (N: number of data points
       n_pairs: number of (birth, death) pairs)

    Returns:
      outputs: tensor of shape (N,1)
    """
    condition1 = tf.math.greater(inputs[:,:,1], self.nu)
    condition2 = tf.math.greater(inputs[:,:,1], 0.0)
    safe_op = tf.where(condition2, inputs[:,:,1], tf.zeros_like(inputs[:,:,1])+1)
    s = tf.where(condition1, 
                 # if x1 > nu
                 tf.exp(-tf.square(self.sigma0) * tf.square(inputs[:,:,0] - self.mu0) - tf.square(self.sigma1) * tf.square(inputs[:,:,1] - self.mu1)),
                 tf.where(condition2,
                          # if 0 < x1 <= nu
                          tf.exp(-tf.square(self.sigma0) * tf.square(inputs[:,:,0] - self.mu0) - tf.square(self.sigma1) * tf.square(tf.math.log(tf.math.truediv(safe_op, self.nu)) * self.nu + self.nu - self.mu1)),
                          # if x1 == 0
                          tf.zeros_like(inputs[:,:,0])
                          )
    )
    return tf.expand_dims(tf.math.reduce_sum(s, axis=1), axis=1)

class HoferLayer(tf.keras.layers.Layer):
  def __init__(self, num_units, nu, name='HoferLayer'):
    self.num_units = num_units
    self.nu = nu
    self.vals = []
    for i in range(num_units):
        hu = HoferUnit(self.nu)
        self.vals.append(hu)
    super(HoferLayer, self).__init__(name=name)

  def call(self, inputs):
    """
    Args:
      inputs: tensor of shape (N, n_pairs, 2)
      (N: number of data points
       n_pairs: number of (birth, death) pairs)

    Returns:
      outputs: tensor of shape (N, num_units)
    """
    return tf.concat([x(inputs) for x in self.vals], 1)