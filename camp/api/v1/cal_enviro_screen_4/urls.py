from django.urls import path
from .endpoints import *



app_name = "cal_enviro_screen_4"


urlpatterns = [
    path("", getCalData )
]

