from django.urls import path
from .endpoints import *



app_name = "cal_enviro_screen_4"


urlpatterns = [
    path("", CalEnviroAllData.as_view(), name="getAllCalEnviro" ),
    path("<int: pk>", CalEnviroDataByTract.as_view(), name="getByTract"),
    
]

