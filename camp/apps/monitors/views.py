import vanilla

from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt

from .models import Monitor


@method_decorator(xframe_options_exempt, name='dispatch')
class MonitorWidget(vanilla.DetailView):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'
    model = Monitor
    template_name = 'monitors/widget.html'


class MonitorWidgetTest(vanilla.TemplateView):
    template_name = 'monitors/widget-test.html'
