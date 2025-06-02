import json

from django.contrib.gis.geos import GEOSGeometry
from django.utils.functional import cached_property

from camp.utils.datafiles import datafile
from shapely.wkt import loads as load_wkt

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


    @classmethod
    def within_SJV(cls, geometry_shape, default=0):
        for name, geometry in cls.counties.items():
            shapely_county = load_wkt(geometry.wkt)
            if shapely_county.intersects(geometry_shape):
                return 1
        return default