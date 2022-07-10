from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand
from django.utils import timezone

import geopandas as gpd
from shapely.geometry import shape

from camp.apps.monitors.purpleair.api import purpleair_api
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.forms import PurpleAirAddForm
from camp.utils.datafiles import datafile


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
        monitors = purpleair_api.get_monitors(
            fields=['sensor_index', 'name', 'longitude', 'latitude']
        )

        for monitor in monitors:
            if not monitor.get('latitude') or not monitor.get('longitude'):
                continue

            point = shape({
                'type': 'Point',
                'coordinates': [monitor['longitude'], monitor['latitude']]
            })

            if counties.contains(point).any():
                try:
                    PurpleAir.objects.get(data__sensor_index=monitor['sensor_index'])
                except PurpleAir.DoesNotExist:
                    print(monitor['name'])
                    form = PurpleAirAddForm({'purple_id': monitor['sensor_index']})
                    assert form.is_valid()
                    form.save()
