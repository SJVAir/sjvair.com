from django.urls import include, re_path, reverse_lazy
from django.contrib.auth import views as auth_views

import vanilla

from . import views

from camp.apps.alerts.views import AlertList, SubscriptionList


auth_urlpatterns = [
    re_path(r'^login/$', auth_views.LoginView.as_view(), {
        # 'authentication_form': forms.AuthenticationForm
    }, name='login'),
    re_path(r'^logout/$', auth_views.LogoutView.as_view(), name='logout'),
    re_path(r'^password/$', auth_views.PasswordChangeView.as_view(
        success_url=reverse_lazy('account:password-change-done'),
    ), name='password-change'),
    re_path(r'^password/done/$', auth_views.PasswordChangeDoneView.as_view(), name='password-change-done'),
    re_path(r'^password/reset/$', auth_views.PasswordResetView.as_view(
        success_url=reverse_lazy('account:password-reset-done'),
    ), name='password-reset'),
    re_path(r'^password/reset/done/$', auth_views.PasswordResetDoneView.as_view(), name='password-reset-done'),
    re_path(r'^reset/(?P<uidb64>[0-9A-Za-z-\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy('account:password-reset-complete'),
        ), name='password-reset-confirm'),
    re_path(r'^reset/done/$', auth_views.PasswordResetCompleteView.as_view(), name='password-reset-complete'),
]

urlpatterns = [
    re_path(r'^$', views.ProfileView.as_view(), name='profile'),
    re_path(r'^alerts/$', AlertList.as_view(), name='alerts'),
    re_path(r'^subscriptions/$', SubscriptionList.as_view(), name='subscriptions'),
    re_path(r'^phone/$', views.SendPhoneVerification.as_view(), name='phone-verify-send'),
    re_path(r'^phone/verify/$', views.SubmitPhoneVerification.as_view(), name='phone-verify-submit'),
    re_path(r'^signup/$', views.SignupView.as_view(), name='signup'),
    re_path(r'^', include(auth_urlpatterns)),
]
