import os
import pickle
import sys
import time

from collections import Counter

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

    def task_rate(self, key):
        if len(self.tasks[key]) < 3:
            return 0
        diffs = [self.tasks[key][i] - self.tasks[key][i - 1] for i in
            range(len(self.tasks[key]) - 3, len(self.tasks[key]))]
        return sum(diffs) / len(diffs)

    def queue_counter(self, queue_name):
        queue = self.queues[queue_name]
        counter = Counter()
        for raw in queue.storage.enqueued_items():
            message = pickle.loads(raw)
            counter[message.name] += 1
        return counter

    def handle(self, *args, **options):
        self.keys = self.get_keys(options.get('queue'))
        self.queues = {key: get_queue(key) for key in self.keys}
        self.tasks = {key: [] for key in self.keys}
        colors = [asciichartpy.lightmagenta, asciichartpy.lightcyan]

        try:
            while True:
                print('\033[?25l', end='')  # hide cursor

                buffer = []

                terminal_size = os.get_terminal_size()

                for i, key in enumerate(self.keys):
                    counter = self.queue_counter(key)
                    self.tasks[key].append(counter.total())
                    self.tasks[key] = self.tasks[key][-(terminal_size.columns - 9):]

                    task_rate = int(round(self.task_rate(key)))
                    try:
                        color = colors[i]
                    except IndexError:
                        color = asciichartpy.default

                    buffer.append(f'{color}{key}{asciichartpy.reset}: {self.tasks[key][-1]} {asciichartpy.lightgray}({task_rate} tasks/sec){asciichartpy.reset}')
                    for task, count in counter.most_common():
                        buffer.append(f' ├ {color}{task}{asciichartpy.reset}: {count}{asciichartpy.reset}')

                buffer.append('─' * terminal_size.columns)
                buffer.append(asciichartpy.plot([self.tasks[key] for key in self.keys], {
                    'min': 0,
                    'height': max(10, terminal_size.lines - len(buffer) - 3),
                    'format': '{:8.0f}',
                    'colors': colors,
                }))
                buffer.append('─' * terminal_size.columns)

                # os.system('clear')
                sys.stdout.write('\033[H\033[J')  # Move cursor to top-left and clear screen
                sys.stdout.flush()
                print('\n'.join(buffer))
                time.sleep(1)
        except KeyboardInterrupt:
            print('\nCtrl+C detected, stopping...')
        finally:
            print('\033[?25h', end='')  # show cursor again
