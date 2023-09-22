import hashlib
import mimetypes
import urllib

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.views import RedirectURLMixin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, resolve_url
from django.template import loader, TemplateDoesNotExist
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import generic
from django.views.decorators.clickjacking import xframe_options_exempt

from django_huey import get_queue
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
    return key


class RedirectViewMixin(RedirectURLMixin):
    redirect_field_name = 'next'

    def get_redirect_url(self):
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name, None)
        )

        if redirect_to is None:
            redirect_to = resolve_url(self.success_url)

        url_is_safe = url_has_allowed_host_and_scheme(
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
    def get_template_names(self):
        # Do we have a template name override?
        if self.template_name is not None:
            return [self.template_name]

        # No override, derive the template from the URL path.
        path = self.request.path.strip('/')
        possible_templates = ['pages/{0}.html'.format(path or 'index')]
        if path:
            possible_templates.append('pages/{0}/index.html'.format(path))
        return possible_templates

    def get(self, request, *args, **kwargs):
        # Enforce a trailing slash.
        if not request.path.endswith('/'):
            return redirect('{0}/'.format(request.path), permanent=True)

        # Template names beginning with an underscore are not allowed.
        if request.path.strip('/').split('/')[-1].startswith('_'):
            raise Http404

        # If URL path doesn't exist as a template, return 404.
        try:
            loader.select_template(self.get_template_names())
        except TemplateDoesNotExist:
            raise Http404

        return self.render_to_response({})


@method_decorator(xframe_options_exempt, name='dispatch')
class RenderStatic(generic.View):
    static_file = None

    def get(self, request, *args, **kwargs):
        content_type = mimetypes.guess_type(self.static_file)[0]
        file = staticfiles_storage.open(self.static_file)
        response = HttpResponse(file.read(), content_type=content_type)
        return response


@method_decorator(staff_member_required, name='dispatch')
class AdminStats(generic.View):
    def get(self, request):
        return JSONResponse({
            'timestamp': timezone.now(),
            'queue_size': {key: get_queue(key).pending_count() for key in settings.DJANGO_HUEY['queues']},
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
    def post(self, request, key):
        try:
            queue = get_queue(key)
        except KeyError:
            messages.error(request, f'Invalid queue: {key}')
            return redirect('admin:index')

        queue.flush()
        messages.success(request, f'The {key} task queue has been flushed.')
        return redirect('admin:index')
