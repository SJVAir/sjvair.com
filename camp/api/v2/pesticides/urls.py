from django.urls import path

from . import endpoints, sections

app_name = 'pesticides'

urlpatterns = [
    path('counties/', sections.CountyList.as_view(), name='county-list'),
    path('townships/', sections.TownshipList.as_view(), name='township-list'),
    path('sections/', sections.SectionList.as_view(), name='section-list'),
    path('sections/<str:section_id>/', sections.SectionDetail.as_view(), name='section-detail'),
    path('region/<str:region_id>/summary/', endpoints.PesticideRegionSummary.as_view(), name='region-summary'),
    path('region/<str:region_id>/notice/', endpoints.PesticideRegionNotice.as_view(), name='region-notice'),
    path('region/<str:region_id>/use/', endpoints.PesticideRegionUse.as_view(), name='region-use'),
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
    path('notices/active/', sections.ActiveNoticeList.as_view(), name='notice-active'),
]
