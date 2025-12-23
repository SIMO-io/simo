from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class TestRoutingModules(SimpleTestCase):
    def test_core_routing_has_expected_patterns(self):
        from simo.core import routing

        self.assertEqual(len(routing.urlpatterns), 3)
        patterns = [p.pattern.regex.pattern for p in routing.urlpatterns]
        self.assertIn(r'ws/log/(?P<ct_id>\d+)/(?P<object_pk>\d+)/$', patterns)
        self.assertIn(r'ws/gateway-controller/(?P<gateway_id>\d+)/$', patterns)
        self.assertIn(r'ws/component-controller/(?P<component_id>\d+)/$', patterns)

    def test_fleet_routing_has_expected_patterns(self):
        from simo.fleet import routing

        self.assertEqual(len(routing.urlpatterns), 1)
        self.assertEqual(routing.urlpatterns[0].pattern.regex.pattern, r'ws/fleet/$')

    def test_generic_routing_has_expected_patterns(self):
        from simo.generic import routing

        self.assertEqual(len(routing.urlpatterns), 1)
        self.assertEqual(
            routing.urlpatterns[0].pattern.regex.pattern,
            r'ws/cam-stream/(?P<component_id>\d+)/$',
        )


class TestCamStreamConsumer(SimpleTestCase):
    def test_disconnect_without_video_does_not_crash(self):
        from simo.generic.socket_consumers import CamStreamConsumer

        consumer = CamStreamConsumer()
        consumer.video = None
        asyncio.run(consumer.disconnect(1000))

    def test_connect_throttle_closes(self):
        from simo.generic.socket_consumers import CamStreamConsumer

        consumer = CamStreamConsumer()
        consumer.scope = {
            'user': SimpleNamespace(is_authenticated=True, is_active=True, is_master=True),
            'url_route': {'kwargs': {'component_id': 1}},
        }
        consumer.accept = mock.AsyncMock()
        consumer.close = mock.AsyncMock()

        with mock.patch('simo.generic.socket_consumers.check_throttle', return_value=1):
            asyncio.run(consumer.connect())

        consumer.close.assert_awaited_once()
        consumer.accept.assert_not_awaited()

