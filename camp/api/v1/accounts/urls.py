from django.urls import path, include

from . import endpoints

app_name = 'accounts'

urlpatterns = [
    path("", endpoints.UserDetail.as_view(), name="user-detail"),
    path("login/", endpoints.LoginEndpoint.as_view(), name="login"),
    path("register/", endpoints.RegisterEndpoint.as_view(), name="register"),

    path('phone/', endpoints.SendPhoneVerificationEndpoint.as_view(), name='phone-verify-send'),
    path('phone/verify/', endpoints.ConfirmPhoneVerificationEndpoint.as_view(), name='phone-verify-confirm'),

    path("password-reset/", endpoints.PasswordResetEndpoint.as_view(), name="password-reset"),
    path(
        "password-reset/<uidb64>/<token>/",
        endpoints.PasswordResetConfirmEndpoint.as_view(),
        name="password-reset-confirm",
    ),
]
