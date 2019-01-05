# -*- coding: utf-8 -*-

import numpy as np
import numpy.linalg as nl
import time

from pydsge.engine import boehlgorithm_pp
from numba import njit

from .stats import logpdf

class TVF(object):

    def __init__(self, N, dim_x = None, dim_z = None, fx = None, hx = None, model_obj = None):

        ## get stuff directly from the model class if it exists
        if model_obj is not None:
            self._dim_x = len(model_obj.vv)
            self._dim_z = model_obj.ny
            self.fx         = lambda x: model_obj.t_func(x, return_flag = False)
            self.hx         = model_obj.o_func

        else:
            self._dim_x = dim_x
            self._dim_z = dim_z
            self.fx     = fx
            self.hx     = hx

        self.N      = N

        self.R      = np.eye(self._dim_z)
        self.Q      = np.eye(self._dim_x)
        self.P      = np.eye(self._dim_x)

        self.x      = np.zeros(self._dim_x)

    def batch_filter(self, Z, store=False, calc_ll=False, info=False):

        _dim_x, _dim_z, N, P, R, Q, x =     self._dim_x, self._dim_z, self.N, self.P, self.R, self.Q, self.x 

        I1  = np.ones(N)
        I2  = np.eye(N) - np.outer(I1, I1)/N

        if store:
            self.Xs              = np.empty((Z.shape[0], _dim_x, N))
            self.X_priors        = np.empty_like(self.Xs)
            self.X_bars          = np.empty_like(self.Xs)
            self.X_bar_priors    = np.empty_like(self.Xs)

        ll  = 0

        means           = np.empty((Z.shape[0], _dim_x))
        covs            = np.empty((Z.shape[0], _dim_x, _dim_x))

        Y           = np.empty((_dim_z, N))
        X_prior     = np.empty((_dim_x, N))

        mus     = np.random.multivariate_normal(mean = np.zeros(self._dim_z), cov = self.R, size=(len(Z),self.N))
        epss    = np.random.multivariate_normal(mean = np.zeros(self._dim_x), cov = self.Q, size=(len(Z),self.N))
        X       = np.random.multivariate_normal(mean = x, cov = P, size=N).T

        for nz, z in enumerate(Z):

            ## predict
            for i in range(X.shape[1]):
                eps             = epss[nz,i]
                X_prior[:,i]    = self.fx(X[:,i]+eps)

            for i in range(X_prior.shape[1]):
                mu          = mus[nz,i]
                Y[:,i]      = self.hx(X_prior[:,i]) + mu

            ## update
            X_bar   = X_prior @ I2
            Y_bar   = Y @ I2
            ZZ      = np.outer(z, I1) 
            C_yy    = np.cov(Y_bar)
            # X       = X_prior + X_bar @ Y_bar.T @ nl.inv((N-1)*(C_yy +R)) @ ( ZZ - Y )
            X       = X_prior + X_bar @ Y_bar.T @ nl.inv(C_yy*(N-1)) @ ( ZZ - Y )

            ## storage
            means[nz,:]   = np.mean(X, axis=1)
            covs[nz,:,:]  = np.cov(X)

            if store:
                self.X_bar_priors[nz,:,:]    = X_bar
                self.X_bars[nz,:,:]          = X @ I2
                self.X_priors[nz,:,:]        = X_prior
                self.Xs[nz,:,:]              = X

            if calc_ll:
                z_mean  = np.mean(Y, axis=1)
                ll      += logpdf(x = z, mean = z_mean, cov = C_yy)

        self.ll     = ll

        return means, covs, ll

    """
    def rts_smoother(self, means, covs):

        SE      = self.Xs[-1]

        for i in reversed(range(means.shape[0] - 1)):

            # J   = self.X_bars[i] @ nl.pinv(self.X_bar_priors[i+1])
            J   = self.X_bars[i] @ self.X_bar_priors[i+1].T @ nl.pinv( self.X_bar_priors[i+1] @ self.X_bar_priors[i+1].T )
            SE  = self.Xs[i] + J @ (SE - self.X_priors[i+1])

            means[i]    = np.mean(SE, axis=1)
            covs[i]     = np.cov(SE)

        return means, covs
    """

    def rts_smoother(self, means, covs):

        SE      = self.Xs[-1]
        ASE     = SE

        # mtd     = 'BFGS'   
        mtd     = 'L-BFGS-B' 
        
        import scipy.optimize as so

        for i in reversed(range(means.shape[0] - 1)):

            # J   = self.X_bars[i] @ nl.pinv(self.X_bar_priors[i+1])
            J   = self.X_bars[i] @ self.X_bar_priors[i+1].T @ nl.pinv( self.X_bar_priors[i+1] @ self.X_bar_priors[i+1].T )
            SE  = self.Xs[i] + J @ (ASE - self.X_priors[i+1])

            def target(x_eps):

                x   = x_eps[:self._dim_x]
                eps = x_eps[self._dim_x:]

                l0  = logpdf(x, mean = np.mean(SE, axis=1), cov = np.cov(SE))
                l1  = logpdf(self.fx(x), mean = np.mean(ASE, axis=1), cov = np.cov(ASE))
                l2  = logpdf(eps, mean = np.zeros(self._dim_z), cov = self.R)

                return -l0 -l1 -l2

            res     = so.minimize(target, np.hstack((np.mean(SE, axis=1), np.zeros(self._dim_z))), method = mtd)
            x       = res['x'][:self._dim_x]

            I1      = np.ones(self.N)
            ASE     = SE + np.outer(x - np.mean(SE), I1)

            means[i]    = np.mean(ASE, axis=1)
            covs[i]     = np.cov(ASE)

        return means, covs
    # """
