import calendar
import csv

from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.utils import timezone

from resticus.exceptions import ValidationError
from resticus.views import Endpoint

from camp.utils.forms import DateRangeForm


class CurrentTime(Endpoint):
    def get(self, request):
        timestamp = timezone.now().utctimetuple()
        return calendar.timegm(timestamp)


class CSVExport(Endpoint):
    form_class = DateRangeForm
    model = None
    columns = []
    filename = "export_{data[start_date]}_{data[end_date]}.csv"

    def get_form(self, data=None):
        return self.form_class(data)

    def get_queryset(self, queryset=None):
        if queryset is None:
            if self.model is None:
                raise ImproperlyConfigured(
                    f'{self.__class__.__name__} '
                    'must define the model attribute or '
                    'implement get_queryset()'
                )
            queryset = self.model.objects.all()
        return queryset

    def filter_queryset(self, queryset, form):
        return queryset.filter(timestamp__range=(
            form.cleaned_data['start_date'],
            form.cleaned_data['end_date'] + timedelta(days=1)
        ))

    def get(self, request, *args, **kwargs):
        self.form = self.get_form(request.GET)
        if self.form.is_valid():
            return self.form_valid(self.form)
        return self.form_invalid(self.form)

    def form_valid(self, form):
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset, form)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{self.get_filename()}"'

        writer = csv.writer(response)
        writer.writerow(self.get_header_row())
        for instance in queryset.iterator():
            writer.writerow(self.get_row(instance))

        return response

    def form_invalid(self, form):
        raise ValidationError(form=form)

    def get_filename(self):
        return self.filename.format(data=self.form.cleaned_data, view=self)

    def get_header_row(self):
        return [name for name, func in self.columns]

    def get_row(self, instance):
        print(instance.pk)
        return [func(instance) for name, func in self.columns]

