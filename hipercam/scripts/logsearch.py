import sys
import re
import sqlite3

import numpy as np
import pandas as pd

import hipercam as hcam
from hipercam import cline, utils
from hipercam.cline import Cline
from hipercam.utils import target_lookup

__all__ = [
    "logsearch",
]

#######################################################################
#
# logsearch -- carries out a search for objects in data logs
#
#######################################################################

def logsearch(args=None):
    description = \
    """``logsearch target (dmax) regex (nocase) tmin [hcamdb ucamdb
    uspecdb] output``

    Searches for targets in the |hiper| and |ucam| logs. It can carry
    out a coordinate lookup given a name and/or carry out a regular
    expression search. It uses the sqlite3 databases generated by
    |hlogger| which can be downloaded from the (password protected)
    log webpages hosted at Warwick.

    If a target name is entered, it will first searched for in
    SIMBAD. If that fails, it will be searched for coordinates in the
    form "J123456.7-123456" or similar, so the latter is always the
    fallback for objects that don't appear in SIMBAD. It can also search
    by regular expression matching.

    Arguments::

       target : str
          Target name. On the command line, must be enclosed in quotes if it
          contains spaces. This will be used first to carry out a lookup in
          SIMBAD to find the RA and Dec. Failing this it tries to identify
          coordinates from a final strength of the form JHHMMSS.S[+/-]DDMMSS
          Enter "none" to ignore.

       tmin : float
          Minimum exposure duration seconds to cut down on chaff.

       dmax : float
          Maximum distance from lookup position, arcminutes

       regex : str
          Regular expression to use to try to match target names in addition to
          the coordinate matching. "none" to ignore.

       nocase : bool [if regex is not "none"]
          True for case-insensitive matching, else case-sensitive used with regex

       hcamdb : database [hidden]
          Path to |hiper| database which will probably be called hipercam.db if
          downloaded from the Warwick logs. 'none' to ignore. Best to specify
          the full path when setting this to allow searches to be undertaken from
          any directory.

       ucamdb : database [hidden]
          Path to ULTRACAM database which will probably be called ultracam.db if
          downloaded from the Warwick logs. 'none' to ignore. Best to specify
          the full path when setting this to allow searches to be undertaken from
          any directory.

       uspecdb : database [hidden]
          Path to ULTRASPEC database which will probably be called ultraspec.db if
          downloaded from the Warwick logs. 'none' to ignore. Best to specify
          the full path when setting this to allow searches to be undertaken from
          any directory.

       output : str
          Name of CSV file to store the results. 'none' to ignore. The
          results are best viewed in an excel-type programme or
          topcat, or they can be read programatically into a pandas
          Dataframe using pd.read_csv('results.csv'). Results from all
          instruments are concatenated which for instance means that a
          column appropriate for hipercam, might be blank for ULTRACAM
          and vice versa. An extra "Instrument" column is added to
          make the origin clear.  """

    command, args = utils.script_args(args)

    with Cline("HIPERCAM_ENV", ".hipercam", command, args) as cl:

        # register parameters
        cl.register("target", Cline.LOCAL, Cline.PROMPT)
        cl.register("dmax", Cline.LOCAL, Cline.PROMPT)
        cl.register("regex", Cline.LOCAL, Cline.PROMPT)
        cl.register("nocase", Cline.LOCAL, Cline.PROMPT)
        cl.register("tmin", Cline.LOCAL, Cline.PROMPT)
        cl.register("hcamdb", Cline.LOCAL, Cline.HIDE)
        cl.register("ucamdb", Cline.LOCAL, Cline.HIDE)
        cl.register("uspecdb", Cline.LOCAL, Cline.HIDE)
        cl.register("output", Cline.LOCAL, Cline.PROMPT)

        # get inputs
        target = cl.get_value(
            "target", "target name for simbad lookup ['none' to ignore]",
            "AR Sco", ignore="none"
        )

        if target is not None:
            dmax = cl.get_value(
                "dmax", "maximum distance from target [arcminutes]",
                12., 0.
            )

            regex = cl.get_value(
                "regex", "regular expression to match target name ['none' to ignore]",
                "none", ignore="none"
            )

        else:
            regex = cl.get_value(
                "regex", "regular expression to match target name",
                "ar\s*sco"
            )

        if regex is not None:
            nocase = cl.get_value(
                "nocase", "case insensitive match?", True
            )

        tmin = cl.get_value(
            "tmin", "minimum exposure duration for a run to be included [seconds]", -1.
        )

        hcamdb = cl.get_value(
            "hcamdb", "path to hipercam sqlite3 database ['none' to ignore]",
            cline.Fname("hipercam.db", ".db"), ignore="none"
        )

        ucamdb = cl.get_value(
            "ucamdb", "path to ultracam sqlite3 database ['none' to ignore]",
            cline.Fname("ultracam.db", ".db"), ignore="none"
        )

        uspecdb = cl.get_value(
            "uspecdb", "path to ultraspec sqlite3 database ['none' to ignore]",
            cline.Fname("ultraspec.db", ".db"), ignore="none"
        )

        output = cl.get_value(
            "output", "name of spreadsheet of results ['none' to ignore]",
            cline.Fname('results', '.csv', cline.Fname.NEW), ignore="none"
        )

    # check that at least one database is defined
    dbs = []
    if hcamdb is not None: dbs.append('HiPERCAM')
    if ucamdb is not None: dbs.append('ULTRACAM')
    if uspecdb is not None: dbs.append('ULTRASPEC')

    if len(dbs):
        print(f"Will search the following instruments database files: {', '.join(dbs)}")
    else:
        print(f"No databases defined; please run 'logsearch' with 'prompt' to set them")
        exit(1)

    if target is not None:
        name, ra, dec = target_lookup(target)
        if name == 'UNDEF':
            print(f'Coordinate lookup for "{target}" failed')
            exit(1)

        print(
            f'Coordinate lookup for "{target}" returned name = "{name}", RA [hrs] = {ra}, Dec [deg] = {dec}'
        )

        field = dmax/60.
        ra *= 15
        cdec = np.cos(np.radians(dec))
        ralo = ra - field/cdec
        rahi = ra + field/cdec
        declo = dec - field
        dechi = dec + field

    # assemble pairs of databases files and tables
    dbases = []
    if hcamdb is not None: dbases.append((hcamdb,'hipercam'))
    if ucamdb is not None: dbases.append((ucamdb,'ultracam'))
    if uspecdb is not None: dbases.append((uspecdb,'ultraspec'))

    results = []
    for dbase, dtable in dbases:

        # connect to database
        conn = sqlite3.connect(dbase)

        # build query string
        query = f'SELECT * FROM {dtable}\n'

        if target is not None:
            query += (
                f"WHERE (ra_deg > {ralo} AND ra_deg < {rahi}\n"
                f"AND dec_deg > {declo} AND dec_deg < {dechi}\n"
                f"AND total > {tmin})\n"
            )

            if regex is not None:
                conn.create_function("REGEXP", 2, regexp)
                query += f'OR (REGEXP("{regex}",target) AND total > {tmin})'

        else:
            conn.create_function("REGEXP", 2, regexp)
            query += f'WHERE (REGEXP("{regex}",target) AND total > {tmin})'

        print(f'\nQuerying {dbase}\n')
        res = pd.read_sql_query(query, conn)
        if len(res):
            print(res)
            res['Instrument'] = dtable
            results.append(res)
        else:
            print('   no runs found')

        # close connection
        conn.close()

        if output is not None:
            total = pd.concat(results)
            total.to_csv(output)

def regexp(expr, item):
    reg = re.compile(expr,re.IGNORECASE)
    return reg.search(item) is not None
