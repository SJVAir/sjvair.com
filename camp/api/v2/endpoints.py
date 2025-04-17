import calendar
import csv

from django.forms import forms
from django.http import HttpResponse
from django.utils import timezone

from resticus import generics
from resticus.http import Http400


class CurrentTime(generics.Endpoint):
    def get(self, request):
        timestamp = timezone.now().utctimetuple()
        return calendar.timegm(timestamp)


class CSVExport(generics.ListEndpoint):
    filter_class = None
    model = None

    columns = []
    headers = {}
    filename = "export.csv"

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{self.get_filename()}"'

        writer = csv.writer(response)
        writer.writerow(self.get_header_row())
        for instance in queryset.iterator():
            writer.writerow(self.get_row(instance))

        return response

    def get_filename(self):
        return self.filename.format(data=self.form.cleaned_data, view=self)

    def get_header_row(self):
        return [self.headers.get(name, name) for name, func in self.columns]

    def get_row(self, instance):
        row = []
        for name, func in self.columns:
            value = func(instance)
            row.append(value if value is not None else '')
        return row


class FormEndpoint(generics.Endpoint):
    """
    A simple endpoint that works with Django forms.
    """

    form_class = forms.Form

    def get_form_class(self):
        return self.form_class

    def get_form(self, data=None, files=None, **kwargs):
        form_class = self.get_form_class()
        return form_class(data=data, files=files, **kwargs)

    def post(self, request, *args, **kwargs):
        form = self.get_form(data=request.data, files=request.FILES)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        raise NotImplementedError()

    def form_invalid(self, form):
        return Http400({"errors": form.errors.get_json_data()})
