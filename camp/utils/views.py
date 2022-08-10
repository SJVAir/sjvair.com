import hashlib
import urllib

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.views import SuccessURLAllowedHostsMixin
from django.db import connection
from django.http import Http404
from django.shortcuts import redirect, resolve_url
from django.template import loader, TemplateDoesNotExist
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import is_safe_url
from django.views import generic

from huey.contrib.djhuey import HUEY
from resticus.http import JSONResponse

from camp.apps.monitors.models import Entry


def get_view_cache_key(view, query=None):
    '''
        Given an instance of a class-based view, return
        a suitable key for caching the response.
    '''
    key = f'{view.__class__.__module__}.{view.__class__.__name__}'

    # Encode the kwargs into the key
    if view.kwargs:
        encoded = hashlib.sha1(urllib.parse.urlencode(query).encode()).hexdigest()
        key = f'{key}|kw:{encoded}'

    # Encode the url params into the key
    # TODO: Account for view.filter_class, so that the cache
    # isn't polluted with garbage kwargs.
    params = view.request.GET.copy()
    params.pop('_cc', None)
    if params:
        encoded = hashlib.sha1(urllib.parse.urlencode(params, doseq=True).encode()).hexdigest()
        key = f'{key}|q:{encoded}'

    print(key, len(key))
    return key


class RedirectViewMixin(SuccessURLAllowedHostsMixin):
    redirect_field_name = 'next'

    def get_redirect_url(self):
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name, None)
        )

        if redirect_to is None:
            redirect_to = resolve_url(self.success_url)

        url_is_safe = is_safe_url(
            url=redirect_to,
            allowed_hosts=self.get_success_url_allowed_hosts(),
            require_https=self.request.is_secure(),
        )
        return redirect_to if url_is_safe else ''

    def get_success_url(self):
        return self.get_redirect_url()

    def get_context_data(self, **kwargs):
        context = super(RedirectViewMixin, self).get_context_data(**kwargs)
        context[self.redirect_field_name] = self.get_redirect_url()
        return context


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
