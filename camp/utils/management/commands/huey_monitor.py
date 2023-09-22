import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

import asciichartpy
from django_huey import get_queue


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--queue', '-q', action='store', type=str)

    def get_keys(self, key=None):
        if key is not None:
            return [key]
        return list(settings.DJANGO_HUEY['queues'].keys())

    def handle(self, *args, **options):
        self.keys = self.get_keys(options.get('queue'))
        self.queues = {key: get_queue(key) for key in self.keys}
        self.tasks = {key: [] for key in self.keys}
        colors = [asciichartpy.lightmagenta, asciichartpy.lightcyan]

        try:
            while True:
                terminal_size = os.get_terminal_size()

                for key in self.keys:
                    self.tasks[key].append(self.queues[key].pending_count())
                    self.tasks[key] = self.tasks[key][-(terminal_size.columns - 15):]

                os.system('clear')

                print(asciichartpy.plot([self.tasks[key] for key in self.keys], {
                    'min': 0,
                    'height': max(10, terminal_size.lines - 10),
                    'format': '{:8.0f}',
                    'colors': colors,
                }))

                print('')
                for i, key in enumerate(self.keys):
                    try:
                        color = colors[i]
                    except IndexError:
                        color = asciichartpy.default

                    print(f'{color}{key}{asciichartpy.reset}: {self.tasks[key][-1]}')

                time.sleep(1)
        except KeyboardInterrupt:
            print('\nCtrl+C detected, stopping...')
