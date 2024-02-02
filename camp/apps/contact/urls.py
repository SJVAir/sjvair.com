from django.urls import include, path

from . import views

urlpatterns = [
    path('', views.ContactFormView.as_view(), name='form'),
    path('done/', views.ContactDoneView.as_view(), name='done'),
]
