import json

from django.contrib.gis.geos import GEOSGeometry
from django.utils.functional import cached_property

from camp.utils.datafiles import datafile


class County:
    counties = {
        county['properties']['name']: GEOSGeometry(json.dumps(county['geometry']))
        for county in datafile('california-counties.geojson')['features']
        if county['properties']['name'] in [
            'Fresno',
            'Kern',
            'Kings',
            'Madera',
            'Merced',
            'San Joaquin',
            'Stanislaus',
            'Tulare',
        ]
    }

    names = list(sorted(counties.keys()))
    keys = {name.lower().replace(' ', '_'): name for name in names}

    @classmethod
    def lookup(cls, point, default=''):
        for name, geometry in cls.counties.items():
            if geometry.contains(point):
                return name
        return default
