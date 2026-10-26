"""
The dashboard's Content Security Policy, built from csp-hosts.json.

csp-hosts.json is a copy of data-dashboard's own csp-hosts.json (the
reference list of every host its code needs). Change the two together: a
data-dashboard PR that changes its list says so, and the matching change
lands here.
"""
import functools
import json
from pathlib import Path

HOSTS_PATH = Path(__file__).parent / 'csp-hosts.json'


@functools.lru_cache
def build_policy(static_url, report_uri=''):
    """
    The policy string. `{static}` becomes the dashboard's static folder
    (STATIC_URL + 'workspace/') when STATIC_URL is absolute, as on S3. A bare
    path like /static/ isn't a valid source; 'self' already covers it there.
    """
    absolute = static_url.startswith(('http://', 'https://'))
    static = f'{static_url}workspace/'
    directives = []
    for name, sources in json.loads(HOSTS_PATH.read_text()).items():
        sources = [
            static if source == '{static}' else source
            for source in sources
            if source != '{static}' or absolute
        ]
        directives.append(' '.join([name, *sources]))
    if report_uri:
        directives.append(f'report-uri {report_uri}')
    return '; '.join(directives)


def policy_header_name(enforce):
    return 'Content-Security-Policy' if enforce else 'Content-Security-Policy-Report-Only'
