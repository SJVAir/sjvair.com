import csv
import io

from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.forms import PurpleAirAddForm
from camp.apps.monitors.linreg import linear_regression, RegressionResults


@dataclass
class AnalysisResults(RegressionResults):
    monitor: PurpleAir
    std_a: float
    std_b: float
    mean_a: float
    mean_b: float

    @property
    def std_diff(self):
        return self.std_a - self.std_b

    @property
    def mean_diff(self):
        return self.mean_a - self.mean_b


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        flagged = []
        failed = []

        end_date = timezone.now()
        start_date = end_date - timedelta(days=7)

        # monitors = PurpleAir.objects.filter(name__icontains='hackerspace')
        monitors = PurpleAir.objects.all()
        for monitor in monitors:
            queryset = monitor.entries.filter(timestamp__date__range=(start_date, end_date))
            a_qs = queryset.filter(sensor='a')
            b_qs = queryset.filter(sensor='b')

            is_failed = False
            is_flagged = False

            results = linear_regression(a_qs, b_qs, ['pm25'])
            if results is None:
                is_failed = True
                reason = 'Unknown'

                missing = []
                if not a_qs.exists():
                    missing.append('A')
                if not b_qs.exists():
                    missing.append('B')

                if missing:
                    reason = f"No data for {' and '.join(missing)}"

                failed.append({'monitor': monitor, 'reason': reason})

            else:
                results = AnalysisResults(
                    monitor=monitor,
                    std_a=results.df.endog_pm25.std(),
                    std_b=results.df.pm25.std(),
                    mean_a=results.df.endog_pm25.mean(),
                    mean_b=results.df.pm25.mean(),
                    **{key: getattr(results, key) for key in results.__annotations__}
                )

                is_flagged = any((results.r2 < 0.90, abs(results.std_diff) >= 5))

                if is_flagged:
                    flagged.append(results)

            print('x' if is_failed else '+' if is_flagged else ' ', monitor.name)

        report = self.build_report(start_date, end_date, flagged, failed)

        with open('PA-AvB.csv', 'w') as f:
            f.write(report)

    def build_report(self, start_date, end_date, flagged, failed):
        fields = [
            'id', 'name', 'county', 'location', 'hours', 'r2',
            'std_a', 'std_b', 'std_diff',
            'mean_a', 'mean_b', 'mean_diff',
        ]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields)

        writer.writerows([
            {'id': 'Start Date', 'name': start_date},
            {'id': 'End Date', 'name': end_date},
            {},
        ])

        writer.writeheader()

        for results in flagged:
            writer.writerow({
                'id': results.monitor.pk,
                'name': results.monitor.name,
                'county': results.monitor.county,
                'location': results.monitor.location,
                'hours': len(results.df),
                'r2': results.r2,

                'std_a': results.std_a,
                'std_b': results.std_b,
                'std_diff': results.std_diff,

                'mean_a': results.mean_a,
                'mean_b': results.mean_b,
                'mean_diff': results.mean_diff,
            })

        writer.writerow({})
        writer.writerow({'id': 'UNABLE TO PROCESS'})
        writer.writerow({
            'id': 'id',
            'name': 'name',
            'county': 'county',
            'location': 'location',
            'hours': 'status',
            'r2': 'reason',
        })
        for results in failed:
            writer.writerow({
                'id': results['monitor'].pk,
                'name': results['monitor'].name,
                'county': results['monitor'].county,
                'location': results['monitor'].location,
                'hours': 'active' if results['monitor'].is_active else 'inactive',
                'r2': results['reason'],
            })

        return stream.getvalue()
