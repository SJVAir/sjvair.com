from datetime import timedelta

from django.conf import settings
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

    def get_group_members(self):
        member_list = purpleair_api.get_group(settings.PURPLEAIR_GROUP_ID)['members']
        return [member['sensor_index'] for member in member_list]

    def handle(self, *args, **kwargs):
        counties = self.load_counties()
        members = self.get_group_members()

        # TODO: Pass in the bounding box of all the counties to limit
        # the number of sensors fetched from the PurpleAir API.
        monitors = purpleair_api.list_sensors(
            fields=['sensor_index', 'name', 'longitude', 'latitude']
        )

        print('Total monitors from PurpleAir:', len(monitors))
        print('Number of monitors in our group:', len(members))

        for monitor in monitors:
            if not monitor.get('latitude') or not monitor.get('longitude'):
                continue

            point = shape({
                'type': 'Point',
                'coordinates': [monitor['longitude'], monitor['latitude']]
            })

            if counties.contains(point).any() and monitor['sensor_index'] not in members:
                # All we need to do is add it to the group within PurpleAir,
                # and we'll pick it up on the next import pass.
                print(f'Adding #{monitor["sensor_index"]} - {monitor["name"]}')
                purpleair_api.create_group_member(
                    settings.PURPLEAIR_GROUP_ID,
                    monitor['sensor_index']
                )
