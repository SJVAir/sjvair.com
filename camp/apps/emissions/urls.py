from django.urls import path
from django.views.generic import RedirectView

from camp.apps.emissions import dairy_views, views

urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('about/', views.About.as_view(), name='about'),
    path('map/', views.MapPage.as_view(), name='map'),
    path('oil-gas/', views.OilGasPage.as_view(), name='oil-gas'),
    path('near/', views.NearMe.as_view(), name='near-me'),
    path('near/dairies/', dairy_views.NearMeDairies.as_view(), name='near-me-dairies'),
    # An area page's tabs (views.AREA_TABS): Overview is the page itself, Dairies its dairy page.
    path('near/facilities/', views.NearMeFacilities.as_view(), name='near-me-facilities'),
    path('near/oil-gas/', views.NearMeOilGas.as_view(), name='near-me-oil-gas'),
    path('near/schools/', views.NearMeSchools.as_view(), name='near-me-schools'),
    path('near/community/', views.NearMeCommunity.as_view(), name='near-me-community'),
    path('region/<str:sqid>/', views.RegionRedirect.as_view(), name='region-redirect'),
    # Before the slugged region page: `region/<sqid>/dairies/` isn't a slug.
    path('region/<str:sqid>/dairies/', dairy_views.RegionDairiesRedirect.as_view(), name='region-dairies-redirect'),
    path('region/<str:sqid>/<slug:slug>/', views.RegionPage.as_view(), name='region'),
    path('region/<str:sqid>/<slug:slug>/dairies/', dairy_views.RegionDairies.as_view(), name='region-dairies'),
    path('region/<str:sqid>/<slug:slug>/facilities/', views.RegionFacilities.as_view(), name='region-facilities'),
    path('region/<str:sqid>/<slug:slug>/oil-gas/', views.RegionOilGas.as_view(), name='region-oil-gas'),
    path('region/<str:sqid>/<slug:slug>/schools/', views.RegionSchools.as_view(), name='region-schools'),
    path('region/<str:sqid>/<slug:slug>/community/', views.RegionCommunity.as_view(), name='region-community'),
    path('facilities/', views.FacilityList.as_view(), name='facility-list'),
    # Sectors sit under Facilities; ahead of the facility sqid route so 'sectors' isn't read as one.
    path('facilities/sectors/', views.SectorList.as_view(), name='sector-list'),
    path('facilities/sectors/<slug:sector>/', views.SectorDetail.as_view(), name='sector-detail'),
    path('facilities/<str:sqid>/', views.FacilityRedirect.as_view(), name='facility-redirect'),
    path('facilities/<str:sqid>/<slug:slug>/', views.FacilityDetail.as_view(), name='facility-detail'),
    # Sectors' first home, kept for beta links.
    path('sectors/', RedirectView.as_view(pattern_name='emissions:sector-list', permanent=True, query_string=True)),
    path('sectors/<slug:sector>/', RedirectView.as_view(pattern_name='emissions:sector-detail', permanent=True, query_string=True)),
    path('dairies/', dairy_views.DairyList.as_view(), name='dairy-list'),
]
