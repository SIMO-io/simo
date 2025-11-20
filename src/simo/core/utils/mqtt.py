import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt
from django.conf import settings


try:
    DEFAULT_KEEPALIVE = int(getattr(settings, 'MQTT_KEEPALIVE', 60))
except Exception:
    DEFAULT_KEEPALIVE = 60

DEFAULT_RETRY_DELAY = getattr(settings, 'MQTT_RETRY_DELAY', 5)


def _log(logger, level: str, message: str):
    if logger is None:
        print(message)
        return
    log_fn = getattr(logger, level, None)
    if log_fn:
        log_fn(message)
    else:
        logger.log(logging.INFO, message)


def connect_with_retry(
    client: mqtt.Client,
    *,
    logger=None,
    stop_event: Optional[threading.Event] = None,
    description: str = 'MQTT',
    retry_delay: int = DEFAULT_RETRY_DELAY,
    keepalive: int = DEFAULT_KEEPALIVE,
) -> bool:
    """Attempt to connect, retrying with backoff until success or stop_event."""

    attempt = 0
    while True:
        if stop_event and stop_event.is_set():
            return False
        try:
            client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive)
            if attempt:
                _log(
                    logger,
                    'info',
                    f"{description}: MQTT reconnected after {attempt} attempts.",
                )
            return True
        except Exception as exc:
            attempt += 1
            _log(
                logger,
                'warning',
                f"{description}: MQTT connect attempt {attempt} failed: {exc}. "
                f"Retrying in {retry_delay}s",
            )
            if stop_event:
                if stop_event.wait(retry_delay):
                    return False
            else:
                time.sleep(retry_delay)


def install_reconnect_handler(
    client: mqtt.Client,
    *,
    logger=None,
    stop_event: Optional[threading.Event] = None,
    description: str = 'MQTT',
    retry_delay: int = DEFAULT_RETRY_DELAY,
    user_handler: Optional[Callable[[mqtt.Client, object, int], None]] = None,
):
    """Wrap on_disconnect with an auto-reconnect loop."""

    reconnect_lock = threading.Lock()

    def _on_disconnect(cli, userdata, rc):
        if user_handler:
            try:
                user_handler(cli, userdata, rc)
            except Exception as exc:
                _log(logger, 'error', f"{description}: on_disconnect handler error: {exc}")
        if rc == mqtt.MQTT_ERR_SUCCESS:
            return
        if stop_event and stop_event.is_set():
            return
        if not reconnect_lock.acquire(blocking=False):
            return

        def _reconnect_loop():
            try:
                _log(
                    logger,
                    'warning',
                    f"{description}: MQTT connection lost (rc={rc}). Attempting reconnect...",
                )
                while not (stop_event and stop_event.is_set()):
                    try:
                        cli.reconnect()
                        _log(logger, 'info', f"{description}: MQTT reconnected successfully")
                        return
                    except Exception as exc:
                        _log(
                            logger,
                            'warning',
                            f"{description}: MQTT reconnect failed: {exc}. Retry in {retry_delay}s",
                        )
                        if stop_event:
                            if stop_event.wait(retry_delay):
                                return
                        else:
                            time.sleep(retry_delay)
            finally:
                reconnect_lock.release()

        threading.Thread(target=_reconnect_loop, daemon=True).start()

    client.on_disconnect = _on_disconnect
