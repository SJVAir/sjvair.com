from django.urls import path
from .endpoints import *

app_name = "SmokeTest"


#TODO ADD TO PREEVIOUS URLS.PY TO EXTEND THE URL + CHANGE THESE URLS TO MAKE SENSE ex: camp/api/hms_smoke/ongoing... 

urlpatterns = [
    path("hms_smoke/ongoing", OngoingSmokeView.as_view(), name="ongoing_smoke" ),
    path("hms_smoke/ongoing/density", OngoingSmokeDensityView.as_view(), name="ongoing_smoke_density"),
    path("hms_smoke/last", LatestObeservableSmokeView.as_view(), name = "last_observable_smoke"),
    path("hms_smoke/last/density", LatestObeservableSmokeDensityView.as_view(), name="last_observable_smoke_density"),
    path("hms_smoke/<str:pk>", SelectSmokeView.as_view(), name="smoke_by_id")

]