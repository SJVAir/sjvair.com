import csv

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator

import vanilla


REPORTS = []


def register(cls):
    """Class decorator: add a report to the index and URL registry."""
    REPORTS.append(cls)
    return cls


@method_decorator(staff_member_required, name='dispatch')
class BaseReport(vanilla.TemplateView):
    slug = None
    title = None
    description = ''
    template_name = None

    def get_rows(self):
        """Primary table as a list of dicts. Keys become CSV columns."""
        raise NotImplementedError

    def get_csv_columns(self, rows):
        return list(rows[0].keys()) if rows else []

    def get_context_data(self, **kwargs):
        csv_query = self.request.GET.copy()
        csv_query['format'] = 'csv'
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'title': self.title,
            'report': self,
            'rows': self.get_rows(),
            'csv_query': csv_query.urlencode(),
        }

    def render_to_response(self, context):
        if self.request.GET.get('format') == 'csv':
            return self.render_csv(context['rows'])
        return super().render_to_response(context)

    def render_csv(self, rows):
        today = timezone.localdate().isoformat()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{self.slug}-{today}.csv"'
        writer = csv.DictWriter(response, fieldnames=self.get_csv_columns(rows), extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
        return response


@method_decorator(staff_member_required, name='dispatch')
class ReportIndex(vanilla.TemplateView):
    template_name = 'admin/reports/index.html'

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'title': 'Reports',
            'reports': REPORTS,
        }
