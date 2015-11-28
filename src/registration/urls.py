# coding=utf-8
"""
URLconf for django-inspectional-registration
"""
__author__ = 'Alisue <lambdalisue@hashnote.net>'
from registration.compat import url
from registration.compat import patterns

from registration.views import RegistrationView
from registration.views import RegistrationClosedView
from registration.views import RegistrationCompleteView
from registration.views import ActivationView
from registration.views import ActivationCompleteView

urlpatterns = patterns('',
    url(r'^activate/complete/$', ActivationCompleteView.as_view(),
        name='registration_activation_complete'),
    url(r'^activate/(?P<activation_key>\w+)/$', ActivationView.as_view(),
        name='registration_activate'),
    url(r'^register/$', RegistrationView.as_view(),
        name='registration_register'),
    url(r'^register/closed/$', RegistrationClosedView.as_view(),
        name='registration_disallowed'),
    url(r'^register/complete/$', RegistrationCompleteView.as_view(),
        name='registration_complete'),
)

# django.contrib.auth
from registration.conf import settings
from django.contrib.auth import views as auth_views
if settings.REGISTRATION_DJANGO_AUTH_URLS_ENABLE:
    prefix = settings.REGISTRATION_DJANGO_AUTH_URL_NAMES_PREFIX
    suffix = settings.REGISTRATION_DJANGO_AUTH_URL_NAMES_SUFFIX

    import django
    if django.VERSION >= (1, 6):
        uidb = r"(?P<uidb64>[0-9A-Za-z_\-]+)"
        token = r"(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})"
        password_reset_confirm_rule = (
            r"^password/reset/confirm/%s/%s/$" % (uidb, token)
        )
    else:
        uidb = r"(?P<uidb36>[0-9A-Za-z]+)"
        token = r"(?P<token>.+)"
        password_reset_confirm_rule = (
            r"^password/reset/confirm/%s-%s/$" % (uidb, token)
        )

    
