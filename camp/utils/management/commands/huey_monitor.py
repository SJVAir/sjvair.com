import os
import time

from django.core.management.base import BaseCommand

import asciichartpy
from django_huey import get_queue


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--queue', '-q', action='store', type=str)

    def handle(self, *args, **options):
        queue = get_queue(options['queue'])
        pending_tasks = []
        try:
            while True:
                terminal_size = os.get_terminal_size()
                pending_tasks.append(queue.pending_count())
                pending_tasks = pending_tasks[-(terminal_size.columns - 15):]

                os.system('clear')

                print(asciichartpy.plot(pending_tasks, {
                    'min': 0,
                    'height': max(10, terminal_size.lines - 10),
                    'format': '{:8.0f}',
                    'colors': [asciichartpy.lightmagenta],
                }))
                print(f'Queue: {queue.name}')
                print(f'Pending Tasks: {pending_tasks[-1]}')

                time.sleep(1)
        except KeyboardInterrupt:
            print('\nCtrl+C detected, stopping...')
