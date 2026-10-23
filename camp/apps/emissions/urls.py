from django.urls import path
from django.views.generic import RedirectView

from camp.apps.emissions import dairy_views, views

urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('about/', views.About.as_view(), name='about'),
    path('map/', views.MapPage.as_view(), name='map'),
    path('oil-gas/', views.OilGasPage.as_view(), name='oil-gas'),
    # A data tab's Table (views.SUBVIEWS): its Summary's URL plus table/.
    path('oil-gas/table/', views.OilGasPage.as_view(subview='table'), name='oil-gas-table'),
    path('methane/', views.MethanePage.as_view(), name='methane'),
    path('methane/table/', views.MethanePage.as_view(subview='table'), name='methane-table'),
    path('near/', views.NearMe.as_view(), name='near-me'),
    path('near/dairies/', dairy_views.NearMeDairies.as_view(), name='near-me-dairies'),
    path('near/dairies/table/', dairy_views.NearMeDairies.as_view(subview='table'), name='near-me-dairies-table'),
    # An area page's tabs (views.AREA_TABS): Overview is the page itself, Dairies its dairy page.
    path('near/facilities/', views.NearMeFacilities.as_view(), name='near-me-facilities'),
    path('near/facilities/table/', views.NearMeFacilities.as_view(subview='table'), name='near-me-facilities-table'),
    path('near/oil-gas/', views.NearMeOilGas.as_view(), name='near-me-oil-gas'),
    path('near/oil-gas/table/', views.NearMeOilGas.as_view(subview='table'), name='near-me-oil-gas-table'),
    path('near/methane/', views.NearMeMethane.as_view(), name='near-me-methane'),
    path('near/methane/table/', views.NearMeMethane.as_view(subview='table'), name='near-me-methane-table'),
    path('near/schools/', views.NearMeSchools.as_view(), name='near-me-schools'),
    path('near/community/', views.CommunityRedirect.as_view(pattern_name='emissions:near-me'), name='near-me-community'),
    path('region/<str:sqid>/', views.RegionRedirect.as_view(), name='region-redirect'),
    # Before the slugged region page: `region/<sqid>/dairies/` isn't a slug.
    path('region/<str:sqid>/dairies/', dairy_views.RegionDairiesRedirect.as_view(), name='region-dairies-redirect'),
    path('region/<str:sqid>/<slug:slug>/', views.RegionPage.as_view(), name='region'),
    path('region/<str:sqid>/<slug:slug>/dairies/', dairy_views.RegionDairies.as_view(), name='region-dairies'),
    path('region/<str:sqid>/<slug:slug>/dairies/table/', dairy_views.RegionDairies.as_view(subview='table'), name='region-dairies-table'),
    path('region/<str:sqid>/<slug:slug>/facilities/', views.RegionFacilities.as_view(), name='region-facilities'),
    path('region/<str:sqid>/<slug:slug>/facilities/table/', views.RegionFacilities.as_view(subview='table'), name='region-facilities-table'),
    path('region/<str:sqid>/<slug:slug>/oil-gas/', views.RegionOilGas.as_view(), name='region-oil-gas'),
    path('region/<str:sqid>/<slug:slug>/oil-gas/table/', views.RegionOilGas.as_view(subview='table'), name='region-oil-gas-table'),
    path('region/<str:sqid>/<slug:slug>/methane/', views.RegionMethane.as_view(), name='region-methane'),
    path('region/<str:sqid>/<slug:slug>/methane/table/', views.RegionMethane.as_view(subview='table'), name='region-methane-table'),
    path('region/<str:sqid>/<slug:slug>/schools/', views.RegionSchools.as_view(), name='region-schools'),
    path('region/<str:sqid>/<slug:slug>/community/', views.CommunityRedirect.as_view(pattern_name='emissions:region'), name='region-community'),
    path('facilities/', views.FacilityList.as_view(), name='facility-list'),
    # Sectors and the Table sit under Facilities; ahead of the facility sqid route so neither is read as one.
    path('facilities/table/', views.FacilityList.as_view(subview='table'), name='facility-list-table'),
    path('facilities/sectors/', views.SectorList.as_view(), name='sector-list'),
    path('facilities/sectors/<slug:sector>/', views.SectorDetail.as_view(), name='sector-detail'),
    path('facilities/<str:sqid>/', views.FacilityRedirect.as_view(), name='facility-redirect'),
    path('facilities/<str:sqid>/<slug:slug>/', views.FacilityDetail.as_view(), name='facility-detail'),
    # Sectors' first home, kept for beta links.
    path('sectors/', RedirectView.as_view(pattern_name='emissions:sector-list', permanent=True, query_string=True)),
    path('sectors/<slug:sector>/', RedirectView.as_view(pattern_name='emissions:sector-detail', permanent=True, query_string=True)),
    path('dairies/', dairy_views.DairyList.as_view(), name='dairy-list'),
    path('dairies/table/', dairy_views.DairyList.as_view(subview='table'), name='dairy-list-table'),
]
