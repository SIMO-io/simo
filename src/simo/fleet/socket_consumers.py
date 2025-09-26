import asyncio
import json
import logging
import pytz
import traceback
import sys
import zlib
import time
import io
import websockets
import lameenc
import inspect
from pydub import AudioSegment
from datetime import datetime, timedelta
from django.db import transaction
from logging.handlers import RotatingFileHandler
from django.utils import timezone
from django.conf import settings
import paho.mqtt.client as mqtt
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from simo.core.utils.model_helpers import get_log_file_path
from simo.core.middleware import drop_current_instance
from simo.core.utils.logs import capture_socket_errors
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.models import Gateway, Instance, Component
from simo.conf import dynamic_settings
from simo.users.models import Fingerprint

from .gateways import FleetGatewayHandler
from .models import Colonel
from .controllers import TTLock


class VoiceAssistantSession:
    """Per-connection voice session manager for room-sensor (Sentinel).

    Responsibilities:
    - Aggregate PCM frames into an utterance using inactivity threshold.
    - Encode PCM->MP3 and send to Website over WS; receive MP3 reply.
    - Decode MP3->PCM and stream back to device paced in 32 ms chunks.
    - Manage follow-up window and Colonel.is_vo_active lifecycle.
    """

    # Tunables
    INACTIVITY_MS = 800          # consider utterance ended after this quiet
    MAX_UTTERANCE_SEC = 20       # hard cap to avoid runaway buffers
    # Match Sentinel I2S TX chunk (1024 bytes ≈ 32 ms @ 16 kHz 16-bit mono)
    PLAY_CHUNK_BYTES = 1024
    PLAY_CHUNK_INTERVAL = 0.032
    FOLLOWUP_SEC = 15            # follow-up window after playback

    def __init__(self, consumer: "FleetConsumer"):
        self.c = consumer
        self.active = False
        self.awaiting_response = False
        self.playing = False
        self._end_after_playback = False
        self.capture_buf = bytearray()
        self.last_chunk_ts = 0.0
        self.last_rx_audio_ts = 0.0
        self.last_tx_audio_ts = 0.0
        self.started_ts = None
        self.mcp_token = None
        self._finalizer_task = None
        self._cloud_task = None
        self._play_task = None
        self._followup_task = None
        self.voice = 'male'
        self.zone = None
        self._idle_task = asyncio.create_task(self._idle_watchdog())
        self._utterance_task = asyncio.create_task(self._utterance_watchdog())

    async def start_if_needed(self):
        if self.active:
            return
        self.active = True
        self.started_ts = time.time()
        await self._set_is_vo_active(True)

    async def on_audio_chunk(self, payload: bytes):
        """Handle a PCM chunk from Sentinel (0x00 prefix stripped)."""
        # Ignore during playback or waiting for cloud reply (speaker echo)
        if self.playing or self.awaiting_response:
            return

        await self.start_if_needed()

        # Append and track time
        if not getattr(self, '_rx_started', False):
            self._rx_started = True
            self._rx_start_ts = time.time()
            print("VA RX START (device→hub)")
        self.capture_buf.extend(payload)
        self.last_chunk_ts = time.time()
        self.last_rx_audio_ts = self.last_chunk_ts

        # Cap size/duration
        if len(self.capture_buf) > 2 * 16000 * self.MAX_UTTERANCE_SEC:
            # 2 bytes/sample * 16k * seconds
            await self._finalize_utterance()
            return

        # Debounced finalizer
        if not self._finalizer_task or self._finalizer_task.done():
            self._finalizer_task = asyncio.create_task(self._finalizer_loop())

    async def _finalizer_loop(self):
        # Wait until quiet period
        try:
            while True:
                if not self.active:
                    return
                if self.awaiting_response or self.playing:
                    return
                if self.last_chunk_ts and (time.time() - self.last_chunk_ts) * 1000 >= self.INACTIVITY_MS:
                    print("VA FINALIZE UTTERANCE (quiet)")
                    await self._finalize_utterance()
                    return
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return

    async def _utterance_watchdog(self):
        # Secondary safeguard to finalize utterance if finalizer task didn't start
        while True:
            try:
                await asyncio.sleep(0.1)
                if not self.active:
                    continue
                if self.awaiting_response or self.playing:
                    continue
                # If we have buffered audio and we were quiet long enough, finalize
                if self.capture_buf and self.last_chunk_ts and (time.time() - self.last_chunk_ts) * 1000 >= self.INACTIVITY_MS:
                    print("VA FINALIZE (watchdog)")
                    await self._finalize_utterance()
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    async def _finalize_utterance(self):
        if not self.capture_buf:
            return
        # Move buffer and reset capture
        pcm = bytes(self.capture_buf)
        self.capture_buf.clear()
        self.last_chunk_ts = 0
        # Debug end of device→hub RX + capture stats
        try:
            dur = time.time() - (self._rx_start_ts or time.time())
            print(f"VA RX END (device→hub) bytes={len(pcm)} dur={dur:.2f}s")
            samples = len(pcm) // 2
            exp = samples / 16000.0
            if exp:
                print(f"VA CAPTURE STATS: samples={samples} sec={exp:.2f} wall={dur:.2f} ratio={dur/exp:.2f}")
        except Exception:
            pass
        finally:
            self._rx_started = False

        # Send to cloud and then play back response
        if self._cloud_task and not self._cloud_task.done():
            # Should not happen due to await pipeline, but guard
            return
        self._cloud_task = asyncio.create_task(self._cloud_roundtrip_and_play(pcm))

    async def _cloud_roundtrip_and_play(self, pcm_bytes: bytes):
        self.awaiting_response = True
        try:
            mp3_bytes = await self._encode_mp3(pcm_bytes)
            if not mp3_bytes:
                return
            print(f"VA TX START (hub→website) mp3={len(mp3_bytes)}B")
            # Connect to Website WS and exchange
            ws_url = "wss://simo.io/ws/voice-assistant/"
            # Read dynamic settings in a sync-safe way
            hub_uid = await sync_to_async(lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True)()
            hub_secret = await sync_to_async(lambda: dynamic_settings['core__hub_secret'], thread_sensitive=True)()
            headers = {
                "hub-uid": hub_uid,
                "hub-secret": hub_secret,
                "instance-uid": self.c.instance.uid,
                "mcp-token": self.mcp_token.token,
                "voice": self.voice,
                "zone": self.zone
            }
            if not websockets:
                raise RuntimeError("websockets library not available")
            print(f"VA WS CONNECT {ws_url}")

            kwargs = {'max_size': 10 * 1024 * 1024}
            # Stupid generation Z developers!!! What a shame!!! Shame on you, you bastards!
            # Whoever thought renaming extra_headers to additional_headers
            # at this point in time, without providing backward compatability deserves
            # life time sentence in prison with 500 years restriction on any coding work.
            # Debilai bliat.
            ws_params = inspect.signature(websockets.connect).parameters
            if 'additional_headers' in ws_params:
                kwargs['additional_headers'] = headers
            else:
                kwargs['extra_headers'] = headers
            async with websockets.connect(ws_url, **kwargs) as ws:
                print("VA WS OPEN")
                await ws.send(mp3_bytes)
                print("VA WS SENT (binary)")

                mp3_reply = None
                while True:
                    try:
                        msg = await ws.recv()
                    except Exception as e:
                        raise e
                    if isinstance(msg, (bytes, bytearray)):
                        mp3_reply = bytes(msg)
                        print(f"VA RX START (website→hub) mp3={len(mp3_reply)}B")
                        break
                    else:
                        # text control/interim messages
                        try:
                            data = json.loads(msg)
                        except Exception:
                            data = None
                        if isinstance(data, dict):
                            print(f"VA WS CTRL {data}")
                            # Handle Website control hints
                            # 1) Session finish request
                            if data.get('session') == 'finish':
                                # End after any current playback completes
                                self._end_after_playback = True
                                # Propagate to Sentinel so it can sleep immediately if desired
                                try:
                                    await self.c.send_data(
                                        {'command': 'va', 'session': 'finish',
                                         'status': data.get('status', 'success')}
                                    )
                                except Exception:
                                    pass
                            # 2) Reasoning indicator (e.g., web search or long reasoning)
                            if 'reasoning' in data:
                                try:
                                    await self.c.send_data({'command': 'va', 'reasoning': bool(data['reasoning'])})
                                except Exception:
                                    pass
                        # Optionally forward interim to device (not required now)
                        # await self._send_device_json({'command': 'va', 'type': 'interim', 'text': data.get('interim')})

            if mp3_reply:
                pcm_out = await self._decode_mp3(mp3_reply)
                if pcm_out:
                    await self._play_to_device(pcm_out)
                    # After playback completes, end immediately if requested by Website
                    if self._end_after_playback:
                        await self._end_session(cloud_also=False)
                        self._end_after_playback = False
                elif self._end_after_playback:
                    await self._end_session(cloud_also=False)
                    self._end_after_playback = False
            elif self._end_after_playback:
                await self._end_session(cloud_also=False)
                self._end_after_playback = False
        except Exception as e:
            print("VA WS ERROR:", e, file=sys.stderr)
            print("VA: Cloud roundtrip failed\n", traceback.format_exc(), file=sys.stderr)
            try:
                await self.c.send_data(
                    {'command': 'va', 'session': 'finish', 'status': 'error'}
                )
            except Exception:
                pass
            # Fail fast: end session and notify Website
            await self._end_session(cloud_also=True)
        finally:
            self.awaiting_response = False
            # Start follow-up window only if still active
            if self.active and not self.playing and not self._end_after_playback:
                await self._start_followup_timer()

    async def _encode_mp3(self, pcm_bytes: bytes):
        # Ensure encoder availability
        if lameenc is None:
            # Fallback to pydub+ffmpeg
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self._encode_mp3_pydub(pcm_bytes))
        def _enc():
            enc = lameenc.Encoder()
            enc.set_bit_rate(48)  # kbps
            enc.set_in_sample_rate(16000)
            enc.set_channels(1)
            enc.set_quality(2)
            return enc.encode(pcm_bytes) + enc.flush()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _enc)
        except Exception:
            print("VA: lameenc failed, fallback to pydub", file=sys.stderr)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self._encode_mp3_pydub(pcm_bytes))

    def _encode_mp3_pydub(self, pcm_bytes: bytes):
        if AudioSegment is None:
            return None
        # pcm_bytes is s16le mono 16kHz
        audio = AudioSegment(
            data=pcm_bytes, sample_width=2, frame_rate=16000, channels=1
        )
        out = io.BytesIO()
        audio.export(out, format='mp3', bitrate='48k')
        return out.getvalue()

    async def _decode_mp3(self, mp3_bytes: bytes):
        if AudioSegment is None:
            return None
        def _dec():
            audio = AudioSegment.from_file(io.BytesIO(mp3_bytes), format='mp3')
            audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            return audio.raw_data
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _dec)
        except Exception:
            print("VA: MP3 decode failed\n", traceback.format_exc(), file=sys.stderr)
            return None

    async def _play_to_device(self, pcm_bytes: bytes):
        # Send paced 1024B chunks prefixed with 0x01
        self.playing = True
        try:
            print(f"VA TX START (hub→device) pcm={len(pcm_bytes)}B")
            # Optional: instruct device to mute mic (if supported later)
            # await self._send_device_json({'command': 'va', 'type': 'play', 'action': 'start'})
            view = memoryview(pcm_bytes)
            total = len(view)
            pos = 0
            sent_total = 0
            # Conservative, clocked pacing by time budget
            next_deadline = time.time()
            # Keep fudge at 0 for now; adjust dynamically if needed
            fudge = 0.0
            pace_start = time.time()
            chunks = 0
            warmup = 1  # send first chunk back-to-back to prime
            while pos < total and self.c.connected:
                chunk = view[pos:pos + self.PLAY_CHUNK_BYTES]
                pos += len(chunk)
                try:
                    await self.c.send(bytes_data=b"\x01" + bytes(chunk))
                    self.last_tx_audio_ts = time.time()
                    sent_total += len(chunk)
                    chunks += 1
                except Exception:
                    break
                if warmup > 0:
                    warmup -= 1
                else:
                    # Compute duration for this specific chunk (bytes → samples → seconds)
                    samples = len(chunk) // 2
                    dt = samples / 16000.0
                    next_deadline += dt
                    # If we're behind schedule, don't sleep (catch up)
                    drift = next_deadline - time.time()
                    sleep_for = drift + fudge
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
        finally:
            self.playing = False
            try:
                elapsed = time.time() - pace_start if 'pace_start' in locals() else 0.0
                audio_sec = (sent_total // 2) / 16000.0 if sent_total else 0.0
                print(f"VA TX END (hub→device) sent≈{sent_total}B chunks={chunks} elapsed={elapsed:.2f}s audio={audio_sec:.2f}s ratio={elapsed/audio_sec if audio_sec else 0:.2f}")
            except Exception:
                pass
            # await self._send_device_json({'command': 'va', 'type': 'play', 'action': 'end', 'allow_followup': True})

    async def _start_followup_timer(self):
        # Cancel existing
        if self._followup_task and not self._followup_task.done():
            self._followup_task.cancel()
        async def _timer():
            try:
                await asyncio.sleep(self.FOLLOWUP_SEC)
                # If nothing new started, end session
                if self.active and not self.playing and not self.awaiting_response and not self.capture_buf:
                    await self._end_session(cloud_also=False)
            except asyncio.CancelledError:
                return
        self._followup_task = asyncio.create_task(_timer())

    async def _end_session(self, cloud_also: bool = False):
        # Clear internal state
        self.active = False
        self.capture_buf.clear()
        self.last_chunk_ts = 0
        self.last_rx_audio_ts = 0
        self.last_tx_audio_ts = 0
        # Cancel timers
        for t in (self._finalizer_task, self._cloud_task, self._play_task, self._followup_task):
            if t and not t.done():
                t.cancel()
        self._finalizer_task = self._cloud_task = self._play_task = self._followup_task = None

        await self._set_is_vo_active(False)
        # Optional: end Website session (requires Website endpoint)
        if cloud_also:
            await self._finish_cloud_session()
        # Optional: notify device to fully sleep
        # await self._send_device_json({'command': 'va', 'type': 'session', 'action': 'end'})

    async def _idle_watchdog(self):
        # Auto-deactivate after 120s with no RX or TX audio
        IDLE_SEC = 120
        while True:
            try:
                await asyncio.sleep(2)
                if not self.active:
                    continue
                # Consider the latest audio activity, RX or TX
                last_audio = max(self.last_rx_audio_ts or 0, self.last_tx_audio_ts or 0)
                if not last_audio:
                    continue
                if (time.time() - last_audio) > IDLE_SEC:
                    print("VA idle timeout reached (120s), ending session")
                    await self._end_session(cloud_also=True)
            except asyncio.CancelledError:
                return
            except Exception:
                # Don't crash the loop on observer issues
                pass

    async def _set_is_vo_active(self, flag: bool):
        def _execute():
            from simo.mcp_server.models import InstanceAccessToken
            with transaction.atomic():
                if flag:
                    self.mcp_token, new = InstanceAccessToken.objects.get_or_create(
                        instance=self.c.colonel.instance, date_expired=None,
                        issuer='sentinel'
                    )
                else:
                    # There should be a single mcp token only issued by sentinel
                    InstanceAccessToken.objects.filter(
                        instance=self.c.colonel.instance, date_expired=None,
                        issuer='sentinel'
                    ).update(date_expired=timezone.now())
                    self.mcp_token = None
                self.c.colonel.is_vo_active = flag
                self.c.colonel.save(update_fields=['is_vo_active'])

        await sync_to_async(_execute, thread_sensitive=True)()



    async def _finish_cloud_session(self):
        """Call Website HTTP endpoint to mark AISession closed for this instance.
        Retries with backoff if needed; idempotent on the server.
        """
        try:
            import requests
        except Exception:
            return

        # Read dynamic settings safely

        hub_uid = await sync_to_async(lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True)()
        hub_secret = await sync_to_async(lambda: dynamic_settings['core__hub_secret'], thread_sensitive=True)()
        url = 'https://simo.io/ai/finish-session/'
        payload = {
            'hub_uid': hub_uid,
            'hub_secret': hub_secret,
            'instance_uid': self.c.instance.uid,
        }

        def _post():
            try:
                return requests.post(url, json=payload, timeout=5)
            except Exception:
                return None

        # Best-effort retries: 3 attempts with backoff
        delays = [0, 2, 5]
        for delay in delays:
            if delay:
                try:
                    # non-blocking sleep in async, but requests runs in thread
                    # We'll just sleep async here
                    pass
                except Exception:
                    pass
            try:
                if delay:
                    await asyncio.sleep(delay)
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(None, _post)
                if resp is not None and getattr(resp, 'status_code', None) in (200, 204):
                    return
            except Exception:
                continue
        # Give up silently; Website TTL auto-close will cleanup

    async def shutdown(self):
        await self._end_session(cloud_also=False)


@capture_socket_errors
class FleetConsumer(AsyncWebsocketConsumer):


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.colonel = None
        self.colonel_logger = None
        self.connected = False
        self.mqtt_client = None
        self.last_seen = 0
        self._va = None


    async def disconnect(self, code):
        print("Colonel %s socket disconnected!" % str(self.colonel))
        self.connected = False
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
        # Stop any active voice session
        try:
            if self._va and (self._va.active or self.colonel.is_vo_active):
                # On disconnect, propagate finish upstream as well
                await self._va._end_session(cloud_also=True)
            elif getattr(self.colonel, 'is_vo_active', False):
                # No session manager but flag says active; finish upstream idempotently
                def _save():
                    self.colonel.is_vo_active = False
                    self.colonel.save(update_fields=['is_vo_active'])
                await sync_to_async(_save, thread_sensitive=True)()
                try:
                    # Best effort notify Website
                    base = await sync_to_async(lambda: dynamic_settings.get('core__remote_http'), thread_sensitive=True)()
                    hub_uid = await sync_to_async(lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True)()
                    hub_secret = await sync_to_async(lambda: dynamic_settings['core__hub_secret'], thread_sensitive=True)()
                    base = base or 'https://simo.io'
                    url = base.rstrip('/') + '/ai/finish-session/'
                    payload = {
                        'hub_uid': hub_uid,
                        'hub_secret': hub_secret,
                        'instance_uid': self.instance.uid,
                    }
                    import requests
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=5))
                except Exception:
                    pass
        except Exception:
            pass

        def save_disconect():
            if self.colonel:
                self.colonel.socket_connected = False
                # Always clear any lingering VO active flag on disconnect
                self.colonel.is_vo_active = False
                self.colonel.save(update_fields=['socket_connected', 'is_vo_active'])
        await sync_to_async(save_disconect, thread_sensitive=True)()


    async def connect(self):
        print("Fleet Socket Connect with headers:", self.scope.get('headers'))
        await self.accept()

        headers = {
            item[0].decode().lower(): item[1].decode() for item in self.scope['headers']
        }

        instance_uid = headers.get('instance-uid')

        def get_instance(instance_uid):
            try:
                return Instance.objects.prefetch_related(
                    'fleet_options'
                ).get(uid=instance_uid)
            except:
                return

        if not instance_uid:
            print("No instance_uid in headers! Disconnect socket!")
            return await self.close()

        self.instance = await sync_to_async(
            get_instance, thread_sensitive=True
        )(instance_uid)

        if not self.instance:
            print("Wrong instance UID!")
            return await self.close()

        if self.instance.fleet_options.secret_key \
            != headers.get('instance-secret'):
            print("Bad instance secret! Headers received: ", headers)
            return await self.close()

        def get_tz():
            return pytz.timezone(self.instance.timezone)

        tz = await sync_to_async(get_tz, thread_sensitive=True)()
        timezone.activate(tz)

        def get_colonel():
            defaults={
                'instance': self.instance,
                'name': headers.get('colonel-name'),
                'type': headers['colonel-type'],
                'firmware_version': headers['firmware-version'],
                'last_seen': timezone.now(),
                'enabled': True
            }
            # !!!!! ATETION! !!!!!!!
            # update_or_create and get_or_create doesn't
            # provide reliable operation in socket/async environment.
            new = False
            colonel = Colonel.objects.filter(uid=headers['colonel-uid']).first()
            if not colonel:
                new = True
                colonel = Colonel.objects.create(
                    uid=headers['colonel-uid'], **defaults
                )
            else:
                for key, val in defaults.items():
                    if key == 'name':
                        continue
                    setattr(colonel, key, val)
                colonel.save()

            return colonel, new

        self.colonel, new = await sync_to_async(
            get_colonel, thread_sensitive=True
        )()

        print(f"Colonel {self.colonel} connected!")
        if not self.colonel.enabled:
            print("Colonel %s drop, it's not enabled!" % str(self.colonel))
            return await self.close()

        if headers.get('instance-uid') != self.colonel.instance.uid \
        or headers.get('instance-secret') != self.colonel.instance.fleet_options.secret_key:
            print("NOT authorized!")
            return await self.close()

        self.connected = True

        await self.log_colonel_connected()
        # Ensure clean start: clear is_vo_active on every (re)connect
        def _reset_vo():
            if self.colonel.is_vo_active:
                self.colonel.is_vo_active = False
                self.colonel.save(update_fields=['is_vo_active'])
        try:
            await sync_to_async(_reset_vo, thread_sensitive=True)()
        except Exception:
            pass


        def get_gateway():
            return Gateway.objects.filter(
                type=FleetGatewayHandler.uid
            ).first()

        self.gateway = await sync_to_async(
            get_gateway, thread_sensitive=True
        )()

        if self.colonel.firmware_auto_update \
            and self.colonel.minor_upgrade_available:
            await self.firmware_update(self.colonel.minor_upgrade_available)
        else:
            def on_mqtt_connect(mqtt_client, userdata, flags, rc):
                command = GatewayObjectCommand(self.gateway)
                TOPIC = command.get_topic()
                print("SUBSCRIBE TO TOPIC: ", TOPIC)
                mqtt_client.subscribe(TOPIC)

            self.mqtt_client = mqtt.Client()
            self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
            self.mqtt_client.on_connect = on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.connect(host=settings.MQTT_HOST,
                                     port=settings.MQTT_PORT)
            self.mqtt_client.loop_start()

            # DO NOT FORCE CONFIG DATA!!!!
            # as colonels might already have config and want to
            # send updated values of components, like for example
            # somebody turned some lights on/off while colonel was
            # not connected to the main hub.
            # If we force this, vales get overridden by what is last
            # known by the hub
            # config = await self.get_config_data()
            # await self.send_data(
            #     'command': 'set_config', 'data': config
            # })

            await self.send_data({'command': 'hello'})

        asyncio.create_task(self.watch_connection())

    async def watch_connection(self):
        while self.connected:
            await sync_to_async(
                self.colonel.refresh_from_db, thread_sensitive=True
            )()

            if self.colonel.firmware_auto_update \
            and self.colonel.minor_upgrade_available:
                await self.firmware_update(
                    self.colonel.minor_upgrade_available
                )

            # Default pinging system sometimes get's lost somewhere,
            # therefore we use our own to ensure connection and understand if
            # colonel is connected or not

            if time.time() - self.last_seen > 2:
                await self.send_data({'command': 'ping'})

            # Robust cleanup: if voice session looks orphaned (no traffic) for >60s, finish upstream
            try:
                if self._va and self._va.active and (time.time() - self.last_seen) > 60:
                    await self._va._end_session(cloud_also=True)
            except Exception:
                pass

            await asyncio.sleep(2)


    async def firmware_update(self, to_version):
        print("Firmware update: ", str(self.colonel))
        await self.send_data({'command': 'ota_update', 'version': to_version})

    async def get_config_data(self):
        self.colonel = await sync_to_async(
            Colonel.objects.get, thread_sensitive=True
        )(id=self.colonel.id)
        hub_uid = await sync_to_async(
            lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True
        )()

        def get_instance_options():
            return {
                'instance_uid': self.instance.uid,
                'instance_secret': self.instance.fleet_options.secret_key
            }
        instance_options = await sync_to_async(
            get_instance_options, thread_sensitive=True
        )()

        config_data = {
            'devices': {}, 'interfaces': {},
            'settings': {
                'name': self.colonel.name, 'hub_uid': hub_uid,
                'logs_stream': self.colonel.logs_stream,
                'pwm_frequency': self.colonel.pwm_frequency,
            }
        }
        config_data['settings'].update(instance_options)

        def get_interfaces(colonel):
            return list(colonel.interfaces.all().select_related(
                'pin_a', 'pin_b'
            ))
        interfaces = await sync_to_async(get_interfaces, thread_sensitive=True)(
            self.colonel
        )
        for interface in interfaces:
            config_data['interfaces'][f'{interface.type}-{interface.no}'] = {
                'pin_a': interface.pin_a.no, 'pin_b': interface.pin_b.no,
            }

        def get_components(colonel):
            return list(
                colonel.components.all().prefetch_related('slaves')
            )
        components = await sync_to_async(
            get_components, thread_sensitive=True
        )(self.colonel)

        def get_comp_config(comp):
            try:
                comp_config = {
                    'type': comp.controller.uid.split('.')[-1],
                    'val': comp.controller._prepare_for_send(
                        comp.value
                    ),
                    'config': comp.controller._get_colonel_config()
                }
                if hasattr(comp.controller, 'family'):
                    comp_config['family'] = comp.controller.family
                slaves = [
                    s.id for s in comp.slaves.all()
                    if s.config.get('colonel') == self.colonel.id
                ]
                if slaves:
                    comp_config['slaves'] = slaves
                if comp.meta.get('options'):
                    comp_config['options'] = comp.meta['options']

                config_data['devices'][str(comp.id)] = comp_config
            except:
                print("Error preparing component config")
                print(traceback.format_exc(), file=sys.stderr)
            else:
                return comp_config

        for component in components:

            comp_config = components = await sync_to_async(
                get_comp_config, thread_sensitive=True
            )(component)

            if not comp_config:
                continue

            slaves = [
                s.id for s in component.slaves.all()
                if s.config.get('colonel') == self.colonel.id
            ]
            if slaves:
                comp_config['slaves'] = slaves
            if component.meta.get('options'):
                comp_config['options'] = component.meta['options']

            config_data['devices'][str(component.id)] = comp_config


        return config_data

    def on_mqtt_message(self, client, userdata, msg):
        drop_current_instance()
        try:
            payload = json.loads(msg.payload)

            if 'bulk_send' in payload:
                colonel_component_ids = [c['id'] for c in Component.objects.filter(
                    config__colonel=self.colonel.id,
                    gateway__in=Gateway.objects.filter(type=FleetGatewayHandler.uid),
                    id__in=[int(id) for id in payload['bulk_send'].keys()]
                ).values('id')]
                bulk_send_data = []
                for comp_id, value in payload['bulk_send'].items():
                    if int(comp_id) not in colonel_component_ids:
                        continue
                    bulk_send_data.append({'id': int(comp_id), 'val': value})
                if bulk_send_data:
                    asyncio.run(self.send_data({
                        'command': 'bulk_set',
                        'values': bulk_send_data
                    }))
                return

            obj = get_event_obj(payload)

            if obj == self.colonel:
                if payload.get('command') == 'update_firmware':
                    asyncio.run(self.firmware_update(payload['to_version']))
                elif payload.get('command') == 'update_config':
                    async def send_config():
                        config = await self.get_config_data()
                        await self.send_data({
                            'command': 'set_config', 'data': config
                        }, compress=self.colonel.type != 'room-sensor')
                    asyncio.run(send_config())
                elif payload.get('command') == 'discover':
                    print(f"SEND discover command for {payload['type']}")
                    asyncio.run(self.send_data(payload))

                elif payload.get('command') == 'finalize':
                    asyncio.run(self.send_data({
                        'command': 'finalize',
                        'data': payload.get('data', {})
                    }))
                else:
                    asyncio.run(self.send_data(payload))

            elif isinstance(obj, Component):
                if int(obj.config.get('colonel')) != self.colonel.id:
                    return
                if 'set_val' in payload:
                    asyncio.run(self.send_data({
                        'command': 'set_val',
                        'id': obj.id,
                        'val': payload['set_val']
                    }))
                if 'update_options' in payload:
                    asyncio.run(self.send_data({
                        'command': 'update_options',
                        'id': obj.id,
                        'options': payload['options']
                    }))

        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)


    async def receive(self, text_data=None, bytes_data=None):
        drop_current_instance()
        try:
            if text_data:
                data = json.loads(text_data)
                if 'ping' not in data:
                    print(f"{self.colonel}: {text_data}")
                if 'get_config' in data:
                    config = await self.get_config_data()
                    print("Send config: ", config)
                    await self.send_data({
                        'command': 'set_config', 'data': config
                    }, compress=self.colonel.type != 'room-sensor')
                elif 'comp' in data:
                    try:
                        try:
                            id=int(data['comp'])
                        except:
                            return

                        component = await sync_to_async(
                            Component.objects.get, thread_sensitive=True
                        )(id=id)

                        if 'val' in data:
                            def receive_val(data):
                                if data.get('actor'):
                                    fingerprint = Fingerprint.objects.filter(
                                        value=f"ttlock-{component.id}-{data.get('actor')}",
                                    ).first()
                                    component.change_init_fingerprint = fingerprint
                                try:
                                    alive = bool(data.get('alive', True))
                                    error_msg = None
                                    if not alive:
                                        error_msg = data.get('error_msg')
                                    component.controller._receive_from_device(
                                        data['val'], alive,
                                        data.get('battery_level'), error_msg
                                    )
                                except Exception as e:
                                    print(traceback.format_exc(),
                                          file=sys.stderr)
                            await sync_to_async(
                                receive_val, thread_sensitive=True
                            )(data)

                        if 'options' in data:
                            def receive_options(val):
                                component.meta['options'] = val
                                component.save()
                            await sync_to_async(
                                receive_options, thread_sensitive=True
                            )(data['options'])

                        if component.controller_uid == TTLock.uid:
                            if 'codes' in data or 'fingerprints' in data:
                                await sync_to_async(
                                    component.controller._receive_meta,
                                    thread_sensitive=True
                                )(data)

                    except Exception as e:
                        print(traceback.format_exc(), file=sys.stderr)

                elif 'discovery-result' in data:
                    def process_discovery_result():
                        self.gateway.refresh_from_db()
                        try:
                            self.gateway.process_discovery(data)
                        except Exception as e:
                            print(traceback.format_exc(), file=sys.stderr)

                    await sync_to_async(
                        process_discovery_result, thread_sensitive=True
                    )()

                elif 'dali-raw' in data:
                    from .custom_dali_operations import process_frame
                    await sync_to_async(process_frame, thread_sensitive=True)(
                        self.colonel.id, data['dali-raw'], data['data']
                    )

                elif 'va' in data and isinstance(data['va'], dict):
                    va = data['va']
                    if va.get('session') == 'finish':
                        if not self._va:
                            self._va = VoiceAssistantSession(self)
                        await self._va._end_session(cloud_also=True)

                elif 'wake-stats' in data and self.colonel.type == 'room-sensor':
                    def update_wake_stats():
                        va_component = Component.objects.filter(
                            config__colonel=self.colonel.id,
                            pk=data.get('id', 0)
                        ).select_related('zone').first()
                        self.colonel.wake_stats = data['wake-stats']
                        self.colonel.last_wake = timezone.now()
                        self.colonel.save()
                        return va_component
                    va_component = await sync_to_async(
                        update_wake_stats, thread_sensitive=True
                    )()
                    # Wake is only a hint; do not activate session until audio arrives.
                    if not self._va:
                        self._va = VoiceAssistantSession(self)
                    self._va.voice = data.get('voice', 'male')
                    self._va.zone = va_component.zone.id

            elif bytes_data:
                if self.colonel.type == 'room-sensor':
                    if bytes_data[0] == 32:
                        await self.capture_logs(bytes_data[1:])
                    else:
                        # Audio frame from Sentinel mic: 0x00 + s16le mono 16kHz
                        if not self._va:
                            self._va = VoiceAssistantSession(self)
                        # Strip prefix and feed
                        await self._va.on_audio_chunk(bytes_data[1:])
                else:
                    if bytes_data[0] == 32:
                        await self.capture_logs(bytes_data[1:])
                    else:
                        await self.capture_logs(bytes_data)

            await self.log_colonel_connected()
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)


    async def capture_logs(self, bytes_data):
        if not self.colonel_logger:
            await self.start_logger()

        for logline in bytes_data.decode(errors='replace').split('\n'):
            self.colonel_logger.log(logging.INFO, logline)


    async def log_colonel_connected(self):
        self.last_seen = time.time()

        def save_last_seen():
            self.colonel.socket_connected = True
            self.colonel.last_seen = timezone.now()
            self.colonel.save(update_fields=[
                'socket_connected', 'last_seen',
            ])

        await sync_to_async(save_last_seen, thread_sensitive=True)()

    async def send_data(self, data, compress=False):
        data = json.dumps(data)
        if compress:
            data = zlib.compress(data.encode())
            await self.send(bytes_data=data)
        else:
            await self.send(data)


    async def start_logger(self):
        self.colonel_logger = logging.getLogger(
            "Colonel Logger [%d]" % self.colonel.id
        )
        self.colonel_logger.handlers = []
        self.colonel_logger.propagate = False
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            "%m-%d %H:%M:%S"
        )
        formatter.converter = \
            lambda *args, **kwargs: timezone.localtime().timetuple()

        logfile_path = await sync_to_async(
            get_log_file_path, thread_sensitive=True
        )(self.colonel)
        file_handler = RotatingFileHandler(
            logfile_path, maxBytes=1024 * 1024,  # 1Mb
            backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        self.colonel_logger.addHandler(file_handler)
