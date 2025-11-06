import threading
import logging
import os
from typing import Callable, Dict, List, Tuple

from django.conf import settings

import paho.mqtt.client as mqtt


logger = logging.getLogger(__name__)


class _MqttHub:
    """
    A process-wide MQTT hub managing a single client connection and
    multiplexing subscriptions to many callbacks. Prevents creating
    a separate MQTT client/thread per watcher and avoids FD leaks.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._client = None  # type: mqtt.Client | None
        self._subs: Dict[str, List[Callable[[mqtt.Client, object, object], None]]] = {}
        self._started = False
        self._connected = threading.Event()
        self._pid = os.getpid()

    def _recreate_client(self):
        # Close previous client if any (best-effort)
        try:
            if self._client is not None:
                try:
                    self._client.loop_stop()
                except Exception:
                    pass
                try:
                    self._client.disconnect()
                except Exception:
                    pass
        finally:
            self._client = None
            self._started = False
            self._connected.clear()
            self._pid = os.getpid()
        # Create fresh client and connect
        self._client = mqtt.Client()
        self._client.username_pw_set('root', settings.SECRET_KEY)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_publish = self._on_publish
        self._client.on_log = self._on_log
        try:
            self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        except Exception as e:
            print(f"[MQTTHUB] reconnect_delay_set failed (recreate): {e}")
        try:
            self._client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        except Exception as e:
            # Fallback to async connect
            try:
                self._client.connect_async(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
            except Exception as e2:
                print(f"[MQTTHUB] connect_async failed (recreate): {e2}")
        self._client.loop_start()
        self._started = True
        # Subscribe all topics for this fresh connection
        topics = list(self._subs.keys())
        for topic in topics:
            try:
                res = self._client.subscribe(topic)
            except Exception as e:
                print(f"[MQTTHUB] resubscribe exception for {topic}: {e}")

    # ----- public API -----
    @property
    def client(self) -> mqtt.Client:
        with self._lock:
            # Detect forked process using this singleton and recreate client
            if self._client is not None and os.getpid() != self._pid:
                self._recreate_client()
            if self._client is None:
                self._client = mqtt.Client()
                self._client.username_pw_set('root', settings.SECRET_KEY)
                self._client.on_connect = self._on_connect
                self._client.on_message = self._on_message
                self._client.on_disconnect = self._on_disconnect
                self._client.on_subscribe = self._on_subscribe
                self._client.on_publish = self._on_publish
                self._client.on_log = self._on_log
                try:
                    self._client.reconnect_delay_set(min_delay=1, max_delay=30)
                    print("[MQTTHUB] reconnect_delay_set ok")
                except Exception as e:
                    print(f"[MQTTHUB] reconnect_delay_set failed: {e}")
                try:
                    # Prefer a synchronous connect so first publish/subscribe is reliable
                    print(f"[MQTTHUB] connecting sync to {settings.MQTT_HOST}:{settings.MQTT_PORT}")
                    self._client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
                    print("[MQTTHUB] connect() returned")
                except Exception as e:
                    # Fallback to async connect if direct connect fails
                    print(f"[MQTTHUB] sync connect failed: {e}; fallback to async")
                    try:
                        self._client.connect_async(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
                        print("[MQTTHUB] connect_async() returned")
                    except Exception as e2:
                        print(f"[MQTTHUB] connect_async failed: {e2}")
                print("[MQTTHUB] loop_start()")
                self._client.loop_start()
                self._started = True
            else:
                # Refresh callbacks and ensure connection if client pre-existed
                self._client.on_connect = self._on_connect
                self._client.on_message = self._on_message
                self._client.on_disconnect = self._on_disconnect
                self._client.on_subscribe = self._on_subscribe
                self._client.on_publish = self._on_publish
                self._client.on_log = self._on_log
                try:
                    is_conn = self._client.is_connected()
                except Exception:
                    is_conn = False
                if not is_conn:
                    try:
                        self._client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
                    except Exception as e:
                        # Fallback to async connect
                        try:
                            self._client.connect_async(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
                        except Exception as e2:
                            logger.exception("MQTT hub: reconnect async failed")
                    if not self._started:
                        self._client.loop_start()
                        self._started = True
            return self._client

    def publish(self, topic: str, payload: str | bytes, retain: bool = False, qos: int = 0):
        """Publish using the shared client."""
        client = self.client
        try:
            info = client.publish(topic, payload, qos=qos, retain=retain)
            return info
        except Exception as e:
            logger.exception("MQTT hub: publish failed for topic %s", topic)

    def subscribe(self, topic: str, callback: Callable[[mqtt.Client, object, object], None]) -> Tuple[str, int]:
        """
        Register a callback for a topic. Returns a token (topic, idx).
        Callback signature matches paho: (client, userdata, msg)
        """
        with self._lock:
            client = self.client
            callbacks = self._subs.setdefault(topic, [])
            callbacks.append(callback)
            if len(callbacks) == 1:
                try:
                    res = client.subscribe(topic)
                    if isinstance(res, tuple) and res[0] != 0:
                        try:
                            client.reconnect()
                            res = client.subscribe(topic)
                        except Exception as e:
                            logger.exception("MQTT hub: subscribe reconnect exception")
                except Exception as e:
                    logger.exception("MQTT hub: subscribe failed for %s", topic)
            token = (topic, len(callbacks) - 1)
            return token

    def unsubscribe(self, token: Tuple[str, int]):
        topic, idx = token
        with self._lock:
            callbacks = self._subs.get(topic)
            if not callbacks:
                return
            # mark slot as None to avoid shifting tokens
            if 0 <= idx < len(callbacks):
                callbacks[idx] = None  # type: ignore
            # If all slots are None, unsubscribe and drop the entry
            if not any(cb is not None for cb in callbacks):
                self._subs.pop(topic, None)
                try:
                    if self._client is not None:
                        res = self._client.unsubscribe(topic)
                except Exception as e:
                    logger.exception("MQTT hub: unsubscribe failed for %s", topic)

    def shutdown(self):
        with self._lock:
            if self._client is not None and self._started:
                try:
                    self._client.loop_stop()
                except Exception as e:
                    logger.exception("MQTT hub: loop_stop exception")
                try:
                    self._client.disconnect()
                except Exception as e:
                    logger.exception("MQTT hub: disconnect exception")
                self._client = None
                self._subs.clear()
                self._started = False

    # ----- paho handlers -----
    def _on_connect(self, client: mqtt.Client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
        # Re-subscribe all topics after reconnect
        with self._lock:
            topics = list(self._subs.keys())
        for topic in topics:
            try:
                client.subscribe(topic)
            except Exception as e:
                logger.exception("MQTT hub: resubscribe failed for %s", topic)

    def _on_message(self, client: mqtt.Client, userdata, msg):
        # Dispatch to callbacks bound to this topic (exact) and any wildcard subscriptions
        matched_callbacks: List[Callable] = []
        with self._lock:
            # exact match first
            exact = self._subs.get(msg.topic, [])
            matched_callbacks.extend([cb for cb in exact if cb is not None])
            # wildcard matches
            for sub, cbs in self._subs.items():
                if sub == msg.topic:
                    continue
                try:
                    if mqtt.topic_matches_sub(sub, msg.topic):
                        matched_callbacks.extend([cb for cb in cbs if cb is not None])
                except Exception:
                    # If malformed subscription key sneaks in, ignore
                    continue
        # De-duplicate callbacks while preserving order
        for cb in dict.fromkeys(matched_callbacks):
            try:
                cb(client, None, msg)
            except Exception:
                logger.exception("MQTT hub: callback failed for topic %s", msg.topic)

    def _on_disconnect(self, client: mqtt.Client, userdata, rc):
        pass

    def _on_subscribe(self, client: mqtt.Client, userdata, mid, granted_qos):
        pass

    def _on_publish(self, client: mqtt.Client, userdata, mid):
        pass

    def _on_log(self, client: mqtt.Client, userdata, level, buf):
        try:
            logger.debug("MQTT: %s", buf)
        except Exception:
            pass


_hub: _MqttHub | None = None


def get_mqtt_hub() -> _MqttHub:
    global _hub
    if _hub is None:
        _hub = _MqttHub()
    return _hub
