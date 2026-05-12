from django.urls import path

from . import endpoints

app_name = 'pesticides'

urlpatterns = [
    path('commodities/', endpoints.CommodityList.as_view(), name='commodity-list'),
    path('commodities/<str:sqid>/', endpoints.CommodityDetail.as_view(), name='commodity-detail'),
    path('chemicals/', endpoints.ChemicalList.as_view(), name='chemical-list'),
    path('chemicals/<str:sqid>/', endpoints.ChemicalDetail.as_view(), name='chemical-detail'),
    path('products/', endpoints.ProductList.as_view(), name='product-list'),
    path('products/<str:sqid>/', endpoints.ProductDetail.as_view(), name='product-detail'),
    path('use/', endpoints.PesticideUseList.as_view(), name='use-list'),
    path('use/<str:sqid>/', endpoints.PesticideUseDetail.as_view(), name='use-detail'),
    path('notice/', endpoints.PesticideNoticeList.as_view(), name='notice-list'),
    path('notice/<str:sqid>/', endpoints.PesticideNoticeDetail.as_view(), name='notice-detail'),
]
