from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
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
        """Primary table as a list of dicts."""
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'title': self.title,
            'report': self,
            'rows': self.get_rows(),
        }


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
