from types import SimpleNamespace

from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from simo.core.middleware import (
    introduce_instance,
    get_current_instance,
    instance_middleware,
)

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


def _add_session(request):
    middleware = SessionMiddleware(lambda _req: None)
    middleware.process_request(request)
    request.session.save()


class InstanceMiddlewareTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def test_introduce_instance_clears_poisoned_session_for_unauthorized_user(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')

        req = self.rf.get('/x')
        _add_session(req)
        req.user = user
        req.session['instance_id'] = inst.id

        tok = introduce_instance(inst, req)
        self.assertIsNone(tok)
        self.assertNotIn('instance_id', req.session)

    def test_get_current_instance_drops_session_instance_id_when_access_denied(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')

        req = self.rf.get('/x')
        _add_session(req)
        req.user = user
        req.session['instance_id'] = inst.id

        cur = get_current_instance(req)
        self.assertIsNone(cur)
        self.assertNotIn('instance_id', req.session)

    def test_instance_middleware_sets_timezone_and_resets_context(self):
        inst = mk_instance('inst-a', 'A')
        inst.timezone = 'Europe/Vilnius'
        inst.save(update_fields=['timezone'])

        from django.core.cache import cache
        from simo.users.models import User

        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        cache.clear()
        user = User.objects.get(pk=user.pk)
        req = self.rf.get(f'/api/{inst.slug}/core/info/')
        _add_session(req)
        req.user = user
        req.resolver_match = SimpleNamespace(kwargs={'instance_slug': inst.slug})

        captured = {}

        def get_response(_request):
            captured['tz'] = timezone.get_current_timezone_name()
            captured['instance'] = get_current_instance()
            return HttpResponse('ok')

        wrapped = instance_middleware(get_response)
        resp = wrapped(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get('tz'), inst.timezone)
        self.assertEqual(getattr(captured.get('instance'), 'id', None), inst.id)

        # Must not leak timezone/instance outside request.
        self.assertIsNone(get_current_instance())
