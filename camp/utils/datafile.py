import json
import os

import yaml

from django.conf import settings


def datafile(filename, mode='r'):
    path = settings.BASE_DIR.child('datafiles', *filename.split(os.sep))
    contents = open(path, mode).read()
    if path.ext in ['.json', '.geojson']:
        return json.loads(contents)
    if path.ext == '.yaml':
        return yaml.safe_load(contents)
    return contents
