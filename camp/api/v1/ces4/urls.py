from django.urls import path

from .endpoints import Ces4List, Ces4Detail


app_name = "ces4"

urlpatterns = [
    path("", Ces4List.as_view(), name="ces4-list" ),
    path("<int:pk>", Ces4Detail.as_view(), name="ces4-detail"), 
]

