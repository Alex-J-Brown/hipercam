# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""
hipercam is a package for the reduction of data from the 5-band multi-window
high-speed CCD camera HiPERCAM.
"""

# Affiliated packages may add whatever they like to this file, but
# should keep this content at the top.
# ----------------------------------------------------------------------------
from ._astropy_init import *
# ----------------------------------------------------------------------------

# For egg_info test builds to pass, put package imports here.
if not _ASTROPY_SETUP_:
    from .group import *
    from .window import *
    from .ccd import *
    from .aperture import *
    import mpl


