# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Code for profile fitting. Currently supports symmetric 2D Gaussian and
Moffat profiles plus constants.
"""

import numpy as np
from scipy.optimize import leastsq
from .core import *
from .window import *

__all__ = (
    'combFit', 'fitMoffat', 'fitGaussian'
)

def combFit(wind, method, sky, height, x, y,
            fwhm, fwhm_min, fwhm_fix, beta, read, gain, thresh):
    """Fits a stellar profile in a :class:Window using either a 2D Gaussian
    or Moffat profile. This is a convenient wrapper of fitMoffat and 
    fitGaussian because one often wants both options.

    Arguments::

        wind      : :class:`Window`
            the Window containing the stellar profile to fit

        method    : string
            fitting method 'g' for Gaussian, 'm' for Moffat

        sky       : float
            initial sky level

        height    : float
            initial peak height

        x         : float
            initial central X value

        y         : float
            initial central Y value

        fwhm      : float
            initial FWHM, unbinned pixels.

        fwhm_min  : float
            minimum FWHM, unbinned pixels.

        fwhm_fix  : float
            fix the FWHM (i.e. don't fit it)

        beta      : float [if method == 'm']
            exponent of Moffat function

        read      : float
            readout noise, RMS ADU

        gain      : float
            gain, electrons per ADU

        thresh    : float
            threshold in terms of RMS for rejection. The RMS is obtained from
            read and gain but scaled by the sqrt(chi**2/d.o.f). Typical value
            = 4

    Returns:: (pars, epars, extras)

    where::

       pars    : tuple
          (sky, height, x, y, fwhm, beta), the fitted parameters
          (`beta` == 0 if `method`=='g')

       epars   : tuple
          (esky, eheight, ex, ey, efwhm, ebeta), fitted standard errors.
          `ebeta` == -1 if `method`=='g'; `efwhm` == -1 if the FWHM was fixed
          or it hit the minimum value. 

       extras : tuple 
          (fit,x,y,sigma,chisq,nok,nrej,npar,message) -- `fit` is a Window
          containing the best fit; `x` and `x` are the X and Y coordinates of
          the pixels, sigma are the final uncertainties used for each pixel,
          any negative were rejected; `chisq` is the chi**2 of the fit; `nok`
          is the number of points fitted; `nrej` is the number rejected;
          `npar` is the number of parameters fitted; `message` summarises the
          fit values. `x`, `y` and `sigma` are all 2D numpy arrays matching
          the dimensions of the data.

    Raises a HipercamError if the leastsq fails.

    """

    if method == 'g':
        # gaussian fit
        (sky, height, x, y, fwhm), \
            (esky, eheight, ex, ey, efwhm), \
            (fit, X, Y, sigma, chisq, nok, nrej, npar) = fitGaussian(
                wind, sky, height, x, y, fwhm, fwhm_min, fwhm_fix,
                read, gain, thresh
            )

    elif method == 'm':
        # moffat fit
        (sky, height, x, y, fwhm, beta), \
            (esky, eheight, ex, ey, efwhm, ebeta), \
            (fit, X, Y, sigma, chisq, nok, nrej, npar) = fitMoffat(
                wind, sky, height, x, y, fwhm, fwhm_min, fwhm_fix,
                beta, read, gain, thresh
            )

    else:
        raise NotImplementedError(
            '{:s} fitting method not implemented'.format(method)
        )

    if method == 'g':
        message = (
            'x,y = {:.1f}({:.1f}),{:.1f}({:.1f}),'
            ' FWHM = {:.2f}({:.2f}), peak = {:.1f}({:.1f}),'
            ' sky = {:.1f}({:.1f}), chi**2 = {:.1f}, nok = {:d}, nrej = {:d}'
        ).format(x,ex,y,ey,fwhm,efwhm,height,eheight,sky,esky,chisq,nok,nrej)
        beta, ebeta = 0., -1.
    elif method == 'm':
        message = (
            'x,y = {:.1f}({:.1f}),{:.1f}({:.1f}),'
            ' FWHM = {:.2f}({:.2f}), peak = {:.1f}({:.1f}),'
            ' sky = {:.1f}({:.1f}), beta = {:.2f}({:.2f}), chi**2 = {:.1f},'
            ' nok = {:d}, nrej = {:d}'
        ).format(x,ex,y,ey,fwhm,efwhm,height,eheight,sky,esky,beta,ebeta,chisq,nok,nrej)

    return (
        (sky, height, x, y, fwhm, beta),
        (esky, eheight, ex, ey, efwhm, ebeta),
        (fit, X, Y, sigma, chisq, nok, nrej, npar, message)
    )

##########################################
#
# 2D Moffat + constant section
#
##########################################

def fitMoffat(wind, sky, height, xcen, ycen, fwhm, fwhm_min, fwhm_fix,
              beta, read, gain, thresh):
    """Fits the profile of one target in a Window with a symmetric 2D Moffat
    profile plus a constant "c + h/(1+alpha**2)**beta" where r is the distance
    from the centre of the aperture. The constant alpha is determined by the
    parameters `fwhm` and `beta`. The routine returns the fitted parameters,
    the covariances and a few extras including the best fit itself. The FWHM
    can be constrained to lie above a lower limit which can be useful when
    data are heavily binned. If when `fwhm_fix` == False, the first fit with a
    free FWHM fails, the routine will try again with the fwhm held fixed at
    its input value `fwhm`.

    Arguments::

        wind     : Window
            the Window with the data to be fitted. Ideally should contain
            only one target, so chopping down to a small region around
            the target of interest is usually a good idea.

        sky      : float
            initial value of the (assumed constant) sky background (counts
            per pixel)

        height   : float
            initial peak height of profile (counts)

        xcen     : float
            initial X value at centre of profile (unbinned absolute
            coordinates)

        ycen     : float
            initial Y value at centre of profile (unbinned absolute
            coordinates)

        fwhm     : float
            initial FWHM (unbinned pixels).

        fwhm_min : float
            minimum value to allow FWHM to go to. Useful for heavily binned
            data especially where all signal might be in a single pixel to
            prevent going to silly values. Routine first fits with a free
            FWHM. If it goes below this value it tries again, setting to
            this value. (unbinned pixels)

        fwhm_fix : bool
            fix the FWHM at the value `fwhm` during fits. Should be a bit
            faster and more robust.

        read     : float / array
            readout noise, from which weights are generated. If an
            array it must match the dimensions of the Window. (RMS counts)

        gain     : float / array
            gain, from which weights are generated. If an array it
            must match the dimensions of the Window (e- per count)

    Returns:: tuple of tuples

        (pars, sigs, extras) where::

           pars   : tuple
                (sky, height, xcen, yce, fwhm, beta), the fitted parameters.
                fwhm = fwhm_min if initial fit returns an fwhm < fwhm_min,
                or == initial fwhm if fwhm_fix == True.

           sigs   : tuple
                (skye, heighte, xcene, ycene, fwhme, betae), standard errors
                on the fit parameters. If fwhm defaults to `fwhm_min` or
                `fwhm_fix` == True, then `fwhme` will come back as -1.

           extras : tuple
                (fit, x, y, sigma, chisq, nok, nrej, npar) where: `fit` is a
                :class:Window containing the best fit; `x` and `y` are the x
                and y positions of all pixels (2D numpy arrays); `sigma` is
                the final set of RMS uncertainties on each pixel (2D numpy
                array); `chisq` is the raw chi**2; `nok` is the number of
                points fitted; `nrej` is the number rejected; `npar` is the
                number of parameters fitted (5 or 6).

    The program re-scales the uncertainties on the fit parameters by
    sqrt(chi**2/ndof) where ndof is the number of degrees of freedom = number
    of points - 5 or 6, depending on the fit. This allows for poor values
    of `read` and `gain` to a certain extent, which happen especially if a
    sky background has been removed at the start. The value of `sigma` on any
    rejected pixel is < 0.

    Raises a HipercamError if the leastsq fails.

    """

    # construct function objects of both types from the first because during
    # rejection, we assume both exist. sigma arrays are constructed here all > 0
    mfit1 = Mfit1(wind, read, gain)
    dmfit1 = Dmfit1(mfit1)
    mfit2 = Mfit2(wind, read, gain, fwhm)
    dmfit2 = Dmfit2(mfit2)

    while True:
        # Rejection loop. There is a break statement at the end of the loop
        # if no pixels have been rejected.

        # Two pass strategy: fit with a free FWHM, and if it is
        # below fwhm_min, re-fit with the fwhm set = fwhm_min

        if fwhm_fix:
            # FWHM held fixed
            mfit2.fwhm = fwhm
            dmfit2.fwhm = fwhm
            param = (sky, height, xcen, ycen, beta)

            # carry out fit
            soln, covar, info, mesg, ier = leastsq(
                mfit2, param, Dfun=dmfit2, col_deriv=True,
                full_output=True
            )
            if ier < 1 or ier > 4:
                raise HipercamError(mesg)

            # process results
            fit = Window(wind.winhead, mfit2.model(soln))
            skyf, heightf, xf, yf, betaf = soln
            skyfe, heightfe, xfe, yfe, betafe = np.sqrt(np.diag(covar))
            fwhmf, fwhmfe = fwhm, -1

        else:
            # FWHM free to vary
            param = (sky, height, xcen, ycen, fwhm, beta)

            # carry out fit
            soln, covar, info, mesg, ier = leastsq(
                mfit1, param, Dfun=dmfit1, col_deriv=True,
                full_output=True
            )
            if ier < 1 or ier > 4:
                raise HipercamError(mesg)

            # process results
            skyf, heightf, xf, yf, fwhmf, betaf = soln
            if fwhmf > fwhm_min:
                # Free fit is OK
                fit = Window(wind.winhead, mfit1.model(soln))
                skyfe, heightfe, xfe, yfe, \
                    fwhmfe, betafe = np.sqrt(np.diag(covar))

            else:
                # fall back to fixed FWHM
                mfit2.fwhm = fwhm_min
                dmfit2.fwhm = fwhm_min
                param = (sky, height, xcen, ycen, beta)

                # carry out fit
                soln, covar, info, mesg, ier = leastsq(
                    mfit2, param, Dfun=dmfit2, col_deriv=True,
                    full_output=True
                )
                if ier < 1 or ier > 4:
                    raise HipercamError(mesg)

                # process results
                fit = Window(wind.winhead, mfit2.model(soln))
                skyf, heightf, xf, yf, betaf = soln
                skyfe, heightfe, xfe, yfe, betafe = np.sqrt(np.diag(covar))
                fwhmf, fwhmfe = fwhm_min, -1

        # now look for bad outliers
        ok = mfit1.sigma > 0
        resid = (wind.data - fit.data) / mfit1.sigma
        chisq = (resid[ok]**2).sum()
        nok1 = len(resid[ok])
        sfac = np.sqrt(chisq/(nok1-len(soln)))

        # reject any above the defined threshold
        mfit1.sigma[ok & (np.abs(resid)> sfac*thresh)] *= -1

        # check whether any have been rejected
        ok = mfit1.sigma > 0
        nok = len(mfit1.sigma[ok])
        if nok < nok1:
            # some more pixels have been rejected
            mfit2.sigma = mfit1.sigma
            dmfit1.sigma = mfit1.sigma
            dmfit2.sigma = mfit1.sigma
        else:
            # no more pixels have been rejected.  calculate how many have
            # been, re-scale the uncertainties to reflect the actual chi**2
            nrej = mfit1.sigma.size - nok
            skyfe *= sfac
            heightfe *= sfac
            xfe *= sfac
            yfe *= sfac
            if fwhmfe > 0:
                fwhmfe *= sfac
            betafe *= sfac
            break

    # OK we are done.
    return (
        (skyf,heightf,xf,yf,fwhmf,betaf),
        (skyfe,heightfe,xfe,yfe,fwhmfe,betafe),
        (fit,mfit1.xy[0],mfit1.xy[1],mfit1.sigma,chisq,nok,nrej,len(soln))
    )

def moffat(xy, sky, height, xcen, ycen, fwhm, beta):
    """
    Returns a 2D numpy array corresponding to the ordinate grids in xy
    set to a Moffat profile plus a constant. Defined by
    sky + height/(1+alpha*r**2)**beta where r is the distance from the
    centre and alpha is set to give the desired FWHM given the exponent
    beta. As beta becomes large, this tends to a Gaussian shape but has
    more extended wings at low beta.

    Arguments::

      xy    : 3D numpy array
         dimensions (2,NY,NX). x,y = xy sets x and y to the X and Y
         ordinates of a 2D grid setting the output of the routine.

      sky    : float
         sky background

      height : float
         height of central peak

      xcen   : float
         X-ordinate of centre

      ycen   : float
         Y-ordinate of centre

      fwhm   : float
         FWHM of the profile

      beta   : float
         Moffat exponent

    Returns:: 2D numpy array containg the Moffat profile plus constant evaluated
    on the ordinate grids in xy.

    """
    x,y = xy
    rsq = (x-xcen)**2+(y-ycen)**2
    alpha = 4*(2**(1./max(0.01,beta))-1)/fwhm**2
    return height/(1+alpha*rsq)**max(0.01,beta) + sky

def dmoffat(xy, sky, height, xcen, ycen, fwhm, beta, skip_dfwhm=False):
    """Returns a list of 2D numpy arrays corresponding to the ordinate grids in xy
    set to the partial derivatives of a Moffat profile plus a
    constant. Defined by sky + height/(1+alpha*r**2)**beta where r is the
    distance from the centre and alpha is set to give the desired FWHM given
    the exponent beta. As beta becomes large, this tends to a Gaussian shape
    but has more extended wings at low beta. The partial derivatives are in
    the order of the parameters.

    Arguments::

      xy    : 3D numpy array
         dimensions (2,NY,NX). x,y = xy sets x and y to the X and Y
         ordinates of a 2D grid setting the output of the routine.

      sky    : float
         sky background

      height : float
         height of central peak

      xcen   : float
         X-ordinate of centre

      ycen   : float
         Y-ordinate of centre

      fwhm   : float
         FWHM of the profile

      beta   : float
         Moffat exponent

      skip_fwhm : bool
         skips computation of derivative wrt FWHM and returns onby 5 derivs 

    Returns:: a list of six 2D numpy arrays containing the partial derivatives
    of a Moffat profile plus constant evaluated on the ordinate grids in xy.

    """
    x,y = xy
    blim = max(0.01, beta)
    alpha = 4*(2**(1/blim)-1)/fwhm**2

    # intermediate time savers (but each the same dimension as x and y)
    xoff = x-xcen
    yoff = y-ycen
    rsq = xoff**2 + yoff**2

    denom = 1+alpha*rsq
    save1 = height/denom**(blim+1)
    save2 = save1*rsq

    # derivatives. beta is a bit complicated because it appears directly
    # through the exponent but also indirectly through alpha
    d_sky = np.ones_like(x)
    d_height = 1/denom**blim
    d_xcen = (2*alpha*blim)*xoff*save1
    d_ycen = (2*alpha*blim)*yoff*save1
    if skip_dfwhm:
        d_beta = -np.log(denom)*height*d_height + (4.*np.log(2)*2**(1/blim)/blim/fwhm**2)*save2
        return [d_sky, d_height, d_xcen, d_ycen, d_beta]
    else:
        d_fwhm = (2*alpha*blim/fwhm)*save2
        d_beta = -np.log(denom)*height*d_height + (4.*np.log(2)*2**(1/blim)/blim/fwhm**2)*save2
        return [d_sky, d_height, d_xcen, d_ycen, d_fwhm, d_beta]

class Mfit1:
    """
    Function object to pass to leastsq for Moffat + constant
    background model with free FWHM.
    """

    def __init__(self, wind, read, gain):
        """
        Arguments::

          wind  : Window
             the Window containing data to fit

          read  : float / array
             readout noise in RMS counts. Can be a 2D array if dimensions
             same as the data in wind

          gain  : float / array
             gain in electrons / count. Can be a 2D array if dimensions
             same as the data in wind
        """
        self.sigma = np.sqrt(read**2+np.maximum(0,wind.data)/gain)
        x = wind.x(np.arange(wind.nx))
        y = wind.y(np.arange(wind.ny))
        self.xy = np.meshgrid(x, y)
        self.data = wind.data

    def __call__(self, param):
        """
        Returns 1D array of normalised residuals. See the model
        method for a description of the argument 'param'
        """
        mod = self.model(param)
        diff = (self.data-mod)/self.sigma
        ok = self.sigma > 0
        return diff[ok].ravel()

    def model(self, param):
        """
        Returns Window with model given a parameter vector.

        Argument::

           param : 1D array
              unpacks to (sky, height, xcen, ycen, fwhm, beta) where:
              'sky' is the background per pixel; 'height' is the central
              height of the Moffat function; 'xcen' and 'ycen' are the ordinates
              of its centre in unbinned CCD pixels with (1,1) at the left
              corner of the physical imagine area; 'fwhm' is the FWHM in unbinned
              pixels; 'beta' is the Moffat exponent.
        """
        sky, height, xcen, ycen, fwhm, beta = param
        return moffat(self.xy, sky, height, xcen, ycen, fwhm, beta)

class Dmfit1:
    """
    Function object to pass to leastsq to calculate the Jacobian equivalent
    to Mfit1
    """

    def __init__(self, mfit1):
        """
        Arguments::

          mfit1 : Mfit1
             the Mfit1 object passed as 'func' to leastsq
        """
        self.sigma = mfit1.sigma
        self.xy = mfit1.xy

    def __call__(self, param):
        """
        Returns list of 1D arrays of the partial derivatives of
        the normalised residuals with respect to the variable
        parameters.
        """
        sky, height, xcen, ycen, fwhm, beta = param
        derivs = dmoffat(self.xy, sky, height, xcen, ycen, fwhm, beta)
        ok = self.sigma > 0
        return [(-deriv[ok]/self.sigma[ok]).ravel() for deriv in derivs]

class Mfit2:
    """
    Function object to pass to leastsq for Moffat + constant
    background model with fixed FWHM
    """

    def __init__(self, wind, read, gain, fwhm):
        """
        Arguments:

          wind  : Window
             the Window containing data to fit

          read  : float / array
             readout noise in RMS counts. Can be a 2D array if dimensions
             same as the data in wind

          gain  : float / array
             gain in electrons / count. Can be a 2D array if dimensions
             same as the data in wind

          fwhm  : float
             the fixed FWHM to use
        """
        self.sigma = np.sqrt(read**2+np.maximum(0,wind.data)/gain)
        x = wind.x(np.arange(wind.nx))
        y = wind.y(np.arange(wind.ny))
        self.xy = np.meshgrid(x, y)
        self.data = wind.data
        self.fwhm = fwhm

    def __call__(self, param):
        """
        Returns 1D array of normalised residuals
        """
        mod = self.model(param)
        diff = (self.data-mod)/self.sigma
        ok = self.sigma > 0
        return diff[ok].ravel()

    def model(self, param):
        """
        Returns Window with model given a parameter vector.

        Argument::

           param : 1D array
              unpacks to (sky, height, xcen, ycen, beta) where:
              'sky' is the background per pixel; 'height' is the central
              height of the Moffat function; 'xcen' and 'ycen' are the ordinates
              of its centre in unbinned CCD pixels with (1,1) at the left
              corner of the physical imagine area; 'beta' is the Moffat exponent.
        """
        sky, height, xcen, ycen, beta = param
        return moffat(self.xy, sky, height, xcen, ycen, self.fwhm, beta)

class Dmfit2:
    """
    Function object to pass to leastsq to calculate the Jacobian equivalent
    to Mfit2
    """

    def __init__(self, mfit2):
        """
        Arguments::

          mfit2 : Mfit2
             the Mfit2 object passed as 'func' to leastsq
        """
        self.sigma = mfit2.sigma
        self.xy = mfit2.xy
        self.fwhm = mfit2.fwhm

    def __call__(self, param):
        """
        Returns list of 1D arrays of the partial derivatives of
        the normalised residuals with respect to the variable
        parameters.
        """
        sky, height, xcen, ycen, beta = param
        derivs = dmoffat(self.xy, sky, height, xcen, ycen, self.fwhm, beta, True)
        ok = self.sigma > 0
        return [(-deriv[ok]/self.sigma[ok]).ravel() for deriv in derivs]

##########################################
#
# 2D Gaussian + constant section
#
##########################################

def fitGaussian(wind, sky, height, xcen, ycen, fwhm, fwhm_min, fwhm_fix,
                read, gain, thresh):
    """Fits the profile of one target in a Window with a 2D symmetric Gaussian
    profile "c + h*exp(-alpha*r**2)" where r is the distance from the centre
    of the aperture. The constant alpha is fixed by the FWHM. The function
    returns the fitted parameters, covariances and a few extras; see below.
    The FWHM can be constrained to lie above a lower limit which can be useful
    when data are heavily binned. If when fwhm_fix == False, the first fit
    with a free FWHM fails, the routine will try again with the fwhm held
    fixed at its input value `fwhm`.

    Arguments::

        wind     : Window
            the Window with the data to be fitted. Ideally should contain only
            one target, so chopping down to a small region around the target
            of interest is usually a good idea.

        sky      : float
            initial value of the (assumed constant) sky background (counts per
            pixel)

        height   : float
            initial peak height of profile (counts)

        xcen     : float
            initial X value at centre of profile (unbinned absolute
            coordinates)

        ycen     : float
            initial Y value at centre of profile (unbinned absolute
            coordinates)

        fwhm     : float
            initial FWHM (unbinned pixels).

        fwhm_min : float
            minimum value to allow FWHM to go to. Useful for heavily binned
            data especially where all signal might be in a single pixel to
            prevent going to silly values. Routine first fits with a free
            FWHM. If it goes below this value it tries again, setting to this
            value. (unbinned pixels)

        fwhm_fix : bool
            fix the FWHM at the value 'fwhm' during fits. Should be a bit
            faster and more robust.

        read     : float / array
            readout noise, from which weights are generated. If an
            array it must match the dimensions of the Window. (RMS counts)

        gain     : float / array
            gain, from which weights are generated. If an array it
            must match the dimensions of the Window (e- per count)

 
    Returns:: tuple of tuples

        (pars, sigs, extras) where::

           pars   : tuple
                (sky, height, xcen, yce, fwhm). Fitted parameters.
                `fwhm` == `fwhm_min` if fwhm after first fit is < `fwhm_min`,
                or == initial fwhm if `fwhm_fix` == True.

           sigs   : tuple
                (skye, heighte, xcene, ycene, fwhme). Standard errors on
                the fit parameters. If `fwhm` defaults to `fwhm_min` or
                `fwhm_fix` == True, then `fwhme` will come back as -1.

           extras : tuple
                (fit, x, y, sigma) where `fit` is a :class:Window containing
                the best fit, `x` and `y` are the x and y positions of all
                pixels (2D numpy arrays) and `sigma` is the final set of RMS
                uncertainties on each pixels [option for future: some may come
                back < 0 indicating rejection].

    Raises a HipercamError if the leastsq fails.

    """

    # construct function objects of both types from the first because during
    # rejection, we assume both exist. sigma arrays are constructed here all > 0
    gfit1 = Gfit1(wind, read, gain)
    dgfit1 = Dgfit1(gfit1)
    gfit2 = Gfit2(wind, read, gain, fwhm)
    dgfit2 = Dgfit2(gfit2)

    while True:
        # Rejection loop. There is a break statement at the end of the loop
        # if no pixels have been rejected.

        # Two pass strategy: fit with a free FWHM, and if it is
        # below fwhm_min, re-fit with the fwhm set = fwhm_min

        if fwhm_fix:
            # FWHM held fixed
            gfit2.fwhm = fwhm
            dgfit2.fwhm = fwhm
            param = (sky, height, xcen, ycen)

            # carry out fit
            soln, covar, info, mesg, ier = leastsq(
                gfit2, param, Dfun=dgfit2, col_deriv=True,
                full_output=True
            )
            if ier < 1 or ier > 4:
                raise HipercamError(mesg)

            # process results
            fit = Window(wind.winhead, gfit2.model(soln))
            skyf, heightf, xf, yf = soln
            skyfe, heightfe, xfe, yfe = np.sqrt(np.diag(covar))
            fwhmf, fwhmfe = fwhm, -1

        else:
            # FWHM free to vary
            param = (sky, height, xcen, ycen, fwhm)

            # carry out fit
            soln, covar, info, mesg, ier = leastsq(
                gfit1, param, Dfun=dgfit1, col_deriv=True,
                full_output=True
            )
            if ier < 1 or ier > 4:
                raise HipercamError(mesg)

            # process results
            skyf, heightf, xf, yf, fwhmf = soln
            if fwhmf > fwhm_min:
                # Free fit is OK
                skyfe, heightfe, xfe, yfe, fwhmfe = np.sqrt(np.diag(covar))
                fit = Window(wind.winhead, gfit1.model(soln))

            else:
                # fall back to fixed FWHM
                gfit2.fwhm = fwhm_min
                dgfit2.fwhm = fwhm_min
                param = (sky, height, xcen, ycen)

                # carry out fit
                soln, covar, info, mesg, ier = leastsq(
                    gfit2, param, Dfun=dgfit2, col_deriv=True,
                    full_output=True
                )
                if ier < 1 or ier > 4:
                    raise HipercamError(mesg)

                # process results
                fit = Window(wind.winhead, gfit2.model(soln))
                skyf, heightf, xf, yf = soln
                skyfe, heightfe, xfe, yfe = np.sqrt(np.diag(covar))
                fwhmf, fwhmfe = fwhm_min, -1

        # now look for bad outliers
        ok = gfit1.sigma > 0
        resid = (wind.data - fit.data) / gfit1.sigma
        chisq = (resid[ok]**2).sum()
        nok1 = len(resid[ok])
        sfac = np.sqrt(chisq/(nok1-len(soln)))

        # reject any above the defined threshold
        gfit1.sigma[ok & (np.abs(resid)> sfac*thresh)] *= -1

        # check whether any have been rejected
        ok = gfit1.sigma > 0
        nok = len(gfit1.sigma[ok])
        if nok < nok1:
            # some more pixels have been rejected
            gfit2.sigma = gfit1.sigma
            dgfit1.sigma = gfit1.sigma
            dgfit2.sigma = gfit1.sigma
        else:
            # no more pixels have been rejected.  calculate how many have
            # been, re-scale the uncertainties to reflect the actual chi**2
            nrej = gfit1.sigma.size - nok
            skyfe *= sfac
            heightfe *= sfac
            xfe *= sfac
            yfe *= sfac
            if fwhmfe > 0:
                fwhmfe *= sfac
            break

    # OK we are done.
    return (
        (skyf,heightf,xf,yf,fwhmf),
        (skyfe,heightfe,xfe,yfe,fwhmfe),
        (fit,gfit1.xy[0],gfit1.xy[1],gfit1.sigma,chisq,nok,nrej,len(soln))
    )

def gaussian(xy, sky, height, xcen, ycen, fwhm):
    """Returns a 2D numpy array corresponding to the ordinate grids in xy set to a
    symmetric 2D Gaussian plus a constant. Defined by sky +
    height*exp(-alpha*r**2) where r is the distance from the centre and alpha
    is set to give the desired FWHM.

    Arguments::

      xy    : 3D numpy array
         dimensions (2,NY,NX). x,y = xy sets x and y to the X and Y
         ordinates of a 2D grid setting the output of the routine.

      sky    : float
         sky background

      height : float
         height of central peak

      xcen   : float
         X-ordinate of centre

      ycen   : float
         Y-ordinate of centre

      fwhm   : float
         FWHM of the profile

    Returns:: 2D numpy array containing the Gaussian plus constant evaluated
    on the ordinate grids in xy.

    """
    x,y = xy
    rsq = (x-xcen)**2+(y-ycen)**2
    alpha = 4.*np.log(2.)/fwhm**2
    return sky+height*np.exp(-alpha*rsq)

def dgaussian(xy, sky, height, xcen, ycen, fwhm, skip_dfwhm=False):
    """Returns a list of four or five 2D numpy arrays corresponding to the
    ordinate grids in xy set to the partial derivatives of a symmetric 2D
    Gaussian plus a constant. Defined by sky + height*exp(-alpha*r**2) where r
    is the distance from the centre and alpha is set to give the desired FWHM.
    The partial derivatives are in the order of the parameters.

    Arguments::

      xy    : 3D numpy array
         dimensions (2,NY,NX). x,y = xy sets x and y to the X and Y
         ordinates of a 2D grid setting the output of the routine.

      sky    : float
         sky background

      height : float
         height of central peak

      xcen   : float
         X-ordinate of centre

      ycen   : float
         Y-ordinate of centre

      fwhm   : float
         FWHM of the profile

      skip_fwhm : bool
         skips computation of derivative wrt FWHM and returns only 4 derivs 

    Returns:: a list of four or five 2D numpy arrays containing the partial
    derivatives of a symmetric 2D Gaussian plus constant evaluated on the
    ordinate grids in xy. They come in the same order as they appear in
    the function call.

    """
    x,y = xy
    alpha = 4.*np.log(2.)/fwhm**2

    # intermediate time savers (but each the same dimension as x and y)
    xoff = x-xcen
    yoff = y-ycen
    rsq = xoff**2 + yoff**2

    # derivatives
    d_sky = np.ones_like(x)

    d_height = np.exp(-alpha*rsq)

    d_xcen = (2*alpha*height)*d_height*xoff

    d_ycen = (2*alpha*height)*d_height*yoff

    if skip_dfwhm:
        return [d_sky, d_height, d_xcen, d_ycen]
    else:
        d_fwhm = (2*alpha*height/fwhm)*d_height*rsq
        return [d_sky, d_height, d_xcen, d_ycen, d_fwhm]

class Gfit1:
    """
    Function object to pass to leastsq for Gaussian + constant
    background model with free FWHM.
    """

    def __init__(self, wind, read, gain):
        """
        Arguments::

          wind  : Window
             the Window containing data to fit

          read  : float / array
             readout noise in RMS counts. Can be a 2D array if dimensions
             same as the data in wind

          gain  : float / array
             gain in electrons / count. Can be a 2D array if dimensions
             same as the data in wind
        """
        self.sigma = np.sqrt(read**2+np.maximum(0,wind.data)/gain)
        x = wind.x(np.arange(wind.nx))
        y = wind.y(np.arange(wind.ny))
        self.xy = np.meshgrid(x, y)
        self.data = wind.data

    def __call__(self, param):
        """
        Returns 1D array of normalised residuals. See the model
        method for a description of the argument 'param'
        """
        mod = self.model(param)
        diff = (self.data-mod)/self.sigma
        ok = self.sigma > 0
        return diff[ok].ravel()

    def model(self, param):
        """Returns Window with model given a parameter vector.

        Argument::

           param : 1D array
              unpacks to (sky, height, xcen, ycen, fwhm) where: 'sky' is the
              background per pixel; 'height' is the central height of the
              Gaussian; 'xcen' and 'ycen' are the ordinates of its centre in
              unbinned CCD pixels with (1,1) at the left corner of the
              physical imagine area; 'fwhm' is the FWHM in unbinned pixels.

        """
        sky, height, xcen, ycen, fwhm = param
        return gaussian(self.xy, sky, height, xcen, ycen, fwhm)

class Dgfit1:
    """
    Function object to pass to leastsq to calculate the Jacobian equivalent
    to Gfit1
    """

    def __init__(self, gfit1):
        """
        Arguments::

          gfit1 : Gfit1
             the Gfit1 object passed as 'func' to leastsq
        """
        self.sigma = gfit1.sigma
        self.xy = gfit1.xy

    def __call__(self, param):
        """Returns list of 1D arrays of the partial derivatives of the normalised
        residuals with respect to the variable parameters.

        """
        sky, height, xcen, ycen, fwhm = param
        derivs = dgaussian(self.xy, sky, height, xcen, ycen, fwhm)
        ok = self.sigma > 0
        return [(-deriv[ok]/self.sigma[ok]).ravel() for deriv in derivs]

class Gfit2:
    """
    Function object to pass to leastsq for Gaussian + constant
    background model with fixed FWHM.
    """

    def __init__(self, wind, read, gain, fwhm):
        """
        Arguments:

          wind  : Window
             the Window containing data to fit

          read  : float / array
             readout noise in RMS counts. Can be a 2D array if dimensions
             same as the data in wind

          gain  : float / array
             gain in electrons / count. Can be a 2D array if dimensions
             same as the data in wind

          fwhm  : float
             the fixed FWHM to use
        """
        self.sigma = np.sqrt(read**2+np.maximum(0,wind.data)/gain)
        x = wind.x(np.arange(wind.nx))
        y = wind.y(np.arange(wind.ny))
        self.xy = np.meshgrid(x, y)
        self.data = wind.data
        self.fwhm = fwhm

    def __call__(self, param):
        """
        Returns 1D array of normalised residuals
        """
        mod = self.model(param)
        diff = (self.data-mod)/self.sigma
        ok = self.sigma > 0
        return diff[ok].ravel()

    def model(self, param):
        """Returns Window with model given a parameter vector.

        Argument::

           param : 1D array
              unpacks to (sky, height, xcen, ycen) where: 'sky' is the
              background per pixel; 'height' is the central height of the
              Moffat function; 'xcen' and 'ycen' are the ordinates of its
              centre in unbinned CCD pixels with (1,1) at the left corner of
              the physical imagine area.

        """
        sky, height, xcen, ycen = param
        return gaussian(self.xy, sky, height, xcen, ycen, self.fwhm)

class Dgfit2:
    """
    Function object to pass to leastsq to calculate the Jacobian equivalent
    to Gfit2
    """

    def __init__(self, gfit2):
        """
        Arguments::

          gfit2 : Gfit2
             the Gfit2 object passed as 'func' to leastsq
        """
        self.sigma = gfit2.sigma
        self.xy = gfit2.xy
        self.fwhm = gfit2.fwhm

    def __call__(self, param):
        """
        Returns list of 1D arrays of the partial derivatives of
        the normalised residuals with respect to the variable
        parameters.
        """
        sky, height, xcen, ycen = param
        derivs = dgaussian(self.xy, sky, height, xcen, ycen, self.fwhm, True)
        ok = self.sigma > 0
        return [(-deriv[ok]/self.sigma[ok]).ravel() for deriv in derivs]