import csv
import itertools
import sys

from datetime import date, time, datetime, timedelta
from pprint import pprint

import numpy as np

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import pytz

from camp.apps.monitors.models import Group
from camp.datasci import UnivariateLinearRegression

# Example:
#   python manage.py analyze_monitor_batch \
#   -g "UCMerced - Batch June 2024" \
#   -sd 2024-06-01 -ed 2024-06-30 \
#   -o ./export/ucmerced-06-2024.csv

TZ = pytz.timezone('America/Los_Angeles')

def cycle_monitors(queryset):
    cycle = itertools.cycle(queryset)
    total = len(queryset) # not .count(), no need for an extra query
    for i, monitor in enumerate(cycle):
        if i == total:
            break
        yield monitor


def r(n):
    return round(n, 5)


class Command(BaseCommand):
    help = 'Analyze a batch of monitors'

    def add_arguments(self, parser):
        parser.add_argument('--group', '-g', action='store', type=str, default=None)
        parser.add_argument('--end_date', '-ed', action='store', type=str, default=None)
        parser.add_argument('--start_date', '-sd', action='store', type=str, default=None)
        parser.add_argument('--output', '-o', action='store', type=str, default=None)

    def handle(self, *args, **options):
        lookup = self.get_lookup(**options)
        group = Group.objects.get(name=options['group'])
        

        self.data = []
        self.rows = []
        queryset = group.monitors.select_related('latest').order_by('name')
        queryset = queryset.filter(pk__in=['HEoirP4rQeySlZlT0r3w2A', 'Oj5xfOnIRwmFFU0gy8sxrw', 'ifWdgoRfQFCjR0fqBOSj3w']).distinct()
        monitor_count = queryset.count()

        # Intradevice analysis
        for i, monitor in enumerate(queryset):
            print(f'Intra ({i} / {monitor_count}) {monitor.name} ({monitor.pk})')
            a = monitor.entries.filter(sensor=monitor.SENSORS[0], **lookup)
            b = monitor.entries.filter(sensor=monitor.SENSORS[1], **lookup)
            results = self.generate_regression(a, b)
            is_valid = self.validate_results(results)

            self.data.append({
                'monitor': monitor,
                'a': a,
                'b': b,
                'intradevice': results,
                'intradevice_valid': is_valid,
            })

        # Interdevice Analysis
        for i, monitor in enumerate(self.data):
            print(f"Inter ({i} / {monitor_count}) {monitor['monitor'].name} ({monitor['monitor'].pk})")
            if not monitor['intradevice_valid']:
                monitor['interdevice'] = None
                monitor['interdevice_valid'] = False
                continue

            monitor2_idx = self.find_next_monitor(i)
            monitor2 = self.data[monitor2_idx]

            if monitor2 is None:
                continue

            results = self.generate_regression(monitor['a'], monitor2['b'])
            is_valid = self.validate_results(results)

            monitor.update({
                'interdevice': results,
                'interdevice_valid': is_valid,
                'interdevice_monitor': monitor2,
            })

        self.prep_output()
        self.save_or_display(options, lookup)

    def save_or_display(self, options, lookup):
        if options['output']:
            with open(options['output'], 'w') as f:
                keys = self.rows[sorted([(i, len(x.keys())) for i, x in enumerate(self.rows)], key=lambda x: x[1], reverse=True)[0][0]].keys()
                writer = csv.DictWriter(f, keys)
                writer.writerow({
                    'Monitor ID': 'Start Date',
                    'Monitor Name': lookup['timestamp__range'][0]
                })
                writer.writerow({
                    'Monitor ID': 'End Date',
                    'Monitor Name': lookup['timestamp__range'][1]
                })
                writer.writeheader()
                writer.writerows(self.rows)
        else:
            pprint(self.rows)

    def prep_output(self):
        for monitor in self.data:
            self.rows.append({
                'Monitor ID': monitor['monitor'].pk,
                'Monitor Name': monitor['monitor'].name,
                'Is Active': str(monitor['monitor'].is_active).upper(),
                'Latest Entry': monitor['monitor'].latest.timestamp.astimezone(TZ) if not monitor['monitor'].is_active else '',
                'Hours': 0,
                'Intra Pass': str(monitor['intradevice_valid']).upper(),
                'Inter Pass': str(monitor['interdevice_valid']).upper(),
            })

            if monitor['intradevice'] is not None:
                results = monitor['intradevice']
                df = results.reg.df
                self.rows[-1].update({'Hours': len(df)})
                self.rows[-1].update(self.prep_results_row(results, 'Intra'))
                self.rows[-1].update({
                    'Intra A Max': r(df['endog_value'].max()),
                    'Intra B Max': r(df['exog_value'].max()),
                    'Intra A Min': r(df['endog_value'].min()),
                    'Intra B Min': r(df['exog_value'].min()),
                    'Intra A Mean': r(df['endog_value'].mean()),
                    'Intra B Mean': r(df['exog_value'].mean()),
                })

            if monitor['interdevice'] is not None:
                results = monitor['interdevice']
                df = results.reg.df.round(5)
                self.rows[-1].update({
                    'Inter Monitor ID': monitor['interdevice_monitor']['monitor'].pk,
                    'Inter Monitor Name': monitor['interdevice_monitor']['monitor'].name,
                })
                self.rows[-1].update(self.prep_results_row(results, 'Inter'))

    def prep_results_row(self, results, prefix):
        if results is None:
            return {}

        return {
            f'{prefix} R2': r(results.r2),
            f'{prefix} Intercept': r(results.intercept),
            f'{prefix} Coefficient': r(results.coefs['pm25_reported']),
            f'{prefix} Variance Score': r(results.variance),
            f'{prefix} Variance Mean': r(results.reg.df.var(axis='columns').mean()),
            f'{prefix} Percent Change Mean': r((results.reg.df
                .pct_change(axis='columns')['exog_value']
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .abs()
                .mean()
            )),
        }

    def find_next_monitor(self, i):
        for j, monitor in enumerate(self.data[i + 1:]):
            if monitor['intradevice_valid']:
                return i + j + 1

        for j, monitor in enumerate(self.data[:i]):
            if monitor['intradevice_valid']:
                return i

    def generate_regression(self, a, b):
        linreg = UnivariateLinearRegression(a, b, 'pm25_reported')
        results = linreg.generate_regression()
        if results is not None:
            results.is_valid = self.validate_results(results)
        return results

    def validate_results(self, results):
        if results is None:
            return False

        if results.r2 < 0.98:
            return False

        if results.variance < .9:
            return False

        return True

    def get_lookup(self, **options):
        end_date = timezone.now().date()
        if options['end_date'] is not None:
            end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()

        end_date = datetime.combine(end_date, time.max)
        end_date = timezone.make_aware(end_date, TZ)

        if options['start_date'] is not None:
            start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
        else:
            start_date = (lookup['timestamp__lte'] - timedelta(days=14)).date()

        start_date = datetime.combine(start_date, time.min)
        start_date = timezone.make_aware(start_date, TZ)

        return {'timestamp__range': (start_date, end_date)}
