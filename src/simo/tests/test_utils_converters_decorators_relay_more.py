from __future__ import annotations

from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase


class TestInputToMeters(SimpleTestCase):
    pass


def _mk_input_to_meters_case(raw: str, expected: float):
    from simo.core.utils.converters import input_to_meters

    def _test(self):
        self.assertAlmostEqual(input_to_meters(raw), expected)

    return _test


_UNIT_ALIASES = {
    'm': 1.0,
    'meter': 1.0,
    'meters': 1.0,
    'ft': 0.3048,
    'foot': 0.3048,
    'feet': 0.3048,
    'km': 1000.0,
    'kilometer': 1000.0,
    'kilometers': 1000.0,
    'in': 0.0254,
    'inch': 0.0254,
    'inches': 0.0254,
}

_VALUES = [0, 1, 2.5, 10, 123.45]
_FORMATS = [
    '{v} {u}',
    '{v}{u}',
    ' {v}{u} ',
    '{v} {u}.',
    '{v}{u}.',
    '{v}   {u}',
    '{v}\t{u}',
]


case_idx = 0
for unit, factor in _UNIT_ALIASES.items():
    for value in _VALUES:
        for fmt in _FORMATS:
            raw = fmt.format(v=value, u=unit)
            expected = float(value) * factor
            setattr(
                TestInputToMeters,
                f'test_input_to_meters_{case_idx}',
                _mk_input_to_meters_case(raw, expected),
            )
            case_idx += 1


class TestInputToMetersInvalid(SimpleTestCase):
    def test_missing_unit_raises(self):
        from simo.core.utils.converters import input_to_meters

        with self.assertRaises(ValueError):
            input_to_meters('10')

    def test_missing_number_raises(self):
        from simo.core.utils.converters import input_to_meters

        with self.assertRaises(ValueError):
            input_to_meters('meters')

    def test_invalid_unit_raises(self):
        from simo.core.utils.converters import input_to_meters

        with self.assertRaises(ValueError):
            input_to_meters('10 parsecs')

    def test_invalid_number_raises(self):
        from simo.core.utils.converters import input_to_meters

        with self.assertRaises(ValueError):
            input_to_meters('abc m')


class TestHttpResponseRedirect(SimpleTestCase):
    def test_absolute_url_unchanged(self):
        from simo.core.utils.relay import HttpResponseRedirect

        with mock.patch('simo.core.utils.relay.get_script_prefix', return_value='/s/'):
            resp = HttpResponseRedirect('http://example.com/x')
            self.assertEqual(resp.url, 'http://example.com/x')

    def test_already_prefixed_unchanged(self):
        from simo.core.utils.relay import HttpResponseRedirect

        with mock.patch('simo.core.utils.relay.get_script_prefix', return_value='/simo/'):
            resp = HttpResponseRedirect('/simo/x')
            self.assertEqual(resp.url, '/simo/x')

    def test_script_prefix_is_applied(self):
        from simo.core.utils.relay import HttpResponseRedirect

        with mock.patch('simo.core.utils.relay.get_script_prefix', return_value='/simo/'):
            resp = HttpResponseRedirect('/x')
            self.assertEqual(resp.url, '/simo/x')


class TestSimoThrottle(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def test_throttled_returns_429_and_retry_after(self):
        from simo.core.utils.decorators import simo_throttle

        called = []

        @simo_throttle('scope-x')
        def view(_request):
            called.append(True)
            return HttpResponse('ok')

        req = self.rf.get('/x')
        with mock.patch('simo.core.throttling.check_throttle', return_value=2.7):
            resp = view(req)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp['Retry-After'], '2')
        self.assertEqual(called, [])

    def test_not_throttled_calls_view(self):
        from simo.core.utils.decorators import simo_throttle

        @simo_throttle('scope-x')
        def view(_request):
            return HttpResponse('ok')

        req = self.rf.get('/x')
        with mock.patch('simo.core.throttling.check_throttle', return_value=0):
            resp = view(req)
        self.assertEqual(resp.status_code, 200)

    def test_default_scope_uses_function_name(self):
        from simo.core.utils.decorators import simo_throttle

        @simo_throttle()
        def my_view(_request):
            return HttpResponse('ok')

        req = self.rf.get('/x')
        with mock.patch('simo.core.throttling.check_throttle', return_value=0) as chk:
            my_view(req)
        self.assertEqual(chk.call_args.kwargs['scope'], 'my_view')


class TestSimoCsrfExempt(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def test_simo_user_agent_skips_csrf(self):
        from simo.core.utils.decorators import simo_csrf_exempt

        @simo_csrf_exempt
        def view(_request):
            return HttpResponse('ok')

        req = self.rf.post('/x')
        req.headers = {'User-Agent': 'SIMO/1.0'}
        resp = view(req)
        self.assertEqual(resp.status_code, 200)

    def test_browser_user_agent_enforces_csrf(self):
        from simo.core.utils.decorators import simo_csrf_exempt

        @simo_csrf_exempt
        def view(_request):
            return HttpResponse('ok')

        req = self.rf.post('/x')
        req.headers = {'User-Agent': 'Mozilla/5.0'}
        resp = view(req)
        self.assertEqual(resp.status_code, 403)
