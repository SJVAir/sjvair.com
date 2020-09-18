from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import connection
from django.http import Http404
from django.shortcuts import redirect
from django.template import loader, TemplateDoesNotExist
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import generic

from huey.contrib.djhuey import HUEY
from resticus.http import JSONResponse

from camp.apps.monitors.models import Entry


class PageTemplate(generic.TemplateView):
    def get(self, request, *args, **kwargs):
        # Enforce a trailing slash.
        if not request.path.endswith('/'):
            return redirect('{0}/'.format(request.path), permanent=True)

        # Template names beginning with an underscore are not allowed.
        if request.path.strip('/').split('/')[-1].startswith('_'):
            raise Http404

        # Set the template_name based on the URL path and raise a 404 if it doesn't exist.
        self.template_name = 'pages/{0}.html'.format(request.path.strip('/') or 'index')

        try:
            loader.get_template(self.template_name)
        except TemplateDoesNotExist:
            raise Http404

        return self.render_to_response({})


@method_decorator(staff_member_required, name='dispatch')
class AdminStats(generic.View):
    def get(self, request):
        return JSONResponse({
            'timestamp': timezone.now(),
            'queue_size': HUEY.pending_count(),
            'entry_count': self.get_entry_count(),
        })

    def get_entry_count(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT reltuples::BIGINT
                    AS estimate
                FROM pg_class
                WHERE relname=%s;
            """, [Entry._meta.db_table])
            return cursor.fetchone()[0]

@method_decorator(staff_member_required, name='dispatch')
class FlushQueue(generic.View):
    def post(self, request):
        HUEY.flush()
        messages.success(request, 'The task queue has been flushed.')
        return redirect('admin:index')
