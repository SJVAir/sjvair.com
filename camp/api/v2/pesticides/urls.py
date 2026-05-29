from django.urls import path

from . import endpoints

app_name = 'pesticides'

urlpatterns = [
    path('summary/<str:region_id>/', endpoints.PesticideSummary.as_view(), name='summary'),
    path('commodities/', endpoints.CommodityList.as_view(), name='commodity-list'),
    path('commodities/<str:commodity_id>/', endpoints.CommodityDetail.as_view(), name='commodity-detail'),
    path('chemicals/', endpoints.ChemicalList.as_view(), name='chemical-list'),
    path('chemicals/<str:chemical_id>/', endpoints.ChemicalDetail.as_view(), name='chemical-detail'),
    path('products/', endpoints.ProductList.as_view(), name='product-list'),
    path('products/<str:product_id>/', endpoints.ProductDetail.as_view(), name='product-detail'),
    path('use/', endpoints.PesticideUseList.as_view(), name='use-list'),
    path('use/<str:use_id>/', endpoints.PesticideUseDetail.as_view(), name='use-detail'),
    path('notice/', endpoints.PesticideNoticeList.as_view(), name='notice-list'),
    path('notice/<str:notice_id>/', endpoints.PesticideNoticeDetail.as_view(), name='notice-detail'),
]
