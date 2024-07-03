from django.urls import path

from .views import Home, CategoryDetail, ArticleDetail, Glossary, Search

urlpatterns = [
    path('', Home.as_view(), name='home'),
    path('category/<str:sqid>/<str:slug>/', CategoryDetail.as_view(), name='category-detail'),
    path('article/<str:sqid>/<str:slug>/', ArticleDetail.as_view(), name='article-detail'),
    path('glossary/', Glossary.as_view(), name='glossary'),
    path('search/', Search.as_view(), name='search'),
]
