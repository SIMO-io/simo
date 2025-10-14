import asyncio
import io
import json
import sys
import time
import traceback
import inspect
from datetime import timedelta

import websockets
import lameenc
from pydub import AudioSegment
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from asgiref.sync import sync_to_async

from simo.conf import dynamic_settings


class VoiceAssistantSession:
    """Manages a single Sentinel voice session for a connected Colonel.

    - Buffers PCM from device, finalizes utterance on VAD-like quiet.
    - Encodes PCM→MP3, calls Website WS, receives MP3 reply.
    - Decodes MP3→PCM and streams to device paced.
    - Manages `is_vo_active` lifecycle and Website start/finish HTTP hooks.
    - Cloud traffic is gated until arbitration grants winner status.
    """

    INACTIVITY_MS = 800
    MAX_UTTERANCE_SEC = 20
    PLAY_CHUNK_BYTES = 1024
    PLAY_CHUNK_INTERVAL = 0.032
    FOLLOWUP_SEC = 15
    CLOUD_RESPONSE_TIMEOUT_SEC = 60

    def __init__(self, consumer):
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
        self._cloud_gate = asyncio.Event()
        self._start_session_notified = False
        self._start_session_inflight = False
        self._prewarm_requested = False
        self._idle_task = asyncio.create_task(self._idle_watchdog())
        self._utterance_task = asyncio.create_task(self._utterance_watchdog())

    async def start_if_needed(self):
        if self.active:
            return
        self.active = True
        self.started_ts = time.time()
        # Ensure a fresh session starts gated until arbitration grants winner
        try:
            self._cloud_gate.clear()
        except Exception:
            pass
        # is_vo_active will be set by arbitration via open_as_winner

    async def on_audio_chunk(self, payload: bytes):
        if self.playing or self.awaiting_response:
            return
        await self.start_if_needed()
        if not getattr(self, '_rx_started', False):
            self._rx_started = True
            self._rx_start_ts = time.time()
            print("VA RX START (device→hub)")
        self.capture_buf.extend(payload)
        self.last_chunk_ts = time.time()
        self.last_rx_audio_ts = self.last_chunk_ts
        if len(self.capture_buf) > 2 * 16000 * self.MAX_UTTERANCE_SEC:
            await self._finalize_utterance()
            return
        if not self._finalizer_task or self._finalizer_task.done():
            self._finalizer_task = asyncio.create_task(self._finalizer_loop())

    async def _finalizer_loop(self):
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
        while True:
            try:
                await asyncio.sleep(0.1)
                if not self.active or self.awaiting_response or self.playing:
                    continue
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
        pcm = bytes(self.capture_buf)
        self.capture_buf.clear()
        self.last_chunk_ts = 0
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
        if self._cloud_task and not self._cloud_task.done():
            return
        self._cloud_task = asyncio.create_task(self._cloud_roundtrip_and_play(pcm))

    async def _cloud_roundtrip_and_play(self, pcm_bytes: bytes):
        try:
            await asyncio.wait_for(self._cloud_gate.wait(), timeout=30)
        except asyncio.TimeoutError:
            return
        self.awaiting_response = True
        try:
            # Ensure we have an MCP token before contacting Website
            if self.mcp_token is None:
                try:
                    await self.ensure_mcp_token()
                except Exception:
                    pass
            # Hard guard: abort if token still missing
            if self.mcp_token is None or not getattr(self.mcp_token, 'token', None):
                raise RuntimeError("Missing MCP token for Website WS call")

            if (not self._start_session_notified) and (not self._start_session_inflight):
                try:
                    await self._start_cloud_session()
                except Exception:
                    pass
                else:
                    self._start_session_notified = True
            mp3_bytes = await self._encode_mp3(pcm_bytes)
            if not mp3_bytes:
                return
            print(f"VA TX START (hub→website) mp3={len(mp3_bytes)}B")
            ws_url = "wss://simo.io/ws/voice-assistant/"
            hub_uid = await sync_to_async(lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True)()
            hub_secret = await sync_to_async(lambda: dynamic_settings['core__hub_secret'], thread_sensitive=True)()
            headers = {
                "hub-uid": hub_uid,
                "hub-secret": hub_secret,
                "instance-uid": self.c.instance.uid,
                "mcp-token": getattr(self.mcp_token, 'token', None),
                "voice": self.voice,
                "zone": self.zone
            }
            if not websockets:
                raise RuntimeError("websockets library not available")
            print(f"VA WS CONNECT {ws_url}")

            kwargs = {'max_size': 10 * 1024 * 1024}
            ws_params = inspect.signature(websockets.connect).parameters
            if 'additional_headers' in ws_params:
                kwargs['additional_headers'] = headers
            else:
                kwargs['extra_headers'] = headers
            async with websockets.connect(ws_url, **kwargs) as ws:
                print("VA WS OPEN")
                await ws.send(mp3_bytes)
                print("VA WS SENT (binary)")
                deadline = time.time() + self.CLOUD_RESPONSE_TIMEOUT_SEC
                mp3_reply = None
                streaming = False
                streaming_opus = False
                sent_total = 0
                stream_chunks = 0
                stream_start_ts = None
                opus_proc = None
                pcm_forward_task = None
                pcm_start_threshold = 8192  # ~256ms @ 16kHz s16le mono
                pcm_buffer = bytearray()
                ws_closed_ok = False
                ws_closed_error = False
                ws_closed_code = None
                pcm_stats_sent = 0
                async def _start_opus_decoder():
                    nonlocal opus_proc, pcm_forward_task, pcm_buffer, pcm_stats_sent
                    if opus_proc is not None:
                        return
                    try:
                        opus_proc = await asyncio.create_subprocess_exec(
                            'ffmpeg', '-v', 'error', '-i', 'pipe:0',
                            '-f', 's16le', '-ar', '16000', '-ac', '1', 'pipe:1',
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                    except Exception as e:
                        print('VA: failed to start ffmpeg for opus decode:', e, file=sys.stderr)
                        opus_proc = None
                        return

                    async def _pcm_forwarder():
                        nonlocal pcm_buffer, pcm_stats_sent, stream_start_ts, stream_chunks, sent_total
                        started = False
                        next_deadline = 0.0
                        try:
                            while True:
                                chunk = await opus_proc.stdout.read(4096)
                                if not chunk:
                                    break
                                pcm_buffer.extend(chunk)
                                if not started and len(pcm_buffer) >= pcm_start_threshold:
                                    started = True
                                    if stream_start_ts is None:
                                        stream_start_ts = time.time()
                                        print('VA RX STREAM START (website→hub) opus->pcm')
                                    next_deadline = time.time()
                                # forward in paced frames (~32ms for 1024B)
                                while started and len(pcm_buffer) >= self.PLAY_CHUNK_BYTES:
                                    frame = bytes(pcm_buffer[:self.PLAY_CHUNK_BYTES])
                                    del pcm_buffer[:self.PLAY_CHUNK_BYTES]
                                    try:
                                        # pacing
                                        samples = len(frame) // 2
                                        dt = samples / 16000.0
                                        sleep_for = next_deadline - time.time()
                                        if sleep_for > 0:
                                            await asyncio.sleep(sleep_for)
                                        await self.c.send(bytes_data=b"\x01" + frame)
                                        self.last_tx_audio_ts = time.time()
                                        sent_total += len(frame)
                                        stream_chunks += 1
                                        pcm_stats_sent += len(frame)
                                        if not self.playing:
                                            self.playing = True
                                        next_deadline += dt
                                    except Exception:
                                        return
                        except asyncio.CancelledError:
                            return
                        except Exception as e:
                            print('VA: opus decode forward error:', e, file=sys.stderr)
                        finally:
                            # flush tail with pacing
                            if started and pcm_buffer:
                                try:
                                    while pcm_buffer:
                                        take = min(self.PLAY_CHUNK_BYTES, len(pcm_buffer))
                                        frame = bytes(pcm_buffer[:take])
                                        del pcm_buffer[:take]
                                        samples = len(frame) // 2
                                        dt = samples / 16000.0
                                        sleep_for = next_deadline - time.time()
                                        if sleep_for > 0:
                                            await asyncio.sleep(sleep_for)
                                        await self.c.send(bytes_data=b"\x01" + frame)
                                        self.last_tx_audio_ts = time.time()
                                        sent_total += len(frame)
                                        stream_chunks += 1
                                        next_deadline += dt
                                except Exception:
                                    pass
                            pcm_buffer = bytearray()

                    pcm_forward_task = asyncio.create_task(_pcm_forwarder())
                while True:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        raise asyncio.TimeoutError("Cloud response timeout waiting for audio reply")
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        raise
                    except Exception as e:
                        # Connection closed or errored — inspect close code
                        try:
                            from websockets.exceptions import ConnectionClosed
                        except Exception:
                            ConnectionClosed = tuple()
                        if isinstance(e, ConnectionClosed):
                            try:
                                ws_closed_code = getattr(e, 'code', None)
                            except Exception:
                                ws_closed_code = None
                            if ws_closed_code == 1000 or self._end_after_playback:
                                ws_closed_ok = True
                            else:
                                ws_closed_error = True
                            break
                        # Any other exception (e.g., network reset) => treat as error end if streaming started
                        if streaming or streaming_opus:
                            ws_closed_error = True
                            break
                        # Otherwise, propagate to outer handler (will send error finish)
                        raise e
                    # Reset deadline on activity
                    deadline = time.time() + self.CLOUD_RESPONSE_TIMEOUT_SEC
                    if isinstance(msg, (bytes, bytearray)):
                        if streaming_opus:
                            # Feed opus bytes into decoder stdin
                            try:
                                if opus_proc is not None and opus_proc.stdin:
                                    opus_proc.stdin.write(msg)
                                    await opus_proc.stdin.drain()
                            except Exception as e:
                                print('VA: opus stdin write failed:', e, file=sys.stderr)
                                break
                            continue
                        if streaming:
                            if stream_start_ts is None:
                                stream_start_ts = time.time()
                                print("VA RX STREAM START (website→hub) pcm16le")
                            try:
                                await self.c.send(bytes_data=b"\x01" + bytes(msg))
                                self.last_tx_audio_ts = time.time()
                                sent_total += len(msg)
                                stream_chunks += 1
                                if not self.playing:
                                    self.playing = True
                            except Exception:
                                break
                            continue
                        # Not in streaming mode: assume single MP3 blob
                        mp3_reply = bytes(msg)
                        print(f"VA RX START (website→hub) mp3={len(mp3_reply)}B")
                        break
                    else:
                        try:
                            data = json.loads(msg)
                        except Exception:
                            data = None
                        if isinstance(data, dict):
                            print(f"VA WS CTRL {data}")
                            # Streaming handshake
                            audio = data.get('audio') if isinstance(data.get('audio'), dict) else None
                            if audio and audio.get('format') == 'pcm16le':
                                if int(audio.get('sr', 0)) != 16000:
                                    print("VA: unsupported stream rate, expecting 16k; ignoring stream")
                                else:
                                    streaming = True
                                    continue
                            if audio and audio.get('format') == 'opus':
                                # Start opus->pcm decoder
                                await _start_opus_decoder()
                                if opus_proc is not None:
                                    streaming_opus = True
                                    continue
                            if data.get('session') == 'finish':
                                self._end_after_playback = True
                                try:
                                    await self.c.send_data(
                                        {'command': 'va', 'session': 'finish',
                                         'status': data.get('status', 'success')}
                                    )
                                except Exception:
                                    pass
                            if 'reasoning' in data:
                                try:
                                    await self.c.send_data({'command': 'va', 'reasoning': bool(data['reasoning'])})
                                except Exception:
                                    pass

            if mp3_reply:
                pcm_out = await self._decode_mp3(mp3_reply)
                if pcm_out:
                    await self._play_to_device(pcm_out)
                    if self._end_after_playback:
                        await self._end_session(cloud_also=False)
                        self._end_after_playback = False
                elif self._end_after_playback:
                    await self._end_session(cloud_also=False)
                    self._end_after_playback = False
            elif streaming:
                # Streaming ended; finalize playback stats
                try:
                    elapsed = time.time() - (stream_start_ts or time.time())
                    audio_sec = (sent_total // 2) / 16000.0 if sent_total else 0.0
                    print(f"VA RX STREAM END (website→hub) sent≈{sent_total}B chunks={stream_chunks} elapsed={elapsed:.2f}s audio={audio_sec:.2f}s ratio={elapsed/audio_sec if audio_sec else 0:.2f}")
                except Exception:
                    pass
                self.playing = False
                if self._end_after_playback:
                    await self._end_session(cloud_also=False)
                    self._end_after_playback = False
            elif streaming_opus:
                # Close decoder stdin and let forwarder drain fully
                try:
                    if opus_proc and opus_proc.stdin:
                        try:
                            opus_proc.stdin.close()
                        except Exception:
                            pass
                except Exception:
                    pass
                # Allow forwarder to finish without artificially short timeouts
                if pcm_forward_task:
                    try:
                        await pcm_forward_task
                    except Exception:
                        try:
                            pcm_forward_task.cancel()
                        except Exception:
                            pass
                # Ensure process exits cleanly
                try:
                    if opus_proc:
                        try:
                            await opus_proc.wait()
                        except Exception:
                            opus_proc.kill()
                except Exception:
                    pass
                try:
                    elapsed = time.time() - (stream_start_ts or time.time())
                    audio_sec = (sent_total // 2) / 16000.0 if sent_total else 0.0
                    print(f"VA RX OPUS END sent≈{sent_total}B chunks={stream_chunks} elapsed={elapsed:.2f}s audio={audio_sec:.2f}s ratio={elapsed/audio_sec if audio_sec else 0:.2f}")
                except Exception:
                    pass
                self.playing = False
                if self._end_after_playback:
                    await self._end_session(cloud_also=False)
                    self._end_after_playback = False
            elif self._end_after_playback:
                await self._end_session(cloud_also=False)
                self._end_after_playback = False
            elif ws_closed_error:
                # Website closed with a non-1000 code: finish with error immediately
                try:
                    await self.c.send_data({'command': 'va', 'session': 'finish', 'status': 'error'})
                except Exception:
                    pass
                await self._end_session(cloud_also=True)
            elif ws_closed_ok:
                # Normal close without explicit finish: keep session open for follow-up.
                pass
        except Exception as e:
            print("VA WS ERROR:", e, file=sys.stderr)
            print("VA: Cloud roundtrip failed\n", traceback.format_exc(), file=sys.stderr)
            try:
                await self.c.send_data({'command': 'va', 'session': 'finish', 'status': 'error'})
            except Exception:
                pass
            await self._end_session(cloud_also=True)
        finally:
            self.awaiting_response = False
            if self.active and not self.playing and not self._end_after_playback:
                await self._start_followup_timer()

    async def _encode_mp3(self, pcm_bytes: bytes):
        if lameenc is None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self._encode_mp3_pydub(pcm_bytes))
        def _enc():
            enc = lameenc.Encoder()
            enc.set_bit_rate(48)
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
        audio = AudioSegment(data=pcm_bytes, sample_width=2, frame_rate=16000, channels=1)
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
        self.playing = True
        try:
            print(f"VA TX START (hub→device) pcm={len(pcm_bytes)}B")
            view = memoryview(pcm_bytes)
            total = len(view)
            pos = 0
            sent_total = 0
            next_deadline = time.time()
            fudge = 0.0
            pace_start = time.time()
            chunks = 0
            warmup = 1
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
                    samples = len(chunk) // 2
                    dt = samples / 16000.0
                    next_deadline += dt
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

    async def _start_followup_timer(self):
        if self._followup_task and not self._followup_task.done():
            self._followup_task.cancel()
        async def _timer():
            try:
                await asyncio.sleep(self.FOLLOWUP_SEC)
                if self.active and not self.playing and not self.awaiting_response and not self.capture_buf:
                    await self._end_session(cloud_also=False)
            except asyncio.CancelledError:
                return
        self._followup_task = asyncio.create_task(_timer())

    async def _idle_watchdog(self):
        IDLE_SEC = 120
        while True:
            try:
                await asyncio.sleep(2)
                if not self.active:
                    continue
                last_audio = max(self.last_rx_audio_ts or 0, self.last_tx_audio_ts or 0)
                if not last_audio:
                    continue
                if (time.time() - last_audio) > IDLE_SEC:
                    print("VA idle timeout reached (120s), ending session")
                    await self._end_session(cloud_also=True)
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    async def _set_is_vo_active(self, flag: bool):
        def _execute():
            from simo.mcp_server.models import InstanceAccessToken
            with transaction.atomic():
                if flag:
                    self.mcp_token, _ = InstanceAccessToken.objects.get_or_create(
                        instance=self.c.colonel.instance, date_expired=None, issuer='sentinel'
                    )
                else:
                    # Do NOT eagerly expire the token here; it may be in use
                    # by Website prewarm or by the chosen winner on this instance.
                    # Cleanup is handled by a scheduled task (1-day expiry).
                    self.mcp_token = None
                self.c.colonel.is_vo_active = flag
                self.c.colonel.save(update_fields=['is_vo_active'])
        await sync_to_async(_execute, thread_sensitive=True)()

    async def _finish_cloud_session(self):
        try:
            import requests
        except Exception:
            return
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
        for delay in (0, 2, 5):
            if delay:
                await asyncio.sleep(delay)
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, _post)
            if resp is not None and getattr(resp, 'status_code', None) in (200, 204):
                return

    async def _start_cloud_session(self):
        try:
            import requests
        except Exception:
            return
        hub_uid = await sync_to_async(lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True)()
        hub_secret = await sync_to_async(lambda: dynamic_settings['core__hub_secret'], thread_sensitive=True)()
        url = 'https://simo.io/ai/start-session/'
        payload = {
            'hub_uid': hub_uid,
            'hub_secret': hub_secret,
            'instance_uid': self.c.instance.uid,
            'mcp-token': getattr(self.mcp_token, 'token', None),
            'zone': self.zone,
        }
        def _post():
            try:
                return requests.post(url, json=payload, timeout=5)
            except Exception:
                return None
        for delay in (0, 2):
            if delay:
                await asyncio.sleep(delay)
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, _post)
            if resp is not None and getattr(resp, 'status_code', None) in (200, 204):
                return

    async def _end_session(self, cloud_also: bool = False):
        self.active = False
        self.capture_buf.clear()
        self.last_chunk_ts = 0
        self.last_rx_audio_ts = 0
        self.last_tx_audio_ts = 0
        # Reset prewarm/session flags so next VA session can prewarm again
        self._start_session_notified = False
        self._start_session_inflight = False
        self._prewarm_requested = False
        # Close cloud gate so subsequent sessions don't bypass arbitration
        try:
            self._cloud_gate.clear()
        except Exception:
            pass
        for t in (self._finalizer_task, self._cloud_task, self._play_task, self._followup_task):
            if t and not t.done():
                t.cancel()
        self._finalizer_task = self._cloud_task = self._play_task = self._followup_task = None
        await self._set_is_vo_active(False)
        if cloud_also:
            await self._finish_cloud_session()

    async def shutdown(self):
        await self._end_session(cloud_also=False)

    async def open_as_winner(self):
        if not self.active:
            self.active = True
        await self._set_is_vo_active(True)
        try:
            self._cloud_gate.set()
        except Exception:
            pass
        # Best-effort notify Website immediately at session start
        # Do it in background so we don't block audio pipeline
        if not self._start_session_notified:
            asyncio.create_task(self._start_cloud_session_safe())

    async def _start_cloud_session_safe(self):
        if self._start_session_inflight:
            return
        self._start_session_inflight = True
        try:
            await self._start_cloud_session()
        except Exception:
            pass
        else:
            self._start_session_notified = True
        finally:
            self._start_session_inflight = False

    async def ensure_mcp_token(self):
        """Ensure self.mcp_token exists without toggling is_vo_active."""
        def _execute():
            from simo.mcp_server.models import InstanceAccessToken
            token, _ = InstanceAccessToken.objects.get_or_create(
                instance=self.c.colonel.instance, date_expired=None, issuer='sentinel'
            )
            return token
        self.mcp_token = await sync_to_async(_execute, thread_sensitive=True)()

    async def prewarm_on_first_audio(self):
        """Called on the first audio frames to notify Website ASAP, before winners."""
        if self._start_session_notified or self._start_session_inflight or self._prewarm_requested:
            return
        self._prewarm_requested = True
        try:
            if self.mcp_token is None:
                await self.ensure_mcp_token()
        except Exception:
            pass
        # Fire and forget; internal flag will be set only on success
        asyncio.create_task(self._start_cloud_session_safe())

    async def reject_busy(self):
        try:
            await self.c.send_data({'command': 'va', 'session': 'finish', 'status': 'busy'})
        except Exception:
            pass
        await self._end_session(cloud_also=False)


