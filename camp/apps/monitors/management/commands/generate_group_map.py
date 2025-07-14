import code
import sys

from urllib.parse import urlencode

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import numpy as np

from camp.apps.monitors.models import Group

def hex_to_rgb(c):
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % rgb

def array_multiply(array, c):
    return [element * c for element in array]

def array_sum(a, b):
    return tuple(map(int, map(sum, zip(a, b))))

def intermediate(a, b, ratio):
    aComponent = array_multiply(a, ratio)
    bComponent = array_multiply(b, 1 - ratio)
    return array_sum(aComponent, bComponent)

def gradient(a, b, steps):
    steps = [n / float(steps) for n in range(steps)]
    return [intermediate(a, b, step) for step in steps][::-1]


pm_colors = (
    (0, 12, hex_to_rgb('78FA4C')),
    (12.1, 35.4, hex_to_rgb('FFFE54')),
    (35.5, 55.4, hex_to_rgb('D4712B')),
    (55.5, 150.4, hex_to_rgb('C3281C')),
    (150.5, 250.4, hex_to_rgb('66567E')),
    (250.5, 999999, hex_to_rgb('653734')),
)

def pm_color(pm):
    pm = max(float(pm), 0)
    for i, (low, high, color) in enumerate(pm_colors):
        if low <= pm <= high:
            try:
                next_low, next_high, next_color = pm_colors[i + 1]
            except IndexError:
                return color

            percent = int(round((100 / (high - low)) * (pm - low)))
            colors = [color] + gradient(color, next_color, 100)
            return colors[percent]


class Command(BaseCommand):
    help = 'Analyze a batch of monitors'

    def add_arguments(self, parser):
        parser.add_argument('--group', '-g', action='store', type=str, default=None)

    def handle(self, *args, **options):
        self.group = Group.objects.get(pk=options['group'])

        url = 'https://api.maptiler.com/maps/openstreetmap/static/auto/400x300@2x.png'
        params = {
            'key': settings.MAPTILER_API_KEY,
            'attribution': 'false',
            'padding': '.75',
            'markers': self.generate_markers(),
        }

        print(params['markers'], '\n\n')

        print(f'{url}?{urlencode(params)}')

    def generate_markers(self):
        data = []
        queryset = (self.group.monitors
            .exclude(is_hidden=True)
            .select_related('latest')
        )

        for monitor in queryset:
            if not monitor.is_active or not monitor.latest:
                continue

            color = pm_color(monitor.latest.pm25)
            if color is None:
                color = hex_to_rgb('cccccc')

            data.append((
                str(monitor.position.x),
                str(monitor.position.y),
                rgb_to_hex(color),
            ))

        return '|'.join([','.join(m) for m in data])



