import calendar
import csv

from django.conf import settings
from django.forms import forms
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

from django_huey import get_queue

from resticus import generics
from resticus.http import Http400, JSONResponse
from resticus.serializers import serialize


class CurrentTime(generics.Endpoint):
    def get(self, request):
        timestamp = timezone.now().utctimetuple()
        return calendar.timegm(timestamp)


class TaskStatus(generics.Endpoint):
    """
    Gets status of specific Huey task
    """

    def get(self, request, task_id):
        queue = get_queue(settings.DJANGO_HUEY.get('default'))
        result = serialize(queue.result(task_id, preserve=True))
        return JSONResponse({'data': result})


class CSVExport(generics.ListEndpoint):
    filter_class = None
    model = None

    columns = []
    headers = {}
    filename = "export.csv"

    class Echo:
        """
        An object that implements just the write method of the file-like interface.
        """

        def write(self, value):
            """Write the value by returning it, instead of storing in a buffer."""
            return value

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)

        writer = csv.writer(self.Echo())
        response = self.get_response(
            (writer.writerow(row) for row in self.get_rows(queryset)),
            content_type='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="{self.get_filename()}"'
            }
        )
        return response

    def get_response(self, iterable, *args, **kwargs):
        if self.is_streaming():
            return StreamingHttpResponse(iterable, *args, **kwargs)
        return HttpResponse(''.join(iterable), *args, **kwargs)

    def get_rows(self, queryset):
        yield self.get_header_row()
        for instance in queryset.iterator():
            yield self.get_row(instance)

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

    def process_form(self, *args, **kwargs):
        form = self.get_form(*args, **kwargs)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def post(self, request, *args, **kwargs):
        return self.process_form(data=request.data, files=request.FILES)

    def form_valid(self, form):
        raise NotImplementedError()

    def form_invalid(self, form):
        return Http400({"errors": form.errors.get_json_data()})
