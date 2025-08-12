import hashlib
import mimetypes
import urllib

from typing import ClassVar, Dict, Iterable, List, Optional, Tuple, Union

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.views import RedirectURLMixin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, resolve_url
from django.template import loader, TemplateDoesNotExist
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import generic
from django.views.decorators.clickjacking import xframe_options_exempt

import vanilla

from django_huey import get_queue
from resticus import http
from resticus.http import JSONResponse
from ua_parser import user_agent_parser

from camp.apps.entries.models import PM25


class CachedEndpointMixin:
    """
    Drop-in mixin for class-based endpoints.

    Features:
    - Response caching keyed by view class + kwargs + querystring (minus control keys).
    - ?_cc=1 -> clear cache key for this specific param set.
    - ?_warm=1 -> recompute and write to cache (prewarm) bypassing cache read.
    - Optional auto-registration for scheduled prewarming.
    """

    # --- Caching knobs ---
    cache_timeout: int = 60

    # --- Prewarm knobs (opt-in) ---
    cache_refresh: bool = False
    # URL name to reverse for prewarming, e.g. 'api:v1:monitors:monitor-list'
    cache_refresh_name: Optional[str] = None
    # One set of kwargs or many; handle both dict or list-of-dicts
    cache_refresh_kwargs: Union[None, Dict, List[Dict]] = None
    # Extra query params to include when prewarming
    cache_refresh_qs: Dict[str, Union[str, List[str]]] = {}

    # --- Internal registry of classes that want refresh ---
    _registry: ClassVar[List[type]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Auto-register classes that opt in for refresh and provided a reverse name
        if getattr(cls, 'cache_refresh', False) and getattr(cls, 'cache_refresh_name', None):
            CachedEndpointMixin._registry.append(cls)

    # ---------- Request handling ----------

    def get(self, request, *args, **kwargs):
        """
        Handles:
          - ?_cc=1: delete cache for this key, then fall through and recompute.
          - ?_warm=1: bypass cache read, recompute, and write to cache.
          - default: read cache -> return if hit -> compute + write if miss.
        """
        cache_key = self.get_view_cache_key()
        clear = '_cc' in request.GET
        warm = '_warm' in request.GET  # bypass read, write fresh

        if clear:
            cache.delete(cache_key)

        if not warm:
            cached = cache.get(cache_key)
            if cached is not None:
                return self._finalize_response(cached, 'HIT')

        status = 'REFRESH' if warm else 'BYPASS' if clear else 'MISS'
        response = super().get(request, *args, **kwargs)
        cache.set(cache_key, response, self.cache_timeout)
        return self._finalize_response(response, status)

    def get_view_cache_key(self) -> str:
        """
        Cache key: module.Class|kw:<sha1(kwargs)>|q:<sha1(query)>
        Drops control params (_cc, _warm) from the query hash.
        """
        key = f'{self.__class__.__module__}.{self.__class__.__name__}'

        if getattr(self, 'kwargs', None):
            kw = urllib.parse.urlencode(self.kwargs, doseq=True)
            key = f'{key}|kw:{hashlib.sha1(kw.encode()).hexdigest()}'

        # Encode the url params into the key
        # TODO: Account for self.filter_class, so that the cache
        # isn't polluted with garbage kwargs.

        params = self.request.GET.copy()
        params.pop('_cc', None)
        params.pop('_warm', None)
        if params:
            qs = urllib.parse.urlencode(params, doseq=True)
            key = f'{key}|q:{hashlib.sha1(qs.encode()).hexdigest()}'

        return key

    def _finalize_response(self, response, cache_status: str):
        if not isinstance(response, (HttpResponse, StreamingHttpResponse)):
            if self.is_streaming():
                response = self.streaming_response(response)
            else:
                response = http.Http200(response)
        response['X-Cache-Status'] = cache_status
        return response

    # ---------- Prewarm helpers ----------

    @classmethod
    def _iter_refresh_targets(cls) -> Iterable[Tuple[type, str, Dict, Dict]]:
        """
        Yields (ViewClass, url_name, kwargs, qs) for each registered target.
        Handles single dict or list-of-dicts for kwargs.
        """
        for view_cls in cls._registry:
            url_name = view_cls.cache_refresh_name
            qs = dict(view_cls.cache_refresh_qs or {})

            kwarg_sets: List[Dict]
            cr_kwargs = view_cls.cache_refresh_kwargs
            if cr_kwargs is None:
                kwarg_sets = [dict()]
            elif isinstance(cr_kwargs, dict):
                kwarg_sets = [cr_kwargs]
            else:
                kwarg_sets = list(cr_kwargs)

            for kw in kwarg_sets:
                yield (view_cls, url_name, kw, qs)

    @classmethod
    def prewarm_view(cls, view_cls: type, url_name: str, kw: Dict, qs: Dict):
        """
        Pre-warm a single view by issuing a GET with ?_warm=1.
        """
        kw = kw or {}
        view = view_cls.as_view()
        factory = RequestFactory()

        base = reverse(url_name, kwargs=kw)
        # ensure _warm=1 is present alongside any configured qs
        qs = dict(qs or {})
        qs['_warm'] = '1'
        url = f'{base}?{urllib.parse.urlencode(qs, doseq=True)}'

        request = factory.get(url)
        response = view(request, **kw)
        return response

    @classmethod
    def prewarm_all_registered(cls) -> List[Tuple[type, int]]:
        """
        Pre-warm all registered endpoints; returns [(ViewClass, status_code)].
        """
        results: List[Tuple[type, int]] = []
        for view_cls, url_name, kw, qs in cls._iter_refresh_targets():
            resp = cls.prewarm_view(view_cls, url_name, kw, qs)
            if resp.status_code == 500:
                return resp
            results.append((view_cls, getattr(resp, 'status_code', 0)))
        return results


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


class GetTheApp(vanilla.TemplateView):
    template_name = 'pages/app.html'

    def get(self, request):
        user_agent = user_agent_parser.Parse(request.META.get('HTTP_USER_AGENT', ''))
        if user_agent['os']['family'] == 'Android':
            return redirect(settings.APP_URL_ANDROID)

        if user_agent['device']['family'] == 'iPhone':
            return redirect(settings.APP_URL_IPHONE)

        if user_agent['device']['family'] == 'iPad':
            return redirect(settings.APP_URL_IPAD)

        return super().get(request)


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
            """, [PM25._meta.db_table])
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
