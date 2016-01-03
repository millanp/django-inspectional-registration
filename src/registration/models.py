# coding=utf-8
"""
Models of django-inspectional-registration

This is a modification of django-registration_ ``models.py``
The original code is written by James Bennett

.. _django-registration: https://bitbucket.org/ubernostrum/django-registration


Original License::

    Copyright (c) 2007-2011, James Bennett
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are
    met:

        * Redistributions of source code must retain the above copyright
        notice, this list of conditions and the following disclaimer.
        * Redistributions in binary form must reproduce the above
        copyright notice, this list of conditions and the following
        disclaimer in the documentation and/or other materials provided
        with the distribution.
        * Neither the name of the author nor the names of other
        contributors may be used to endorse or promote products derived
        from this software without specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
    LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
    A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
    OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
    SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
    LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
    DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
    THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
__author__ = 'Alisue <lambdalisue@hashnote.net>'
__all__ = (
    'ActivationForm', 'RegistrationForm', 
    'RegistrationFormNoFreeEmail',
    'RegistrationFormTermsOfService',
    'RegistrationFormUniqueEmail',
)
import re
import datetime

from django.db import models
from django.contrib.sites.models import Site
from django.template.loader import render_to_string
from django.core.exceptions import ObjectDoesNotExist
from django.utils.text import ugettext_lazy as _

from registration.conf import settings
from registration.compat import get_user_model
from registration.compat import user_model_label
from registration.compat import datetime_now
from registration.utils import generate_activation_key
from registration.utils import generate_random_password
from registration.utils import send_mail
from registration.supplements import get_supplement_class
from registration.compat import transaction_atomic

from logging import getLogger
logger = getLogger(__name__)

SHA1_RE = re.compile(r'^[a-f0-9]{40}$')


class RegistrationManager(models.Manager):
    """Custom manager for the ``RegistrationProfile`` model.

    The methods defined here provide shortcuts for account registration,
    registration acceptance, registration rejection and account activation
    (including generation and emailing of activation keys), and for cleaning out
    expired/rejected inactive accounts.

    """
    @transaction_atomic
    def register(self, username, email, site, send_email=True):
        """register new user with ``username`` and ``email``

        Create a new, inactive ``User``, generate a ``RegistrationProfile``
        and email notification to the ``User``, returning the new ``User``.

        By default, a registration email will be sent to the new user. To
        disable this, pass ``send_email=False``. A registration email will be
        generated by ``registration/registration_email.txt`` and
        ``registration/registration_email_subject.txt``.

        The user created by this method has no usable password and it will
        be set after activation.

        This method is transactional. Thus if some exception has occur in this
        method, the newly created user will be rollbacked.

        """
        User = get_user_model()
        new_user = User.objects.create_user(username, email, 'password')
        new_user.set_unusable_password()
        new_user.is_active = False
        new_user.save()

        profile = self.create(user=new_user)

        if send_email:
            profile.send_registration_email(site)

        return new_user

    @transaction_atomic
    def accept_registration(self, profile, site,
                            send_email=True, message=None, force=False):
        """accept account registration of ``profile``

        Accept account registration and email activation url to the ``User``,
        returning accepted ``User``. 

        By default, an acceptance email will be sent to the new user. To
        disable this, pass ``send_email=False``. An acceptance email will be
        generated by ``registration/acceptance_email.txt`` and
        ``registration/acceptance_email_subject.txt``.

        This method **DOES** works even after ``reject_registration`` has called
        (this mean the account registration has rejected previously) because 
        rejecting user by mistake may occur in this real world :-p If the account 
        registration has already accepted, returning will be ``None``

        The ``date_joined`` attribute of ``User`` updated to now in this
        method and ``activation_key`` of ``RegistrationProfile`` will
        be generated.

        """
        # rejected -> accepted is allowed
        if force or profile.status in ('untreated', 'rejected'):
            if force:
                # removing activation_key will force to create a new one
                profile.activation_key = None
            profile.status = 'accepted'
            profile.save()

            if send_email:
                profile.send_acceptance_email(site, message=message)

            return profile.user
        return None

    @transaction_atomic
    def reject_registration(self, profile, site, send_email=True, message=None):
        """reject account registration of ``profile``

        Reject account registration and email rejection to the ``User``,
        returning accepted ``User``. 

        By default, an rejection email will be sent to the new user. To
        disable this, pass ``send_email=False``. An rejection email will be
        generated by ``registration/rejection_email.txt`` and
        ``registration/rejection_email_subject.txt``.

        This method **DOES NOT** works after ``accept_registration`` has called
        (this mean the account registration has accepted previously).
        If the account registration has already accepted/rejected, returning 
        will be ``None``

        """
        # accepted -> rejected is not allowed
        if profile.status == 'untreated':
            profile.status = 'rejected'
            profile.save()

            if send_email:
                profile.send_rejection_email(site, message=message)

            return profile.user
        return None

    @transaction_atomic
    def activate_user(self, activation_key, site, password=None,
                      send_email=True, message=None, no_profile_delete=False):
        """activate account with ``activation_key`` and ``password``

        Activate account and email notification to the ``User``, returning 
        activated ``User``, ``password`` and ``is_generated``. 

        By default, an activation email will be sent to the new user. To
        disable this, pass ``send_email=False``. An activation email will be
        generated by ``registration/activation_email.txt`` and
        ``registration/activation_email_subject.txt``.

        This method **DOES NOT** works if the account registration has not been
        accepted. You must accept the account registration before activate the
        account. Returning will be ``None`` if the account registration has not
        accepted or activation key has expired.

        if passed ``password`` is ``None`` then random password will be generated
        and set to the ``User``. If the password is generated, ``is_generated``
        will be ``True``

        Use returning value like::

            activated = RegistrationProfile.objects.activate_user(activation_key)

            if activated:
                # Activation has success
                user, password, is_generated = activated
                # user -- a ``User`` instance of account
                # password -- a raw password of ``User``
                # is_generated -- ``True`` if the password is generated

        When activation has success, the ``RegistrationProfile`` of the ``User``
        will be deleted from database because the profile is no longer required.

        """
        try:
            profile = self.get(_status='accepted', activation_key=activation_key)
        except self.model.DoesNotExist:
            return None
        if not profile.activation_key_expired():
            is_generated = password is None
            password = password or generate_random_password(
                    length=settings.REGISTRATION_DEFAULT_PASSWORD_LENGTH)
            user = profile.user
            user.set_password(password)
            user.is_active = True
            user.save()

            if send_email:
                profile.send_activation_email(site, password,
                                              is_generated, message=message)

            if not no_profile_delete:
                # the profile is no longer required
                profile.delete()
            return user, password, is_generated
        return None

    @transaction_atomic
    def delete_expired_users(self):
        """delete expired users from database

        Remove expired instance of ``RegistrationProfile`` and their associated
        ``User``.

        Accounts to be deleted are identified by searching for instance of
        ``RegistrationProfile`` with expired activation keys, and then checking
        to see if their associated ``User`` instance have the field ``is_active``
        set to ``False`` (it is for compatibility of django-registration); any
        ``User`` who is both inactive and has an expired activation key will be
        deleted.

        It is recommended that this method be executed regularly as part of your
        routine site maintenance; this application provides a custom management
        command which will call this method, accessible as 
        ``manage.py cleanupexpiredregistration`` (for just expired users) or
        ``manage.py cleanupregistration`` (for expired or rejected users).

        Reqularly clearing out accounts which have never been activated servers
        two useful purposes:

        1.  It alleviates the ocasional need to reset a ``RegistrationProfile``
            and/or re-send an activation email when a user does not receive or
            does not act upon the initial activation email; since the account
            will be deleted, the user will be able to simply re-register and
            receive a new activation key (if accepted).

        2.  It prevents the possibility of a malicious user registering one or
            more accounts and never activating them (thus denying the use of
            those username to anyone else); since those accounts will be deleted,
            the username will become available for use again.

        If you have a troublesome ``User`` and wish to disable their account while
        keeping it in the database, simply delete the associated 
        ``RegistrationProfile``; an inactive ``User`` which does not have an 
        associated ``RegistrationProfile`` will be deleted.

        """
        for profile in self.all():
            if profile.activation_key_expired():
                try:
                    user = profile.user
                    if not user.is_active:
                        user.delete()
                        profile.delete()    # just in case
                except ObjectDoesNotExist:
                    profile.delete()

    @transaction_atomic
    def delete_rejected_users(self):
        """delete rejected users from database

        Remove rejected instance of ``RegistrationProfile`` and their associated
        ``User``.

        Accounts to be deleted are identified by searching for instance of
        ``RegistrationProfile`` with rejected status, and then checking
        to see if their associated ``User`` instance have the field ``is_active``
        set to ``False`` (it is for compatibility of django-registration); any
        ``User`` who is both inactive and its registration has been rejected will
        be deleted.

        It is recommended that this method be executed regularly as part of your
        routine site maintenance; this application provides a custom management
        command which will call this method, accessible as 
        ``manage.py cleanuprejectedregistration`` (for just rejected users) or
        ``manage.py cleanupregistration`` (for expired or rejected users).

        Reqularly clearing out accounts which have never been activated servers
        two useful purposes:

        1.  It alleviates the ocasional need to reset a ``RegistrationProfile``
            and/or re-send an activation email when a user does not receive or
            does not act upon the initial activation email; since the account
            will be deleted, the user will be able to simply re-register and
            receive a new activation key (if accepted).

        2.  It prevents the possibility of a malicious user registering one or
            more accounts and never activating them (thus denying the use of
            those username to anyone else); since those accounts will be deleted,
            the username will become available for use again.

        If you have a troublesome ``User`` and wish to disable their account while
        keeping it in the database, simply delete the associated 
        ``RegistrationProfile``; an inactive ``User`` which does not have an 
        associated ``RegistrationProfile`` will be deleted.

        """
        for profile in self.all():
            if profile.status == 'rejected':
                try:
                    user = profile.user
                    if not user.is_active:
                        user.delete()
                        profile.delete() # just in case
                except ObjectDoesNotExist:
                    profile.delete()


class RegistrationProfile(models.Model):
    """Registration profile model class

    A simple profile which stores an activation key and inspection status for use
    during user account registration/inspection.

    Generally, you will not want to interact directly with instances of this model;
    the provided manager includes method for creating, accepting, rejecting and
    activating, as well as for cleaning out accounts which have never been activated
    or its registration has been rejected.

    While it is possible to use this model as the value of the ``AUTH_PROFILE_MODEL``
    setting, it's not recommended that you do so. This model's sole purpose is to
    store data temporarily during account registration, inspection and activation.

    """
    STATUS_LIST = (
        ('untreated', _('Approval needed')),
        ('accepted', _('Waiting for user confirmation')),
        ('rejected', _('Rejected')),
    )
    user = models.OneToOneField(user_model_label, verbose_name=_('user'), 
                                related_name='registration_profile',
                                editable=False)
    _status = models.CharField(_('status'), max_length=10, db_column='status',
                              choices=STATUS_LIST, default='untreated',
                              editable=False)
    activation_key = models.CharField(_('activation key'), max_length=40,
                                      null=True, default=None, editable=False)

    objects = RegistrationManager()

    class Meta:
        verbose_name = _('registration profile')
        verbose_name_plural = _('registration profiles')
        permissions = (
                ('accept_registration', 'Can accept registration'),
                ('reject_registration', 'Can reject registration'),
                ('activate_user', 'Can activate user in admin site'),
            )

    def _get_supplement_class(self):
        """get supplement class of this registration"""
        return get_supplement_class()
    supplement_class = property(_get_supplement_class)

    def _get_supplement(self):
        """get supplement information of this registration"""
        return getattr(self, '_supplement', None)
    supplement = property(_get_supplement)

    def _get_status(self):
        """get inspection status of this profile

        this will return 'expired' for profile which is accepted but
        activation key has expired

        """
        if self.activation_key_expired():
            return 'expired'
        return self._status
    def _set_status(self, value):
        """set inspection status of this profile

        Setting status to ``'accepted'`` will generate activation key
        and update ``date_joined`` attribute to now of associated ``User``

        Setting status not to ``'accepted'`` will remove activation key
        of this profile.

        """
        self._status = value
        # Automatically generate activation key for accepted profile
        if value == 'accepted' and not self.activation_key:
            username = self.user.username
            self.activation_key = generate_activation_key(username)
            # update user's date_joined
            self.user.date_joined = datetime_now()
            self.user.save()
        elif value != 'accepted' and self.activation_key:
            self.activation_key = None
    status = property(_get_status, _set_status)

    def get_status_display(self):
        """get human readable status"""
        sl = list(self.STATUS_LIST)
        sl.append(('expired', _('Activation key has expired')))
        sl = dict(sl)
        return sl.get(self.status)
    get_status_display.short_description = _("status")

    def __unicode__(self):
        return u"Registration information for %s" % self.user

    def __str__(self):
        return "Registration information for %s" % self.user

    def activation_key_expired(self):
        """get whether the activation key of this profile has expired

        Determine whether this ``RegistrationProfiel``'s activation key has
        expired, returning a boolean -- ``True`` if the key has expired.

        Key expiration is determined by a two-step process:

        1.  If the inspection status is not ``'accepted'``, the key is set to
            ``None``. In this case, this method returns ``False`` because these
            profiles are not treated yet or rejected by inspector.

        2.  Otherwise, the date the user signed up (which automatically updated
            in registration acceptance) is incremented by the number of days 
            specified in the setting ``ACCOUNT_ACTIVATION_DAYS`` (which should
            be the number of days after acceptance during which a user is allowed
            to activate their account); if the result is less than or equal to
            the current date, the key has expired and this method return ``True``.

        """
        if self._status != 'accepted':
            return False
        expiration_date = datetime.timedelta(
                days=settings.ACCOUNT_ACTIVATION_DAYS)
        expired = self.user.date_joined + expiration_date <= datetime_now()
        return expired
    activation_key_expired.boolean = True

    def _send_email(self, site, action, extra_context=None):
        context = {
                'user': self.user,
                'site': site,
            }
        if action != 'activation':
            # the profile was deleted in 'activation' action
            context['profile'] = self

        if extra_context:
            context.update(extra_context)

        subject = render_to_string(
                'registration/%s_email_subject.txt' % action, context)
        subject = ''.join(subject.splitlines())
        message = render_to_string(
                'registration/%s_email.txt' % action, context)

        send_mail(subject, message,
                  settings.DEFAULT_FROM_EMAIL, [self.user.email])

    def send_registration_email(self, site):
        """send registration email to the user associated with this profile

        Send a registration email to the ``User`` associated with this
        ``RegistrationProfile``.

        The registration email will make use of two templates:

        ``registration/registration_email_subject.txt``
            This template will be used for the subject line of the email. Because
            it is used as the subject line of an email, this template's output
            **must** be only a single line of text; output longer than one line
            will be forcibly joined into only a single line.

        ``registration/registration_email.txt``
            This template will be used for the body of the email

        These templates will each receive the following context variables:

        ``site``
            An object representing the site on which the user registered;this is
            an instance of ``django.contrib.sites.models.Site`` or
            ``django.contrib.sites.models.RequestSite``

        ``user``
            A ``User`` instance of the registration.

        ``profile``
            A ``RegistrationProfile`` instance of the registration

        """
        self._send_email(site, 'registration')

    def send_acceptance_email(self, site, message=None):
        """send acceptance email to the user associated with this profile

        Send an acceptance email to the ``User`` associated with this
        ``RegistrationProfile``.

        The acceptance email will make use of two templates:

        ``registration/acceptance_email_subject.txt``
            This template will be used for the subject line of the email. Because
            it is used as the subject line of an email, this template's output
            **must** be only a single line of text; output longer than one line
            will be forcibly joined into only a single line.

        ``registration/acceptance_email.txt``
            This template will be used for the body of the email

        These templates will each receive the following context variables:

        ``site``
            An object representing the site on which the user registered;this is
            an instance of ``django.contrib.sites.models.Site`` or
            ``django.contrib.sites.models.RequestSite``

        ``user``
            A ``User`` instance of the registration.

        ``profile``
            A ``RegistrationProfile`` instance of the registration

        ``activation_key``
            The activation key for tne new account. Use following code to get
            activation url in the email body::

                {% load url from future %}
                http://{{ site.domain }}
                {% url 'registration_activate' activation_key=activation_key %}

        ``expiration_days``
            The number of days remaining during which the account may be activated.

        ``message``
            A message from inspector. In default template, it is not shown.

        """
        extra_context = {
                'activation_key': self.activation_key,
                'expiration_days': settings.ACCOUNT_ACTIVATION_DAYS,
                'message': message,
            }
        self._send_email(site, 'acceptance', extra_context)

    def send_rejection_email(self, site, message=None):
        """send rejection email to the user associated with this profile

        Send a rejection email to the ``User`` associated with this
        ``RegistrationProfile``.

        The rejection email will make use of two templates:

        ``registration/rejection_email_subject.txt``
            This template will be used for the subject line of the email. Because
            it is used as the subject line of an email, this template's output
            **must** be only a single line of text; output longer than one line
            will be forcibly joined into only a single line.

        ``registration/rejection_email.txt``
            This template will be used for the body of the email

        These templates will each receive the following context variables:

        ``site``
            An object representing the site on which the user registered;this is
            an instance of ``django.contrib.sites.models.Site`` or
            ``django.contrib.sites.models.RequestSite``

        ``user``
            A ``User`` instance of the registration.

        ``profile``
            A ``RegistrationProfile`` instance of the registration

        ``message``
            A message from inspector. In default template, it is used for explain
            why the account registration has been rejected.

        """
        extra_context = {
                'message': message,
            }
        self._send_email(site, 'rejection', extra_context)

    def send_activation_email(self, site, password=None, is_generated=False,
                              message=None):
        """send activation email to the user associated with this profile

        Send a activation email to the ``User`` associated with this
        ``RegistrationProfile``.

        The activation email will make use of two templates:

        ``registration/activation_email_subject.txt``
            This template will be used for the subject line of the email. Because
            it is used as the subject line of an email, this template's output
            **must** be only a single line of text; output longer than one line
            will be forcibly joined into only a single line.

        ``registration/activation_email.txt``
            This template will be used for the body of the email

        These templates will each receive the following context variables:

        ``site``
            An object representing the site on which the user registered;this is
            an instance of ``django.contrib.sites.models.Site`` or
            ``django.contrib.sites.models.RequestSite``

        ``user``
            A ``User`` instance of the registration.

        ``password``
            A raw password of ``User``. Use this to tell user to them password
            when the password is generated

        ``is_generated``
            A boolean -- ``True`` if the password is generated. Don't forget to
            tell user to them password when the password is generated

        ``message``
            A message from inspector. In default template, it is not shown.

        """
        extra_context = {
                'password': password,
                'is_generated': is_generated,
                'message': message,
            }
        self._send_email(site, 'activation', extra_context)
