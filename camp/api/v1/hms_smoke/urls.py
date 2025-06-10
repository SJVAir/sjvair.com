from django.urls import path
from . import endpoints

app_name = "hms_smoke"

urlpatterns = [
    path('', endpoints.SmokeList.as_view(), name='smoke-list'),
    path('<smoke_id>/', endpoints.SmokeDetail.as_view(), name='smoke-detail'),
    path('ongoing/', endpoints.SmokeListOngoing.as_view(), name='smoke-ongoing'),
    
]


# urlpatterns = [
#     path("ongoing", OngoingSmokeView.as_view(), name="ongoing_smoke" ),
#     path("ongoing/density/", OngoingSmokeDensityView.as_view(), name="ongoing_smoke_density"),
#     path("last", LatestObeservableSmokeView.as_view(), name = "last_observable_smoke"),
#     path("last/density/", LatestObeservableSmokeDensityView.as_view(), name="last_observable_smoke_density"),
#     path("<str:pk>", SelectSmokeView.as_view(), name="smoke_by_id"),
#     path("", SmokeByTimestamp.as_view(), name="all_by_timestamp"),
#     #EXPECTS UTC TIME INPUT
#     path("time/", StartEndFilter.as_view(), name="start_end_filter")

# ]