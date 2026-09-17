from django.urls import path

from camp.apps.pesticides import views
from camp.apps.pesticides.models import Chemical, Commodity, Product

urlpatterns = [
    path('', views.Home.as_view(), name='home'),

    path('map/', views.MapPage.as_view(), name='map'),

    path('records/', views.RecordsBrowser.as_view(), name='records'),
    path('sections/<str:sqid>/', views.SectionDetail.as_view(), name='section-detail'),

    path('notices/', views.NoticeList.as_view(), name='notice-list'),
    path('notices/<str:sqid>/', views.NoticeDetail.as_view(), name='notice-detail'),

    path('chemicals/', views.ChemicalList.as_view(), name='chemical-list'),
    path('chemicals/<str:sqid>/', views.ExplorerRedirect.as_view(model=Chemical), name='chemical-redirect'),
    path('chemicals/<str:sqid>/<slug:slug>/', views.ChemicalDetail.as_view(), name='chemical-detail'),

    path('products/', views.ProductList.as_view(), name='product-list'),
    path('products/<str:sqid>/', views.ExplorerRedirect.as_view(model=Product), name='product-redirect'),
    path('products/<str:sqid>/<slug:slug>/', views.ProductDetail.as_view(), name='product-detail'),

    path('commodities/', views.CommodityList.as_view(), name='commodity-list'),
    path('commodities/<str:sqid>/', views.ExplorerRedirect.as_view(model=Commodity), name='commodity-redirect'),
    path('commodities/<str:sqid>/<slug:slug>/', views.CommodityDetail.as_view(), name='commodity-detail'),
]
