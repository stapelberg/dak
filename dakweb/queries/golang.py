"""Golang related queries

@contact: https://pkg-go.alioth.debian.org/
@copyright: 2017 Michael Stapelberg <stapelberg@debian.org>
@license: GNU General Public License version 2 or later
"""

import bottle
import json

from daklib.dbconn import DBConn, MetadataKey
from dakweb.webregister import QueryRegister


@bottle.route('/golang/import_paths')
def import_paths():
    """
    Returns a mapping of Go import path to Debian binary package name and
    corresponding Debian source package name.

    @rtype: dictionary
    @return: A list of dictionaries of
             - binary
             - source
             - importpath
    """

    s = DBConn().session()
    conn = s.connection()
    res = conn.execute("""
    SELECT
        binaries.package,
        source.source,
        source_metadata.value AS importpath
    FROM
        binaries LEFT JOIN
        source ON (binaries.source = source.id) LEFT JOIN
        source_metadata ON (source.id = source_metadata.src_id) LEFT JOIN
        metadata_keys ON (source_metadata.key_id = metadata_keys.key_id)
    WHERE
        metadata_keys.key = 'Go-Import-Path'
    GROUP BY
        binaries.package,
        source.source,
        source_metadata.value;
    """)
    out = [{'binary': res[0], 'source': res[1], 'importpath': res[2]} for res in res]
    s.close()

    return json.dumps(out)

QueryRegister().register_path('/golang/import_paths', import_paths)
