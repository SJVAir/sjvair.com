import os

from django.conf import settings
from django.http import Http404, JsonResponse
from django.templatetags.static import static
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView, View

from .csp import build_policy, policy_header_name
from .identity import workspace_identity
from .manifest import load_manifest


def is_shared_path(path):
    return path == '/workspace/shared' or path.startswith('/workspace/shared/')


@method_decorator([ensure_csrf_cookie, never_cache], name='dispatch')
class WorkspacePage(TemplateView):
    """
    Every /workspace/* URL renders the dashboard; its own router takes it
    from there. No trailing-slash redirect: the dashboard's routes have none.
    """
    template_name = 'workspace/index.html'
    http_method_names = ['get', 'head', 'options']

    def get_context_data(self, **kwargs):
        return {'workspace_identity': workspace_identity(self.request.user)}

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if is_shared_path(request.path):
            response['X-Robots-Tag'] = 'noindex'
        policy = build_policy(settings.STATIC_URL, settings.WORKSPACE_CSP_REPORT_URI)
        response[policy_header_name(settings.WORKSPACE_CSP_ENFORCE)] = policy
        return response


@method_decorator(never_cache, name='dispatch')
class WorkspaceManifest(View):
    """The web app manifest, at /workspace/manifest.webmanifest (same-origin)."""
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        path = os.path.join(settings.WORKSPACE_DIST_DIR, 'manifest.webmanifest')
        data = load_manifest(path, static('workspace/'))
        if data is None:
            raise Http404()
        return JsonResponse(data, content_type='application/manifest+json')
