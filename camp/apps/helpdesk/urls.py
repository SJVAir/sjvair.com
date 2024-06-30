from django.urls import path

from .views import Home, CategoryDetail, ArticleDetail, Glossary

urlpatterns = [
    path('', Home.as_view(), name='home'),
    path('category/<str:sqid>/<str:slug>/', CategoryDetail.as_view(), name='category-detail'),
    path('category/<str:sqid>/<str:slug>/', ArticleDetail.as_view(), name='article-detail'),
    path('glossary', Glossary.as_view(), name='glossary'),
]
