from unittest.mock import patch

import pytest

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

from camp.apps.accounts import sms_keywords, tasks
from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.alerts.notifications import get_recipients
from camp.apps.monitors.purpleair.models import PurpleAir


class KeywordTests(TestCase):
    def test_normalize(self):
        assert sms_keywords.normalize('  stop!! ') == 'STOP'
        assert sms_keywords.normalize('Stop   All') == 'STOP ALL'
        assert sms_keywords.normalize('Desuscribír.') == 'DESUSCRIBIR'

    def test_english_keywords_are_twilio_enforced(self):
        for body in ['STOP', 'stop', 'Unsubscribe', 'cancel', 'END', 'quit', 'STOPALL', 'optout', 'revoke']:
            assert sms_keywords.classify(body) == sms_keywords.TWILIO_OPT_OUT_KIND, body

    def test_stop_all_is_ours_because_twilio_only_blocks_single_words(self):
        for body in ['STOP ALL', 'stop all', 'Stop   All!']:
            assert sms_keywords.classify(body) == sms_keywords.OPT_OUT_KIND, body

    def test_leading_and_trailing_punctuation_is_ignored(self):
        assert sms_keywords.normalize('¡Alto!') == 'ALTO'
        assert sms_keywords.normalize('¿Parar?') == 'PARAR'
        assert sms_keywords.normalize('  "stop"... ') == 'STOP'
        for body in ['¡Alto!', '¿Parar?', '!!Detener']:
            assert sms_keywords.classify(body) == sms_keywords.OPT_OUT_KIND, body

    def test_other_language_keywords(self):
        for body in ['parar', 'Para', 'ALTO', 'detener', 'Cancelar', 'baja', 'desuscribir', 'tigil', 'Hinto', 'itigil', 'tseem', 'nres']:
            assert sms_keywords.classify(body) == sms_keywords.OPT_OUT_KIND, body

    def test_opt_in_keywords(self):
        for body in ['START', 'unstop', 'Yes']:
            assert sms_keywords.classify(body) == sms_keywords.TWILIO_OPT_IN_KIND, body

    def test_keyword_inside_a_sentence_is_not_an_opt_out(self):
        for body in ['Please stop by', 'stop sending at night', 'no pares', 'hello', '']:
            assert sms_keywords.classify(body) is None, body

    def test_opt_out_reply_by_language(self):
        assert sms_keywords.get_opt_out_reply('es').startswith('SJVAir: Ya no recibira')
        assert sms_keywords.get_opt_out_reply('en').startswith("SJVAir: You won't get")
        assert sms_keywords.get_opt_out_reply('hmn') == sms_keywords.get_opt_out_reply('en')
        assert sms_keywords.get_opt_out_reply('tl') == sms_keywords.get_opt_out_reply('en')
        for language in ['en', 'es', 'tl', 'hmn']:
            assert sms_keywords.get_opt_out_reply(language).isascii()

    @override_settings(TWILIO_PHONE_NUMBERS=['+15595550100'])
    def test_opt_in_instructions_name_the_number(self):
        assert sms_keywords.get_opt_in_instructions() == (
            'Text START to (559) 555-0100 to allow texts from SJVAir again, then request a new code.'
        )

    @override_settings(TWILIO_PHONE_NUMBERS=[''])
    def test_opt_in_instructions_fall_back_without_a_number(self):
        assert sms_keywords.get_opt_in_instructions() == (
            'Text START to our number to allow texts from SJVAir again, then request a new code.'
        )

    @override_settings(TWILIO_PHONE_NUMBERS=[])
    def test_opt_in_instructions_fall_back_with_no_numbers(self):
        assert 'our number' in sms_keywords.get_opt_in_instructions()

    def test_opt_in_reply_by_language(self):
        assert sms_keywords.get_opt_in_reply('es').startswith('SJVAir: Para volver a recibir')
        assert sms_keywords.get_opt_in_reply('en').startswith('SJVAir: To get air quality alerts again')
        assert sms_keywords.get_opt_in_reply('tl') == sms_keywords.get_opt_in_reply('en')
        assert sms_keywords.get_opt_in_reply('hmn') == sms_keywords.get_opt_in_reply('en')
        for language in ['en', 'es', 'tl', 'hmn']:
            assert sms_keywords.get_opt_in_reply(language).isascii()


class UserSMSStateTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')

    def test_defaults_to_not_blocked(self):
        assert self.user.sms_blocked is False

    def test_opt_out_without_block_only_unverifies(self):
        self.user.opt_out_of_sms(blocked=False)
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    def test_opt_out_with_block(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    def test_clear_sms_block_leaves_phone_unverified(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.clear_sms_block()
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False
        assert self.user.phone_verified is False

    def test_phone_change_resets_block(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.phone = '559-555-0123'
        self.user.save()
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False

    def test_phone_change_resets_block_with_update_fields(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.phone = '559-555-0123'
        self.user.save(update_fields=['phone'])
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False

    def test_phone_change_unverifies(self):
        assert self.user.phone_verified is True
        self.user.phone = '559-555-0123'
        self.user.save()
        self.user.refresh_from_db()
        assert self.user.phone_verified is False

    def test_phone_change_unverifies_with_update_fields(self):
        self.user.phone = '559-555-0123'
        self.user.save(update_fields=['phone'])
        self.user.refresh_from_db()
        assert self.user.phone_verified is False

    def test_save_without_phone_change_keeps_verified(self):
        self.user.full_name = 'New Name'
        self.user.save()
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_new_user_creation_is_unaffected(self):
        user = User.objects.create_user('new@sjvair.com', 'letmein1', full_name='New', phone='559-555-0188', phone_verified=True)
        user.refresh_from_db()
        assert user.phone_verified is True

    def test_save_without_phone_change_keeps_block(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.full_name = 'New Name'
        self.user.save()
        self.user.refresh_from_db()
        assert self.user.sms_blocked is True

    def test_opt_out_discards_pending_verification_code(self):
        cache.set(self.user.phone_verification_code_key, '123456', 600)
        self.user.opt_out_of_sms(blocked=False)
        assert cache.get(self.user.phone_verification_code_key) is None

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_send_sms_skips_blocked_user(self, mock_send):
        self.user.opt_out_of_sms(blocked=True)
        assert self.user.send_sms('hello', verify=False) is False
        mock_send.assert_not_called()

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_send_sms_still_sends_to_verified_user(self, mock_send):
        self.user.send_sms('hello')
        mock_send.assert_called_once()


def opted_out_error():
    return TwilioRestException(
        status=400, uri='https://api.twilio.com/fake',
        msg='Attempt to send to unsubscribed recipient', code=sms_keywords.OPTED_OUT_ERROR,
    )


class SendSMSOptOutTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_opted_out_error_blocks_the_user(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = opted_out_error()

        tasks.send_sms_message.call_local(self.user.phone, 'hello')

        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_opted_out_error_for_unknown_number_is_logged(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = opted_out_error()

        with self.assertLogs('camp.apps.accounts.tasks', level='WARNING') as logs:
            tasks.send_sms_message.call_local('+15595550199', 'hello')

        assert '5595550199' not in logs.output[0]
        assert '0199' in logs.output[0]
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_other_twilio_errors_still_raise(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = TwilioRestException(
            status=400, uri='https://api.twilio.com/fake', msg='Invalid number', code=21211,
        )
        with pytest.raises(TwilioRestException):
            tasks.send_sms_message.call_local(self.user.phone, 'hello')


class WebPhoneChangeTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')
        self.client.force_login(self.user)

    def tearDown(self):
        cache.clear()
        return super().tearDown()

    def change_phone(self, phone='559-555-0198'):
        return self.client.post(reverse('account:profile'), {
            'full_name': self.user.full_name,
            'email': self.user.email,
            'phone': phone,
            'language': self.user.language,
        })

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_profile_phone_change_unverifies_and_redirects_to_verify(self, mock_send):
        assert self.user.phone_verified is True
        response = self.change_phone()

        assert response.status_code == 302
        assert response['Location'] == reverse('account:phone-verify-send')
        user = User.objects.get(pk=self.user.pk)
        assert str(user.phone) == '+15595550198'
        assert user.phone_verified is False
        mock_send.assert_not_called()

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_profile_phone_change_then_verify_send_sends_one_code(self, mock_send):
        self.change_phone()
        send_url = reverse('account:phone-verify-send')
        first = self.client.post(send_url, {})
        second = self.client.post(send_url, {})

        assert first.status_code == 302
        assert second.status_code == 200
        assert 'recently been sent' in second.content.decode()
        assert mock_send.call_count == 1

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_changing_phone_between_sends_does_not_bypass_rate_limit(self, mock_send):
        self.user.phone_verified = False
        self.user.save()
        send_url = reverse('account:phone-verify-send')
        self.client.post(send_url, {})
        self.change_phone('559-555-0197')
        response = self.client.post(send_url, {})

        assert response.status_code == 200
        assert 'recently been sent' in response.content.decode()
        assert mock_send.call_count == 1


class InboundSMSTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')
        self.url = reverse('twilio-inbound-sms')

    def post(self, body, sender='+15595555555', signed=True):
        data = {'From': sender, 'Body': body}
        signature = 'not-a-real-signature'
        if signed:
            signature = RequestValidator(settings.TWILIO_AUTH_TOKEN).compute_signature(f'http://testserver{self.url}', data)
        return self.client.post(self.url, data, HTTP_X_TWILIO_SIGNATURE=signature)

    def test_invalid_signature_is_rejected(self):
        response = self.post('STOP', signed=False)
        assert response.status_code == 403
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    @override_settings(TWILIO_AUTH_TOKEN='')
    def test_empty_auth_token_rejects_even_a_forged_signature(self):
        data = {'From': '+15595555555', 'Body': 'STOP'}
        signature = RequestValidator('').compute_signature(f'http://testserver{self.url}', data)
        response = self.client.post(self.url, data, HTTP_X_TWILIO_SIGNATURE=signature)
        assert response.status_code == 403
        self.user.refresh_from_db()
        assert self.user.phone_verified is True
        assert self.user.sms_blocked is False

    def test_english_stop_unverifies_and_blocks_without_reply(self):
        response = self.post('stop')
        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/xml')
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    def test_stop_all_unverifies_with_confirmation_but_does_not_block(self):
        response = self.post('Stop All')
        assert b"You won&apos;t get" in response.content or b"You won't get" in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    def test_spanish_keyword_unverifies_and_replies_in_spanish(self):
        self.user.language = 'es'
        self.user.save()
        response = self.post('Parar')
        assert response.status_code == 200
        assert b'Ya no recibira' in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    def test_hmong_keyword_replies_in_english(self):
        self.user.language = 'hmn'
        self.user.save()
        response = self.post('nres')
        assert b"You won&apos;t get" in response.content or b"You won't get" in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False

    def test_start_clears_block_but_keeps_phone_unverified(self):
        self.user.opt_out_of_sms(blocked=True)
        response = self.post('START')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False
        assert self.user.phone_verified is False

    def test_start_from_unverified_user_replies_with_how_to_resume(self):
        self.user.opt_out_of_sms(blocked=True)
        response = self.post('START')
        assert b'<Message>' in response.content
        assert b'To get air quality alerts again' in response.content

    def test_start_reply_is_spanish_for_spanish_user(self):
        self.user.language = 'es'
        self.user.save()
        self.user.opt_out_of_sms(blocked=True)
        response = self.post('START')
        assert b'Para volver a recibir alertas' in response.content

    def test_start_from_verified_user_has_no_reply(self):
        response = self.post('START')
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_unstop_clears_block(self):
        self.user.opt_out_of_sms(blocked=True)
        response = self.post('UNSTOP')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False

    def test_tagalog_keyword_unverifies_and_replies_in_english(self):
        self.user.language = 'tl'
        self.user.save()
        response = self.post('tigil')
        assert b'get any more texts' in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_web_verification_send_is_refused_for_blocked_user(self, mock_send):
        self.user.opt_out_of_sms(blocked=True)
        self.client.force_login(self.user)
        response = self.client.post(reverse('account:phone-verify-send'), {})
        assert response.status_code == 200
        assert 'Text START' in response.content.decode()
        mock_send.assert_not_called()

    def test_ordinary_text_changes_nothing(self):
        response = self.post('Please stop by the office')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_unknown_sender_returns_empty_response(self):
        response = self.post('STOP', sender='+15595550199')
        assert response.status_code == 200
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_missing_sender_returns_empty_response(self):
        response = self.post('STOP', sender='')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_opted_out_user_is_excluded_from_alert_recipients(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        Subscription.objects.create(user=self.user, monitor=monitor, level='unhealthy_sensitive')
        self.post('STOP')
        assert not get_recipients(monitor).filter(user=self.user).exists()

    def test_blocked_user_is_excluded_from_alert_recipients(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        Subscription.objects.create(user=self.user, monitor=monitor, level='unhealthy_sensitive')
        User.objects.filter(pk=self.user.pk).update(sms_blocked=True)
        assert not get_recipients(monitor).filter(user=self.user).exists()
