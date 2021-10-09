import calendar
import csv

from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured
from django.forms import forms
from django.http import HttpResponse
from django.utils import timezone

from PIL import Image, ImageDraw
from resticus import generics
from resticus.exceptions import ValidationError
from resticus.http import Http400

from camp.utils.forms import DateRangeForm
from camp.utils.polygon import compute_regular_polygon
from .forms import MarkerForm


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


class MapMarker(generics.Endpoint):
    form_class = MarkerForm

    def get_form(self):
        return self.form_class(self.request.GET)

    def get(self, request):
        data = self.get_form().get_data()

        im = Image.new('RGBA', (data['size'], data['size']), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)

        xy = (0, 0, data['size'], data['size'])
        if data['shape'] == 'polygon':
            xy = [
                (xy[0] + xy[2]) / 2,
                (xy[1] + xy[3]) / 2
            ]
            draw.polygon(
                compute_regular_polygon((xy, xy[0] - 1), n_sides=data['sides']),
                fill=f"#{data['fill_color']}",
                outline=f"#{data['border_color']}" if data['border_size'] else None,
            )
        else:
            shape = {
                'circle': draw.ellipse,
                'square': draw.rectangle,
            }.get(data['shape'])

            shape(xy,
                fill=f"#{data['fill_color']}",
                outline=f"#{data['border_color']}",
                width=data['border_size'],
            )

        response = HttpResponse(content_type='image/png')
        im.save(response, 'PNG')
        return response


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
