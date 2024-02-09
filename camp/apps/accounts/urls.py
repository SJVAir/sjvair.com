from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

import vanilla

from . import forms, views

from camp.apps.alerts.views import AlertList, SubscriptionList

urlpatterns = [
    # Login and signup
    path('login/', auth_views.LoginView.as_view(
        authentication_form=forms.AuthenticationForm,
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('signup/', views.SignupView.as_view(), name='signup'),

    # Account management
    path('', views.ProfileView.as_view(), name='profile'),
    path('alerts/', AlertList.as_view(), name='alerts'),
    path('subscriptions/', SubscriptionList.as_view(), name='subscriptions'),
    path('phone/', views.SendPhoneVerification.as_view(), name='phone-verify-send'),
    path('phone/verify/', views.SubmitPhoneVerification.as_view(), name='phone-verify-submit'),
    path('password/', auth_views.PasswordChangeView.as_view(
        success_url=reverse_lazy('account:password-change-done'),
    ), name='password-change'),
    path('password/done/', auth_views.PasswordChangeDoneView.as_view(), name='password-change-done'),

    # Password reset
    path('password/reset/', views.PasswordReset.as_view(), name='password-reset'),
    path('password/reset/confirm/', views.PasswordResetConfirm.as_view(), name='password-reset-confirm'),
    path('password/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password-reset-complete'),
]
