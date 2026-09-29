"""
ICIS-Air ids that don't encode a CEIDARS facility id (Eastern Kern APCD's
`CAKCA…`, EPA Region 9's `0900…` / `CA0000…`), matched by hand:
pgm_sys_id -> (CARB county code, air district external id, facid). Empty
until someone checks the rows against the permit portal; icis.apply stores
unmatched rows but never shows them.
"""

CROSSWALK = {}
