import csv
import itertools
from dataclasses import dataclass
from datetime import date, time, datetime, timedelta
from pprint import pprint
from typing import Optional

import pandas as pd
import pytz

from django.core.management.base import BaseCommand
from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.models import Group, Monitor
from camp.datasci import stats

TZ = pytz.timezone('America/Los_Angeles')

BASE_FIELDS = [
    'Monitor ID',
    'Monitor Name',
    'Is Active',
    'Latest Entry',
    'Hours',
]

INTRA_FIELDS = [
    'Intra A Mean',
    'Intra B Mean',
    'Intra Correlation',
    'Intra RPD (%)',
    'Intra Pass',
]

INTER_FIELDS = [
    'Inter Monitor ID',
    'Inter Monitor Name',
    'Inter A Mean',
    'Inter B Mean',
    'Inter Correlation',
    'Inter RPD (%)',
    'Inter Pass',
]

CSV_FIELDS = BASE_FIELDS + INTRA_FIELDS + INTER_FIELDS


@dataclass
class QAResults:
    monitor: Monitor
    series_a: Optional[pd.Series]
    series_b: Optional[pd.Series]
    correlation: Optional[float]
    rpd_pct: Optional[float]
    mean_a: Optional[float]
    mean_b: Optional[float]
    count: int

    @property
    def passed(self) -> bool:
        if self.correlation is None or self.rpd_pct is None:
            return False
        return self.correlation >= 0.98 and self.rpd_pct < 10


def r(n):
    return round(n, 5) if n is not None else ''


class Command(BaseCommand):
    help = 'Analyze a batch of monitors using correlation and RPD only'

    def add_arguments(self, parser):
        parser.add_argument('--group', '-g', required=True, type=str)
        parser.add_argument('--end_date', '-ed', type=str)
        parser.add_argument('--start_date', '-sd', type=str)
        parser.add_argument('--output', '-o', type=str)

    def handle(self, *args, **options):
        lookup = self.get_lookup(**options)
        group = Group.objects.get(name=options['group'])
        monitors = self.get_monitors(group)
        monitor_count = len(monitors)

        self.data = []
        self.rows = []

        for i, monitor in enumerate(monitors):
            print(f'Intra ({i + 1}/{monitor_count}): {monitor.name}')
            qs = PM25.objects.filter(monitor_id=monitor.pk, stage=PM25.Stage.RAW, **lookup)
            df_a = qs.filter(sensor=monitor.ENTRY_CONFIG[PM25]['sensors'][0]).to_dataframe()
            df_b = qs.filter(sensor=monitor.ENTRY_CONFIG[PM25]['sensors'][1]).to_dataframe()
            series_a = df_a['value'] if df_a is not None and 'value' in df_a else None
            series_b = df_b['value'] if df_b is not None and 'value' in df_b else None
            result = self.analyze_data(monitor, series_a, series_b)
            self.data.append({'monitor': monitor, 'intra': result})

        for i, results in enumerate(self.data):
            monitor = results['monitor']
            if not results['intra'].passed:
                continue
            if match := self.find_next_valid_monitor(i):
                print(f'Inter ({i + 1}/{monitor_count}): {monitor.name} vs {match["monitor"].name}')
                result = self.analyze_data(monitor, results['intra'].series_a, match['intra'].series_b)
                results['inter'] = result
                results['inter_monitor'] = match['monitor']
            else:
                results['inter'] = None
                results['inter_monitor'] = None

        self.write_rows(lookup)
        self.save_or_display(options)

    def get_monitors(self, group):
        queryset = group.monitors.all().order_by('name').with_last_entry_timestamp()
        return [
            monitor for monitor in queryset
            if len(monitor.ENTRY_CONFIG.get(PM25, {}).get('sensors', [])) >= 2
        ]

    def analyze_data(self, monitor, a, b) -> QAResults:
        if a is None or a.empty or b is None or b.empty:
            return QAResults(monitor, None, None, None, None, None, None, 0)

        correlation = stats.correlation(a, b, method='pearson')
        rpd_pct = stats.rpd_pairwise(a, b) * 100 if correlation is not None else None

        return QAResults(
            monitor=monitor,
            series_a=a,
            series_b=b,
            correlation=correlation,
            rpd_pct=rpd_pct,
            mean_a=a.mean(),
            mean_b=b.mean(),
            count=min(len(a), len(b)),
        )

    def find_next_valid_monitor(self, i):
        for j, results in enumerate(self.data[i + 1:]):
            if results['intra'].passed:
                return results

        for j, results in enumerate(self.data[:i]):
            if results['intra'].passed:
                return results

    def write_rows(self, lookup):
        for mon in self.data:
            monitor = mon['monitor']
            row = {
                'Monitor ID': monitor.pk,
                'Monitor Name': monitor.name,
                'Is Active': str(monitor.is_active).upper(),
                'Latest Entry': monitor.last_entry_timestamp.astimezone(TZ) if monitor.last_entry_timestamp else '',
                'Hours': mon['intra'].count,
                'Intra RPD (%)': r(mon['intra'].rpd_pct),
                'Intra Correlation': r(mon['intra'].correlation),
                'Intra A Mean': r(mon['intra'].mean_a),
                'Intra B Mean': r(mon['intra'].mean_b),
                'Intra Pass': str(mon['intra'].passed).upper(),
            }

            if mon.get('inter'):
                row.update({
                    'Inter Monitor ID': mon['inter_monitor'].pk,
                    'Inter Monitor Name': mon['inter_monitor'].name,
                    'Inter RPD (%)': r(mon['inter'].rpd_pct),
                    'Inter Correlation': r(mon['inter'].correlation),
                    'Inter A Mean': r(mon['inter'].mean_a),
                    'Inter B Mean': r(mon['inter'].mean_b),
                    'Inter Pass': str(mon['inter'].passed).upper(),
                })
            self.rows.append(row)

        self.header_rows = [
            {'Monitor ID': 'Start Date', 'Monitor Name': lookup['timestamp__range'][0]},
            {'Monitor ID': 'End Date', 'Monitor Name': lookup['timestamp__range'][1]},
            {}
        ]

    def save_or_display(self, options):
        if options['output']:
            with open(options['output'], 'w') as f:
                writer = csv.DictWriter(f, CSV_FIELDS)
                writer.writerows(self.header_rows)
                writer.writeheader()
                writer.writerows(self.rows)
        else:
            pprint(self.rows)

    def get_lookup(self, **options):
        end_date = timezone.now().date()
        if options['end_date']:
            end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
        end_date = timezone.make_aware(datetime.combine(end_date, time.max), TZ)

        if options['start_date']:
            start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
        else:
            start_date = end_date - timedelta(days=30)
        start_date = timezone.make_aware(datetime.combine(start_date, time.min), TZ)

        return {'timestamp__range': (start_date, end_date)}
