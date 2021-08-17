from django.conf.urls import include, url
from django.urls import reverse_lazy
from django.contrib.auth import views as auth_views

import vanilla

from . import views

from camp.apps.alerts.views import AlertList, SubscriptionList


auth_urlpatterns = [
    url(r'^login/$', auth_views.LoginView.as_view(), {
        # 'authentication_form': forms.AuthenticationForm
    }, name='login'),
    url(r'^logout/$', auth_views.LogoutView.as_view(), name='logout'),
    url(r'^password/$', auth_views.PasswordChangeView.as_view(
        success_url=reverse_lazy('account:password-change-done'),
    ), name='password-change'),
    url(r'^password/done/$', auth_views.PasswordChangeDoneView.as_view(), name='password-change-done'),
    url(r'^password/reset/$', auth_views.PasswordResetView.as_view(
        success_url=reverse_lazy('account:password-reset-done'),
    ), name='password-reset'),
    url(r'^password/reset/done/$', auth_views.PasswordResetDoneView.as_view(), name='password-reset-done'),
    url(r'^reset/(?P<uidb64>[0-9A-Za-z-\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy('account:password-reset-complete'),
        ), name='password-reset-confirm'),
    url(r'^reset/done/$', auth_views.PasswordResetCompleteView.as_view(), name='password-reset-complete'),
]

urlpatterns = [
    url(r'^$', views.ProfileView.as_view(), name='profile'),
    url(r'^alerts/$', AlertList.as_view(), name='alerts'),
    url(r'^subscriptions/$', SubscriptionList.as_view(), name='subscriptions'),
    url(r'^verify-phone/$', views.PhoneVerify.as_view(), name='phone-verify'),
    url(r'^signup/$', views.SignupView.as_view(), name='signup'),
    url(r'^', include(auth_urlpatterns)),
]
