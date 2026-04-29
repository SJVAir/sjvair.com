import itertools
import os
import pickle
import shutil
import sys
import time

from collections import Counter
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

import asciichartpy
from django_huey import get_queue


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--queue', '-q', action='store', type=str)
        parser.add_argument('--interval', '-i', action='store', type=float, default=1.0)

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

    def trend(self, key):
        if len(self.tasks[key]) < 2:
            return asciichartpy.lightgray + '→' + asciichartpy.reset
        last, prev = self.tasks[key][-1], self.tasks[key][-2]
        if last > prev:
            return asciichartpy.lightred + '↑' + asciichartpy.reset
        if last < prev:
            return asciichartpy.lightgreen + '↓' + asciichartpy.reset
        return asciichartpy.lightgray + '→' + asciichartpy.reset

    def format_rate(self, rate):
        r = int(round(rate))
        if r > 0:
            return f'{asciichartpy.lightred}+{r}/s{asciichartpy.reset}'
        if r < 0:
            return f'{asciichartpy.lightgreen}{r}/s{asciichartpy.reset}'
        return f'{asciichartpy.lightgray}0/s{asciichartpy.reset}'

    def handle(self, *args, **options):
        self.keys = self.get_keys(options.get('queue'))
        self.queues = {key: get_queue(key) for key in self.keys}
        self.tasks = {key: [] for key in self.keys}
        interval = options['interval']

        palette = [
            asciichartpy.lightmagenta,
            asciichartpy.lightcyan,
            asciichartpy.lightgreen,
            asciichartpy.lightyellow,
            asciichartpy.lightred,
            asciichartpy.lightblue,
            asciichartpy.white,
        ]

        try:
            while True:
                print('\033[?25l', end='')  # hide cursor

                try:
                    terminal_size = shutil.get_terminal_size()

                    # Build the stats panel (pinned to bottom)
                    stats = []
                    chart_colors = []
                    colors = itertools.cycle(palette)

                    for key in self.keys:
                        color = next(colors)
                        chart_colors.append(color)

                        counter = self.queue_counter(key)
                        self.tasks[key].append(counter.total())
                        self.tasks[key] = self.tasks[key][-(terminal_size.columns - 9):]

                        stats.append(
                            f'{color}{key}{asciichartpy.reset}: '
                            f'{self.trend(key)} {self.tasks[key][-1]} queued'
                            f'{asciichartpy.lightgray} | '
                            f'({self.format_rate(self.task_rate(key))}{asciichartpy.lightgray}){asciichartpy.reset}'
                        )
                        for task, count in counter.most_common():
                            stats.append(f' ├ {color}{task}{asciichartpy.reset}: {count}')

                    timestamp = datetime.now().strftime('%H:%M:%S')

                    # Chart fills whatever space remains below the stats panel
                    # stats + separator + chart + separator + timestamp = terminal_size.lines
                    chart_height = max(5, terminal_size.lines - len(stats) - 4)
                    chart = asciichartpy.plot([self.tasks[key] for key in self.keys], {
                        'min': 0,
                        'height': chart_height,
                        'format': '{:8.0f}',
                        'colors': chart_colors,
                    })

                    buffer = stats + ['─' * terminal_size.columns, chart, '─' * terminal_size.columns]
                    buffer.append(f'{asciichartpy.lightgray}[{timestamp}]{asciichartpy.reset}')

                    sys.stdout.write('\033[2J\033[H')  # clear screen, move cursor to top-left
                    sys.stdout.write('\n'.join(buffer))
                    sys.stdout.flush()
                except Exception:
                    pass  # skip render on resize or other transient error

                time.sleep(interval)
        except KeyboardInterrupt:
            print('\nCtrl+C detected, stopping...')
        finally:
            print('\033[?25h', end='')  # show cursor again
