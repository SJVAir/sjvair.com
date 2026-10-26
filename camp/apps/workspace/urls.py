from django.urls import path, re_path

from .views import WorkspaceManifest, WorkspacePage

urlpatterns = [
    # Before the catch-all page route, which would match it too
    path('workspace/manifest.webmanifest', WorkspaceManifest.as_view(), name='workspace-manifest'),
    re_path(r'^workspace(?:/.*)?$', WorkspacePage.as_view(), name='workspace'),
]
