from django.urls import re_path

from .views import WorkspacePage

urlpatterns = [
    re_path(r'^workspace(?:/.*)?$', WorkspacePage.as_view(), name='workspace'),
]
