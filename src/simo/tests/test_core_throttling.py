from unittest import mock

from django.test import SimpleTestCase, override_settings


class ThrottlingUnitTests(SimpleTestCase):
    def test_subject_uses_user_id_for_authenticated_and_xff_for_anonymous(self):
        from simo.core.throttling import _subject

        req_anon = mock.Mock()
        req_anon.user = mock.Mock(is_authenticated=False)
        req_anon.META = {'REMOTE_ADDR': '10.0.0.1', 'HTTP_X_FORWARDED_FOR': '1.2.3.4, 5.6.7.8'}
        self.assertEqual(_subject(req_anon), 'ip:1.2.3.4')

        req_auth = mock.Mock()
        req_auth.user = mock.Mock(is_authenticated=True, id=123)
        req_auth.META = {'REMOTE_ADDR': '10.0.0.1', 'HTTP_X_FORWARDED_FOR': '1.2.3.4'}
        self.assertEqual(_subject(req_auth), 'u:123')

    @override_settings(
        SIMO_THROTTLE={
            'ban_seconds': 7,
            'global_rules': [{'window_seconds': 10, 'limit_authenticated': 2, 'limit_anonymous': 1}],
            'default_rules': [{'window_seconds': 10, 'limit_authenticated': 2, 'limit_anonymous': 1}],
        }
    )
    def test_check_throttle_bans_after_exceeding_limit(self):
        from django.core.cache import cache
        from simo.core.throttling import check_throttle, SimpleRequest

        cache.clear()

        req = SimpleRequest(user=mock.Mock(is_authenticated=True, id=1), meta={'REMOTE_ADDR': '10.0.0.1'})
        with mock.patch('simo.core.throttling.time.time', autospec=True, return_value=100):
            self.assertEqual(check_throttle(request=req, scope='x'), 0)
            self.assertEqual(check_throttle(request=req, scope='x'), 0)
            wait = check_throttle(request=req, scope='x')

        self.assertEqual(wait, 7)

    def test_check_throttle_fails_open_when_cache_is_unavailable(self):
        from simo.core.throttling import check_throttle, SimpleRequest

        req = SimpleRequest(user=mock.Mock(is_authenticated=False), meta={'REMOTE_ADDR': '10.0.0.1'})

        with (
            mock.patch('simo.core.throttling.cache.add', autospec=True, side_effect=Exception('down')),
            mock.patch('simo.core.throttling.cache.incr', autospec=True, side_effect=Exception('down')),
            mock.patch('simo.core.throttling.cache.get', autospec=True, side_effect=Exception('down')),
        ):
            self.assertEqual(check_throttle(request=req, scope='x'), 0)

