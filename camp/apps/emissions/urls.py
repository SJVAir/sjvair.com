from django.urls import path

from camp.apps.emissions import views

urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('about/', views.About.as_view(), name='about'),
    path('map/', views.MapPage.as_view(), name='map'),
    path('facilities/', views.FacilityList.as_view(), name='facility-list'),
    path('facilities/<str:sqid>/', views.FacilityRedirect.as_view(), name='facility-redirect'),
    path('facilities/<str:sqid>/<slug:slug>/', views.FacilityDetail.as_view(), name='facility-detail'),
    path('sectors/', views.SectorList.as_view(), name='sector-list'),
    path('sectors/<slug:sector>/', views.SectorDetail.as_view(), name='sector-detail'),
]
