from unittest import mock

from django.test import TestCase


class _FakePublishInfo:
    def __init__(self, rc=0):
        self.rc = rc


class _FakeMqttClient:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []

    def username_pw_set(self, *args, **kwargs):
        return None

    def reconnect_delay_set(self, *args, **kwargs):
        return None

    def connect(self, *args, **kwargs):
        return 0

    def connect_async(self, *args, **kwargs):
        return 0

    def is_connected(self):
        return True

    def loop_start(self, *args, **kwargs):
        return None

    def loop_stop(self, *args, **kwargs):
        return None

    def disconnect(self, *args, **kwargs):
        return None

    def reconnect(self, *args, **kwargs):
        return None

    def subscribe(self, topic, *args, **kwargs):
        self.subscribed.append(topic)
        return (0, 1)

    def unsubscribe(self, topic, *args, **kwargs):
        self.unsubscribed.append(topic)
        return (0, 1)

    def publish(self, *args, **kwargs):
        return _FakePublishInfo(rc=0)


class MqttHubTests(TestCase):
    def setUp(self):
        super().setUp()
        # Ensure a fresh hub singleton each test.
        import simo.core.mqtt_hub as mqtt_hub

        mqtt_hub._hub = None
        mqtt_hub._hub_pid = None

    def test_subscribe_only_subscribes_once_per_topic(self):
        import simo.core.mqtt_hub as mqtt_hub

        fake = _FakeMqttClient()
        with mock.patch.object(mqtt_hub.mqtt, 'Client', autospec=True, return_value=fake):
            hub = mqtt_hub.get_mqtt_hub()

            cb1 = mock.Mock()
            cb2 = mock.Mock()
            t1 = hub.subscribe('SIMO/x', cb1)
            t2 = hub.subscribe('SIMO/x', cb2)

            self.assertEqual(fake.subscribed, ['SIMO/x'])

            hub.unsubscribe(t1)
            self.assertEqual(fake.unsubscribed, [])
            hub.unsubscribe(t2)
            self.assertEqual(fake.unsubscribed, ['SIMO/x'])

    def test_on_message_dispatches_exact_and_wildcard(self):
        import simo.core.mqtt_hub as mqtt_hub

        fake = _FakeMqttClient()
        with mock.patch.object(mqtt_hub.mqtt, 'Client', autospec=True, return_value=fake):
            hub = mqtt_hub.get_mqtt_hub()
            exact = mock.Mock()
            wildcard = mock.Mock()
            hub.subscribe('SIMO/a', exact)
            hub.subscribe('SIMO/#', wildcard)

            msg = mock.Mock()
            msg.topic = 'SIMO/a'
            msg.payload = b'1'
            hub._on_message(fake, None, msg)

            exact.assert_called_once()
            wildcard.assert_called_once()

    def test_on_message_deduplicates_callbacks_and_ignores_callback_errors(self):
        import simo.core.mqtt_hub as mqtt_hub

        fake = _FakeMqttClient()
        with mock.patch.object(mqtt_hub.mqtt, 'Client', autospec=True, return_value=fake):
            hub = mqtt_hub.get_mqtt_hub()

            cb = mock.Mock(side_effect=[Exception('boom'), None])
            hub.subscribe('SIMO/a', cb)
            hub.subscribe('SIMO/#', cb)

            msg = mock.Mock()
            msg.topic = 'SIMO/a'
            msg.payload = b'1'

            # Should not raise.
            hub._on_message(fake, None, msg)
            cb.assert_called_once()

    def test_get_mqtt_hub_recreates_on_pid_change(self):
        import simo.core.mqtt_hub as mqtt_hub

        # getpid is called both in get_mqtt_hub() and _MqttHub.__init__
        with mock.patch('simo.core.mqtt_hub.os.getpid', autospec=True, side_effect=[1, 1, 1, 2, 2]):
            h1 = mqtt_hub.get_mqtt_hub()
            h2 = mqtt_hub.get_mqtt_hub()
            h3 = mqtt_hub.get_mqtt_hub()
        self.assertIs(h1, h2)
        self.assertIsNot(h1, h3)
