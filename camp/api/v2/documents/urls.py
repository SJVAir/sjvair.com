from django.urls import path

from . import endpoints

app_name = 'documents'

# Fixed paths (profile/, export/, shared/<token>/...) are registered before <id>/.
urlpatterns = [
    path('', endpoints.DocumentList.as_view(), name='list'),
    path('<str:id>/', endpoints.DocumentDetail.as_view(), name='detail'),
]
