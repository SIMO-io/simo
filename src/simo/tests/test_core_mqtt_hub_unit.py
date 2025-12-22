from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class FakePublishInfo:
    def __init__(self, rc=0):
        self.rc = rc


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.on_subscribe = None
        self.on_publish = None
        self.on_log = None

        self.subscribed = []
        self.unsubscribed = []
        self.published = []
        self.loop_started = 0
        self.loop_stopped = 0
        self.disconnected = 0

    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None

    def connect(self, **_kwargs):
        return 0

    def connect_async(self, **_kwargs):
        return 0

    def loop_start(self):
        self.loop_started += 1

    def loop_stop(self):
        self.loop_stopped += 1

    def disconnect(self):
        self.disconnected += 1

    def subscribe(self, topic):
        self.subscribed.append(topic)
        return (0, 1)

    def unsubscribe(self, topic):
        self.unsubscribed.append(topic)
        return (0,)

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))
        return FakePublishInfo(rc=0)

    def reconnect(self):
        return None


class MqttHubUnitTests(SimpleTestCase):
    def _mk_hub(self):
        from simo.core.mqtt_hub import _MqttHub

        with mock.patch('simo.core.mqtt_hub.mqtt.Client', autospec=True, side_effect=FakeMqttClient):
            hub = _MqttHub()
            # Force client creation while patched.
            _ = hub.client
            return hub

    def test_subscribe_first_time_calls_client_subscribe(self):
        hub = self._mk_hub()

        cb = mock.Mock()
        token = hub.subscribe('a/b', cb)

        self.assertEqual(token, ('a/b', 0))
        self.assertEqual(hub.client.subscribed, ['a/b'])

    def test_subscribe_second_callback_does_not_resubscribe(self):
        hub = self._mk_hub()
        hub.subscribe('a/b', mock.Mock())
        hub.client.subscribed.clear()

        hub.subscribe('a/b', mock.Mock())

        self.assertEqual(hub.client.subscribed, [])

    def test_unsubscribe_last_callback_calls_client_unsubscribe(self):
        hub = self._mk_hub()
        token = hub.subscribe('a/b', mock.Mock())

        hub.unsubscribe(token)

        self.assertEqual(hub.client.unsubscribed, ['a/b'])

    def test_unsubscribe_keeps_other_callbacks(self):
        hub = self._mk_hub()
        t1 = hub.subscribe('a/b', mock.Mock())
        hub.subscribe('a/b', mock.Mock())

        hub.unsubscribe(t1)

        self.assertEqual(hub.client.unsubscribed, [])

    def test_on_message_dispatches_exact_topic(self):
        hub = self._mk_hub()
        cb = mock.Mock()
        hub.subscribe('a/b', cb)

        msg = SimpleNamespace(topic='a/b', payload=b'{}')
        hub._on_message(hub.client, None, msg)

        cb.assert_called_once_with(hub.client, None, msg)

    def test_on_message_dispatches_wildcard_subscription(self):
        hub = self._mk_hub()
        cb = mock.Mock()
        hub.subscribe('a/#', cb)

        with mock.patch('simo.core.mqtt_hub.mqtt.topic_matches_sub', autospec=True, return_value=True):
            msg = SimpleNamespace(topic='a/b', payload=b'{}')
            hub._on_message(hub.client, None, msg)

        cb.assert_called_once_with(hub.client, None, msg)

    def test_on_message_deduplicates_callbacks(self):
        hub = self._mk_hub()
        cb = mock.Mock()
        hub.subscribe('a/#', cb)
        hub.subscribe('a/b', cb)

        with mock.patch('simo.core.mqtt_hub.mqtt.topic_matches_sub', autospec=True, return_value=True):
            msg = SimpleNamespace(topic='a/b', payload=b'{}')
            hub._on_message(hub.client, None, msg)

        cb.assert_called_once()

    def test_on_message_ignores_callback_exceptions(self):
        hub = self._mk_hub()

        def boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        ok = mock.Mock()
        hub.subscribe('a/b', boom)
        hub.subscribe('a/b', ok)

        msg = SimpleNamespace(topic='a/b', payload=b'{}')
        hub._on_message(hub.client, None, msg)

        ok.assert_called_once()
