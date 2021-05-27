import sys
import os

import numpy as np
from astropy.time import Time
from astropy.io import fits
from astropy import wcs
from astropy.coordinates import SkyCoord, Angle
import astropy.units as u

import hipercam as hcam
from hipercam import cline, utils, spooler, defect, fringe
from hipercam.cline import Cline

__all__ = [
    "joinup",
]

###############################################
#
# joinup -- converts a run into separate images
#
###############################################


def joinup(args=None):
    """``joinup [source] (run first [twait tmax] | flist) trim ([ncol
    nrow]) (ccd) bias dark flat fmap (fpair nhalf rmin rmax) msub
    dtype dmax nmax overwrite compress``

    Converts a run or a list of hcm images into as near as possible
    "standard" FITS files with one image in the primary HDU per file,
    representing a single CCD with all windows merged. The aim above
    all is to have a file that plays nicely with 'ds9'. A file such as
    'run0002.fits' (|hiper|) will end up producing files with names
    like run0002_ccd1_0001.fits, run0002_ccd1_0002.fits, etc and the
    same for any of the other CCDs. They will be written to the
    present working directory. If the windows have gaps, then they
    will be filled with zeroes.

    Parameters:

        source : string [hidden]
           Data source, five options:

             |  'hs' : HiPERCAM server
             |  'hl' : local HiPERCAM FITS file
             |  'us' : ULTRACAM server
             |  'ul' : local ULTRACAM .xml/.dat files
             |  'hf' : list of HiPERCAM hcm FITS-format files

           'hf' is used to look at sets of frames generated by 'grab'
           or converted from foreign data formats. The standard
           start-off default for ``source`` can be set using the
           environment variable HIPERCAM_DEFAULT_SOURCE. e.g. in bash
           :code:`export HIPERCAM_DEFAULT_SOURCE="us"` would ensure it
           always started with the ULTRACAM server by default. If
           unspecified, it defaults to 'hl'.

        run : string [if source ends 's' or 'l']
           run number to access, e.g. 'run034'

        first : int [if source ends 's' or 'l']
           exposure number to start from. 1 = first frame. For data
           from the |hiper| server, a negative number tries to get a frame not
           quite at the end.  i.e. -10 will try to get 10 from the last
           frame. This is mainly to sidestep a difficult bug with the
           acquisition system.

        last : int [if source ends 's' or 'l']
           Last frame to access, 0 for the lot

        twait : float [if source ends 's' or 'l'; hidden]
           time to wait between attempts to find a new exposure, seconds.

        tmax : float [if source ends 's' or 'l'; hidden]
           maximum time to wait between attempts to find a new exposure,
           seconds.

        flist : string [if source ends 'f']
           name of file list

        trim : bool [if source starts with 'u']
           True to trim columns and/or rows off the edges of windows nearest
           the readout which can sometimes contain bad data.

        ncol : int [if trim, hidden]
           Number of columns to remove (on left of left-hand window, and right
           of right-hand windows)

        nrow : int [if trim, hidden]
           Number of rows to remove (bottom of windows)

        ccd : string
           CCD(s) to plot, '0' for all, '1 3' to plot '1' and '3' only, etc.

        bias : str
           Name of bias frame to subtract, 'none' to ignore.

        dark : str
           Name of dark frame to correct for dark counts. 'none' to
           ignore.

        flat : str
           Name of flat field to divide by, 'none' to ignore. Should normally
           only be used in conjunction with a bias, although it does allow you
           to specify a flat even if you haven't specified a bias.

        fmap : str
           Fringe map to remove fringes, 'none' to ignore.

        fpair : str [if fmap is not == 'none']
           File of peak/trough pairs for fringe amplitude measurement.

        nhalf : int [if fmap is not == 'none', hidden]
           Half-size of regions around each point for measuring intensity
           differences from peak/trough pairs.

        rmin : float [if fmap is not == 'none', hidden]
           Minimum individual ratio for pruning peak/tough ratios prior to
           taking their median.

        rmin : float [if fmap is not == 'none', hidden]
           Maximum individual ratio for pruning peak/trough ratios prior to
           taking their median.

        msub : bool
           subtract the median from each window. If set this happens after any
           bias subtraction etc.

        ndigit : int
           number of digits to be used in the frame counter attached
           to the output file names. These are zero-padded so that the
           frames order alphabetically. Thus 'run0002_ccd1_0001.fits',
           'run0002_ccd1_0002.fits', 'run0002_ccd1_0003.fits' ... for
           instance.

        dtype : str
           output data type. 'unit16', 'float32', 'float64'. The first
           of these (2-byte unsigned) is only probably a good idea if
           no bias, flat field or median subtraction has been applied
           because it involves rounding and it will fail if any data
           are out of the range 0 to 65535. 32-bit (4 byte) floats
           should be OK for most purposes, but require twice the space
           of uint16.

        dmax : float
           Maximum amount of data in GB to write out. A safety device
           to avoid disaster in case this script was applied to highly
           windowed data where you can end up expanding the total
           amount of data by a large factor.

        nmax : int
           Maximum number of frames. A similar safety device to dmax
           to avoid inadvertent application of this script to a
           million+ frame run. File systems tend not to behave well
           with vast numbers of files.

        overwrite : bool
           overwrite any pre-existing files.

        compress : str
           allows data to be compressed with FITS's internal lossless
           compression mechanisms. The file will still end as ".fits"
           but has a different internal format; 'ds9' copes seamlessly
           with all of them. The options are: 'none', 'rice', 'gzip1',
           'gzip2'. 'rice' gave about a factor of 2 compression in a
           short test I ran, and was as fast as gzip2, but it may
           depend upon the nature of the data. 'none' is fastest. See
           astropy.io.fits for further documentation.

    .. Note::

       Be careful of running this on highly windowed data since it
       could end up expanding the total amount of "data" hugely.  It's
       really aimed at full frame runs above all. The "dmax" and
       "nmax" parameters are aimed at heading off disaster.

       This routine will fail if windows have been binned but are out
       of step (not "in sync") with each other because there is no way
       to register such data within a single image.

       The routine only creates a window big enough to contain all the
       windows. Thus it might end up representing a sub-array of the
       CCD as opposed to all of it. The location can be determined
       from the 'LLX' and 'LLY' parameters that are written to the
       header. These represent the location of the lowest and leftmost
       unbinned pixel that is contained within the data array. The
       bottom-left pixel of the CCD is considered to be (1,1), so full
       frame images have LLX=LLY=1.

       A HipercamError will be raised if an attempt is made to write out
       data outside the range 0 to 65535 into unit16 format and nothing
       will be written

    """

    command, args = utils.script_args(args)

    # get the inputs
    with Cline("HIPERCAM_ENV", ".hipercam", command, args) as cl:

        # register parameters
        cl.register("source", Cline.GLOBAL, Cline.HIDE)
        cl.register("run", Cline.GLOBAL, Cline.PROMPT)
        cl.register("first", Cline.LOCAL, Cline.PROMPT)
        cl.register("last", Cline.LOCAL, Cline.PROMPT)
        cl.register("trim", Cline.GLOBAL, Cline.PROMPT)
        cl.register("ncol", Cline.GLOBAL, Cline.HIDE)
        cl.register("nrow", Cline.GLOBAL, Cline.HIDE)
        cl.register("twait", Cline.LOCAL, Cline.HIDE)
        cl.register("tmax", Cline.LOCAL, Cline.HIDE)
        cl.register("flist", Cline.LOCAL, Cline.PROMPT)
        cl.register("ccd", Cline.LOCAL, Cline.PROMPT)
        cl.register("bias", Cline.GLOBAL, Cline.PROMPT)
        cl.register("dark", Cline.GLOBAL, Cline.PROMPT)
        cl.register("flat", Cline.GLOBAL, Cline.PROMPT)
        cl.register("fmap", Cline.GLOBAL, Cline.PROMPT)
        cl.register("fpair", Cline.GLOBAL, Cline.PROMPT)
        cl.register("nhalf", Cline.GLOBAL, Cline.HIDE)
        cl.register("rmin", Cline.GLOBAL, Cline.HIDE)
        cl.register("rmax", Cline.GLOBAL, Cline.HIDE)
        cl.register("msub", Cline.GLOBAL, Cline.PROMPT)
        cl.register("ndigit", Cline.LOCAL, Cline.PROMPT)
        cl.register("dtype", Cline.LOCAL, Cline.PROMPT)
        cl.register("dmax", Cline.LOCAL, Cline.PROMPT)
        cl.register("nmax", Cline.LOCAL, Cline.PROMPT)
        cl.register("overwrite", Cline.LOCAL, Cline.PROMPT)
        cl.register("compress", Cline.LOCAL, Cline.PROMPT)

        # get inputs
        default_source = os.environ.get('HIPERCAM_DEFAULT_SOURCE','hl')
        source = cl.get_value(
            "source",
            "data source [hs, hl, us, ul, hf]",
            default_source,
            lvals=("hs", "hl", "us", "ul", "hf"),
        )

        # set some flags
        server_or_local = source.endswith("s") or source.endswith("l")

        if server_or_local:
            resource = cl.get_value("run", "run name", "run005")
            if source == "hs":
                first = cl.get_value("first", "first frame to process", 1)
            else:
                first = cl.get_value("first", "first frame to process", 1, 1)

            last = cl.get_value("last", "last frame to grab", 0)
            if last and last < first:
                sys.stderr.write("last must be >= first or 0")
                sys.exit(1)

            twait = cl.get_value(
                "twait", "time to wait for a new frame [secs]", 1.0, 0.0
            )
            tmax = cl.get_value(
                "tmax", "maximum time to wait for a new frame [secs]", 10.0, 0.0
            )

        else:
            resource = cl.get_value(
                "flist", "file list", cline.Fname("files.lis", hcam.LIST)
            )
            first = 1

        trim = cl.get_value("trim", "do you want to trim edges of windows?", True)
        if trim:
            ncol = cl.get_value("ncol", "number of columns to trim from windows", 0)
            nrow = cl.get_value("nrow", "number of rows to trim from windows", 0)

        # define the panel grid. first get the labels and maximum dimensions
        ccdinf = spooler.get_ccd_pars(source, resource)

        if len(ccdinf) > 1:
            ccd = cl.get_value("ccd", "CCD(s) to plot [0 for all]", "0")
            if ccd == "0":
                ccds = list(ccdinf.keys())
            else:
                ccds = ccd.split()
                check = set(ccdinf.keys())
                if not set(ccds) <= check:
                    raise hcam.HipercamError("At least one invalid CCD label supplied")

        else:
            ccds = list(ccdinf.keys())

        # bias frame (if any)
        bias = cl.get_value(
            "bias",
            "bias frame ['none' to ignore]",
            cline.Fname("bias", hcam.HCAM),
            ignore="none",
        )
        if bias is not None:
            # read the bias frame
            bias = hcam.MCCD.read(bias)
            fprompt = "flat frame ['none' to ignore]"
        else:
            fprompt = "flat frame ['none' is normal choice with no bias]"

        # dark
        dark = cl.get_value(
            "dark", "dark frame ['none' to ignore]",
            cline.Fname("dark", hcam.HCAM), ignore="none"
        )
        if dark is not None:
            # read the dark frame
            dark = hcam.MCCD.read(dark)

        # flat (if any)
        flat = cl.get_value(
            "flat", fprompt, cline.Fname("flat", hcam.HCAM), ignore="none"
        )
        if flat is not None:
            # read the flat frame
            flat = hcam.MCCD.read(flat)

        # fringe file (if any)
        fmap = cl.get_value(
            "fmap",
            "fringe map ['none' to ignore]",
            cline.Fname("fmap", hcam.HCAM),
            ignore="none",
        )
        if fmap is not None:
            # read the fringe map
            fmap = hcam.MCCD.read(fmap)
            fpair = cl.get_value(
                "fpair", "fringe pair file",
                cline.Fname("fpair", hcam.FRNG)
            )
            fpair = fringe.MccdFringePair.read(fpair)

            nhalf = cl.get_value(
                "nhalf", "half-size of fringe measurement regions",
                2, 0
            )
            rmin = cl.get_value(
                "rmin", "minimum fringe pair ratio", -0.2
            )
            rmax = cl.get_value(
                "rmax", "maximum fringe pair ratio", 1.0
            )

        msub = cl.get_value("msub", "subtract median from each window?", True)
        ndigit = cl.get_value(
            "ndigit", "number of digits to use for frame numbers in output names",
            4, 1
        )
        dtype = cl.get_value(
            "dtype",
            "output data type", 'float32',
            lvals=['uint16','float32','float64']
        )
        dmax = cl.get_value(
            "dmax",
            "maximum allowable amount of data to write out [GB]", 10., 0.
        )
        nmax = cl.get_value(
            "nmax",
            "maximum allowable number of frames to write out", 10000, 0
        )
        overwrite = cl.get_value(
            "overwrite",
            "overwrite pre-existing files on output?",
            False
        )
        compress = cl.get_value(
            "compress",
            "internal HDU compression to apply", 'none',
            lvals=[
                'none', 'rice', 'gzip1', 'gzip2'
            ]
        )

    ################################################################
    #
    # all the inputs have now been obtained. Get on with doing stuff

    ctrans = {'rice' : 'RICE_1', 'gzip1' : 'GZIP_1', 'gzip2' : 'GZIP_2'}

    total_time = 0  # time waiting for new frame

    # plot images
    dtotal = 0
    GB = 1024**3
    nfile = 0
    with spooler.data_source(source, resource, first) as spool:

        # 'spool' is an iterable source of MCCDs
        nframe = first
        for mccd in spool:

            if server_or_local:
                # Handle the waiting game ...
                give_up, try_again, total_time = spooler.hang_about(
                    mccd, twait, tmax, total_time
                )

                if give_up:
                    print("joinup stopped")
                    break
                elif try_again:
                    continue

            # Trim the frames: ULTRACAM windowed data has bad columns
            # and rows on the sides of windows closest to the readout
            # which can badly affect reduction. This option strips
            # them.
            if trim:
                hcam.ccd.trim_ultracam(mccd, ncol, nrow)

            # indicate progress
            tstamp = Time(mccd.head["TIMSTAMP"], format="isot", precision=3)
            nf = mccd.head.get("NFRAME",nframe)
            tok = "ok" if mccd.head.get("GOODTIME", True) else "nok"
            print(f"{nf}, utc= {tstamp.iso} ({tok})")

            if nframe == first:
                if bias is not None:
                    # crop the bias on the first frame only
                    bias = bias.crop(mccd)
                    bexpose = bias.head.get("EXPTIME", 0.0)
                else:
                    bexpose = 0.
                if dark is not None:
                    dark = dark.crop(mccd)
                if flat is not None:
                    # crop the flat on the first frame only
                    flat = flat.crop(mccd)
                if fmap is not None:
                    fmap = fmap.crop(mccd)
                    fpair = fpair.crop(mccd, nhalf)

            # OK here goes
            for nc, cnam in enumerate(ccds):
                ccd = mccd[cnam]

                if ccd.is_data():
                    # this should be data as opposed to a blank frame
                    # between data frames that occur with nskip > 0

                    # subtract the bias
                    if bias is not None:
                        ccd -= bias[cnam]

                    if dark is not None:
                        # subtract dark, CCD by CCD
                        dexpose = dark.head["EXPTIME"]
                        cexpose = ccd.head["EXPTIME"]
                        scale = (cexpose - bexpose) / dexpose
                        ccd -= scale * dark[cnam]

                    # divide out the flat
                    if flat is not None:
                        ccd /= flat[cnam]

                    if fmap is not None:
                        if cnam in fmap and cnam in fpair:
                            fscale = fpair[cnam].scale(
                                ccd, fmap[cnam], nhalf, rmin, rmax
                            )
                            ccd -= fscale*fmap[cnam]

                    if msub:
                        # subtract median from each window
                        for wind in ccd.values():
                            wind -= wind.median()

                    # The CCD is prepared. We need to generate a
                    # single data array for all data. First check that
                    # it is even possible

                    for n, wind in enumerate(ccd.values()):
                        if n == 0:
                            llx = llxmin = wind.llx
                            lly = llymin = wind.lly
                            urxmax = wind.urx
                            urymax = wind.ury
                            xbin = wind.xbin
                            ybin = wind.ybin
                        else:
                            # Track overall dimensions
                            llxmin = min(llxmin, wind.llx)
                            llymin = min(llymin, wind.lly)
                            urxmax = max(urxmax, wind.urx)
                            urymax = max(urymax, wind.ury)
                            if xbin != wind.xbin or ybin != wind.ybin:
                                raise hcam.HipercamError('Found windows with clashing binning factors')
                            if (wind.llx - llx) % xbin != 0 or (wind.lly - lly) % ybin != 0:
                                raise hcam.HipercamError('Found windows which are out of sync with each other')

                    # create huge array of nothing
                    ny = (urymax-llymin+1) // ybin
                    nx = (urxmax-llxmin+1) // xbin
                    data = np.zeros((ny,nx))

                    # fill it with data
                    for n, wind in enumerate(ccd.values()):
                        xstart = (wind.llx - llxmin) // xbin
                        ystart = (wind.lly - llymin) // ybin
                        data[ystart:ystart+wind.ny,xstart:xstart+wind.nx] = wind.data

                    if dtype == 'uint16' and (data.min() < 0 or data.max() > 65535):
                        raise hcam.HipercamError(
                            f'CCD {cnam}, frame {nf}, data range {data.min()} to {data.max()}, is incompatible with uint16'
                        )

                    # Header
                    phead = mccd.head.copy()

                    # Add some extra stuff
                    phead["CCDLABEL"] = (cnam, "CCD label")
                    phead["NFRAME"] = (nf, "Frame number")
                    phead["LLX"] = (llxmin, "X of lower-left unbinned pixel (starts at 1)")
                    phead["LLY"] = (llymin, "Y of lower-left unbinned pixel (starts at 1)")
                    phead["NXTOT"] = (ccd.nxtot, "Total unbinned X dimension")
                    phead["NYTOT"] = (ccd.nytot, "Total unbinned Y dimension")
                    phead.add_comment('Written by HiPERCAM script "joinup"')

                    if dtype == 'uint16':
                        data = data.astype(np.uint16)
                        dtotal += 2*nx*ny/GB
                    elif dtype == 'float32':
                        data = data.astype(np.float32)
                        dtotal += 4*nx*ny/GB
                    elif dtype == 'float64':
                        data = data.astype(np.float64)
                        dtotal += 8*nx*ny/GB

                    if dtotal >= dmax:
                        print(f'Reached maximum allowable amount of data = {dmax} GB; stopping.')
                        print(f'Written {nfile} FITS files to disk.')
                        return

                    if nfile >= nmax:
                        print(f'Reached maximum allowable number of frames = {nmax}; stopping.')
                        print(f'Written {nfile} FITS files to disk.')
                        return

                    # Make header
                    header=fits.Header(phead.cards)

                    # attempt to generate a WCS
                    instrume = header.get('INSTRUME','UNKNOWN')
                    if instrume == 'HIPERCAM' and 'RA' in header and \
                       'DEC' in header and 'INSTRPA' in header:
                        ra = header['RA']
                        dec = header['DEC']
                        pa = header['INSTRPA']
                        x0, y0 = (1020.-llxmin+1)/xbin, (524.-llymin+1)/ybin
                        pos0 = SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
                        print(ra, dec, pos0.to_string('hmsdms'))
                        scale = 0.081*u.arcsec # pixel scale

                        # 5 points in all, centred upon the rotator centre x0, y0
                        # in a + shape.
                        # 1) centre, 2) up, 3) right, 4) down, 5) left
                        xsteps = [0,0,100,0,-100]
                        ysteps = [0,100,0,-100,0]
                        bfacs = [1,ybin,xbin,ybin,xbin]
                        seps = [0,100,100,100,100]
                        pa -= 90
                        pas = [0,pa,pa+90,pa+180,pa+270]
                        xs,ys,poss = [],[],[]
                        for xstep,ystep,bfac,sep,pa in zip(xsteps,ysteps,bfacs,seps,pas):
                            x = x0 + xstep
                            y = y0 + ystep
                            pos = pos0.directional_offset_by(pa*u.deg, bfac*sep*scale)
                            xs.append(x)
                            ys.append(y)
                            poss.append(pos)
                        poss = SkyCoord(poss)
                        w = wcs.utils.fit_wcs_from_points(
                            (np.array(xs),np.array(ys)),
                            poss, proj_point='center',
                        )
                        print('wcs=',w)
                        header.update(w.to_header())

                    # make the first & only HDU
                    hdul = fits.HDUList()
                    if compress == 'none':
                        hdul.append(fits.PrimaryHDU(data, header=header))
                    else:
                        hdul.append(fits.PrimaryHDU(header=header))
                        compressed_hdu = fits.CompImageHDU(
                            data=data, compression_type=ctrans[compress]
                        )
                        hdul.append(compressed_hdu)

                    oname = f'{os.path.basename(resource)}_ccd{cnam}_{nf:0{ndigit}d}.fits'
                    hdul.writeto(oname, overwrite=overwrite)
                    print(f'   CCD {cnam} written to {oname}')
                    nfile += 1

            # update the frame number
            nframe += 1
            if server_or_local and last and nframe > last:
                break

    print(f'Written {nfile} FITS files to disk.')
