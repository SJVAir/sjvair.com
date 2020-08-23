from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand
from django.utils import timezone

import geopandas as gpd
from shapely.geometry import shape

from camp.apps.monitors.purpleair import api
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.forms import PurpleAirAddForm
from camp.utils.datafile import datafile


class Command(BaseCommand):
    def load_counties(self):
        geometry = [
            shape(county['geometry']) for county
            in datafile('california-counties.geojson')['features']
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
        ]
        return gpd.GeoDataFrame({'geometry': geometry})

    def handle(self, *args, **kwargs):
        counties = self.load_counties()
        monitors = api.get_monitors()
        for monitor in monitors:
            if monitor.get('ParentID'):
                continue
            if not monitor.get('Lat') or not monitor.get('Lon'):
                continue

            point = shape({'type': 'Point', 'coordinates': [monitor['Lon'], monitor['Lat']]})
            if counties.contains(point).any():
                try:
                    PurpleAir.objects.get(name=monitor['Label'])
                except PurpleAir.DoesNotExist:
                    print(monitor['Label'])
                    form = PurpleAirAddForm({'purple_id': monitor['ID']})
                    assert form.is_valid()
                    form.save()
