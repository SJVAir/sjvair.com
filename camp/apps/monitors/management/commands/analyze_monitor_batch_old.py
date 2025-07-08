import csv
import sys

from datetime import date, time, datetime, timedelta
from itertools import cycle
from pprint import pprint

import numpy as np

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import pytz

from camp.apps.monitors.models import Group
from camp.datasci import UnivariateLinearRegression

TZ = pytz.timezone('America/Los_Angeles')


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
        monitor_count = group.monitors.count()
        data = []
        queryset = group.monitors.select_related('latest')

        for i, monitor in enumerate(queryset):
            print(f'({i} / {monitor_count}) {monitor.name} ({monitor.pk})')
            a = monitor.entries.filter(sensor=monitor.SENSORS[0], **lookup)
            b = monitor.entries.filter(sensor=monitor.SENSORS[1], **lookup)

            linreg = UnivariateLinearRegression(a, b, 'pm25_reported')
            results = linreg.generate_regression()

            # if i == 1:
            #     import code
            #     code.interact(local=locals())
            #     sys.exit()
            #     break

            data.append({
                'Monitor ID': monitor.pk,
                'Monitor Name': monitor.name,
                'Latest Entry': monitor.latest.timestamp.astimezone(TZ),
                'Hours': 0,
            })

            if results is None:
                continue

            data[-1].update({
                'Hours': len(linreg.df),
                'R2': results.r2,
                'Intercept': results.intercept,
                'Coefficient': results.coefs['pm25_reported'],
                'Variance Score': results.variance,
                'Variance Mean': linreg.df.var(axis='columns').mean(),
                'Percent Change Mean': round((linreg.df
                    .pct_change(axis='columns')['exog_value']
                    .replace([np.inf, -np.inf], np.nan)
                    .dropna()
                    .abs()
                    .mean()
                ), 3),
                'A Max': round(linreg.df['endog_value'].max(), 3),
                'B Max': round(linreg.df['exog_value'].max(), 3),
                'A Min': round(linreg.df['endog_value'].min(), 3),
                'B Min': round(linreg.df['exog_value'].min(), 3),
                'A Mean': round(linreg.df['endog_value'].mean(), 3),
                'B Mean': round(linreg.df['exog_value'].mean(), 3),
            })

            for monitor in data:
                monitor['Passes?'] = str(self.analyze_results(results)).upper()

        if not data:
            print('No data to save.')
            return

        if options['output']:
            with open(options['output'], 'w') as f:
                keys = data[sorted([(i, len(x.keys())) for i, x in enumerate(data)], key=lambda x: x[1], reverse=True)[0][0]].keys()
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
                writer.writerows(data)
        else:
            pprint(data)

    def analyze_intradevice_results(self, results):
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