class VoiceAssistantArbitrator:
    """Encapsulates instance-wide arbitration and busy handling for a consumer."""

    ARBITRATION_WINDOW_MS = 900
    ARBITRATION_RANK_FIELD = 'avg2p5_s'  # options: score|snr_db|avg2p5_s|peak2p5_s|energy_1s
    WINNER_CONFIRM_GRACE_MS = 1500

    def __init__(self, consumer, session: VoiceAssistantSession):
        self.c = consumer
        self.session = session
        self._arb_started = False
        self._arb_task = None
        self._busy_rejected = False
        self._last_active_scan = 0.0

    async def maybe_reject_busy(self) -> bool:
        now_ts = time.time()
        if (not self._busy_rejected) and (now_ts - self._last_active_scan) > 0.3:
            self._last_active_scan = now_ts
            def _has_active_other():
                return (self.c.colonel.__class__.objects
                        .filter(instance=self.c.instance, is_vo_active=True)
                        .exclude(id=self.c.colonel.id).exists())
            try:
                active_other = await sync_to_async(_has_active_other, thread_sensitive=True)()
            except Exception:
                active_other = False
            if active_other:
                self._busy_rejected = True
                await self.session.reject_busy()
                return True
        return False

    def start_window_if_needed(self):
        # Start a new arbitration window if none is currently running.
        # This allows a fresh window per VA session rather than only once
        # per connection, ensuring the cloud gate can reopen after session end.
        if self._arb_task and not self._arb_task.done():
            return
        self._arb_started = True
        self._arb_task = asyncio.create_task(self._decide_after_window())

    async def _decide_after_window(self):
        try:
            await asyncio.sleep(self.ARBITRATION_WINDOW_MS / 1000.0)
        except asyncio.CancelledError:
            return
        await self._decide_arbitration()

    async def _decide_arbitration(self):
        try:
            await sync_to_async(self.c.colonel.refresh_from_db, thread_sensitive=True)()
            if getattr(self.c.colonel, 'is_vo_active', False):
                await self.session.open_as_winner()
                return

            def _other_active():
                return (self.c.colonel.__class__.objects
                        .filter(instance=self.c.instance, is_vo_active=True)
                        .exclude(id=self.c.colonel.id).exists())
            if await sync_to_async(_other_active, thread_sensitive=True)():
                if not self._busy_rejected:
                    self._busy_rejected = True
                    await self.session.reject_busy()
                return

            field = getattr(self, 'ARBITRATION_RANK_FIELD', 'avg2p5_s')
            now = timezone.now()
            window_start = now - timedelta(milliseconds=self.ARBITRATION_WINDOW_MS)

            def _get_candidates():
                qs = self.c.colonel.__class__.objects.filter(
                    instance=self.c.instance,
                    last_wake__gte=window_start,
                )
                lst = []
                for col in qs:
                    stats = getattr(col, 'wake_stats', None) or {}
                    val = stats.get(field, -1)
                    lst.append((col.id, val))
                return lst

            cand = await sync_to_async(_get_candidates, thread_sensitive=True)()
            if not cand:
                await self.session.open_as_winner()
                return
            cand.sort(key=lambda t: (t[1], -t[0]))
            chosen_id, _ = cand[-1]

            if chosen_id == self.c.colonel.id:
                @transaction.atomic
                def _promote_self():
                    if self.c.colonel.__class__.objects.select_for_update().filter(
                        instance=self.c.instance, is_vo_active=True
                    ).exists():
                        return False
                    cc = self.c.colonel.__class__.objects.select_for_update().get(id=self.c.colonel.id)
                    if not cc.is_vo_active:
                        cc.is_vo_active = True
                        cc.save(update_fields=['is_vo_active'])
                    return True
                ok = await sync_to_async(_promote_self, thread_sensitive=True)()
                if ok:
                    await self.session.open_as_winner()
                else:
                    if not self._busy_rejected:
                        self._busy_rejected = True
                        await self.session.reject_busy()
                return

            deadline = time.time() + (self.WINNER_CONFIRM_GRACE_MS / 1000.0)
            while time.time() < deadline:
                def _chosen_active():
                    return self.c.colonel.__class__.objects.filter(
                        id=chosen_id, instance=self.c.instance, is_vo_active=True
                    ).exists()
                def _any_other_active():
                    return self.c.colonel.__class__.objects.filter(
                        instance=self.c.instance, is_vo_active=True
                    ).exclude(id=self.c.colonel.id).exists()
                chosen_active = await sync_to_async(_chosen_active, thread_sensitive=True)()
                if chosen_active:
                    if not self._busy_rejected:
                        self._busy_rejected = True
                        await self.session.reject_busy()
                    return
                if await sync_to_async(_any_other_active, thread_sensitive=True)():
                    if not self._busy_rejected:
                        self._busy_rejected = True
                        await self.session.reject_busy()
                    return
                await asyncio.sleep(0.1)

            @transaction.atomic
            def _promote_self_fallback():
                if self.c.colonel.__class__.objects.select_for_update().filter(
                    instance=self.c.instance, is_vo_active=True
                ).exists():
                    return False
                cc = self.c.colonel.__class__.objects.select_for_update().get(id=self.c.colonel.id)
                if not cc.is_vo_active:
                    cc.is_vo_active = True
                    cc.save(update_fields=['is_vo_active'])
                return True
            ok = await sync_to_async(_promote_self_fallback, thread_sensitive=True)()
            if ok:
                await self.session.open_as_winner()
            else:
                if not self._busy_rejected:
                    self._busy_rejected = True
                    await self.session.reject_busy()
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)
            try:
                await self.session.open_as_winner()
            except Exception:
                pass
