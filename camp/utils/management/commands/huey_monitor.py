import os
import time

from django.core.management.base import BaseCommand

import asciichartpy
from huey.contrib.djhuey import HUEY


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        pending_tasks = []
        try:
            while True:
                terminal_size = os.get_terminal_size()
                pending_tasks.append(HUEY.pending_count())
                pending_tasks = pending_tasks[-(terminal_size.columns - 15):]

                os.system('clear')

                print(asciichartpy.plot(pending_tasks, {
                    'min': 0,
                    'height': max(10, terminal_size.lines - 10),
                    'format': '{:8.0f}',
                    'colors': [asciichartpy.lightmagenta],
                }))
                print(f'Pending Tasks: {pending_tasks[-1]}')

                time.sleep(1)
        except KeyboardInterrupt:
            print('\nCtrl+C detected, stopping...')
