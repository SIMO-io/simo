import asyncio
import io
import json
import sys
import time
import traceback
import inspect
from collections import deque
from datetime import timedelta

import websockets
import lameenc
from pydub import AudioSegment
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from asgiref.sync import sync_to_async
import asyncio.subprocess

from simo.conf import dynamic_settings
from simo.core.utils import adpcm4

MIC_CHANNEL_ID = 0
SPK_CHANNEL_ID = 1
ADPCM_FRAME_FLAG = 0x80
ADPCM_HEADER_SIZE = 6


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
    # Bias outbound audio pacing faster than
    # theoretical real-time so that encode + network
    # overhead does not underfeed the Sentinel.
    # 0.50 → target interval ≈ 16 ms for a 32 ms
    # chunk; roughly 2x real-time, leaving the
    # device buffer comfortably filled without
    # blasting everything in 1–2 seconds.
    TX_PACE_BIAS = 0.50
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
        self._tx_samples_per_chunk = self.PLAY_CHUNK_BYTES // 2
        # ADPCM encoder state for outbound speaker stream (hub→Sentinel)
        self._tx_adpcm_state = adpcm4.ImaAdpcmState()
        self._tx_adpcm_buf = bytearray((self._tx_samples_per_chunk + 1) // 2)
        self._tx_packet_buf = bytearray(ADPCM_HEADER_SIZE + len(self._tx_adpcm_buf))
        # Outbound stream timing state (PCM16 -> Sentinel)
        self._tx_stream_deadline = None
        self._tx_stream_prefill_sent = 0
        self._tx_stream_play_chunks = 0
        self._tx_debug_seq = 0
        self._tx_last_send_ts = None
        self._tx_clock_base = None
        self._tx_clock_frames = 0
        self._tx_clock_target = None
        self._tx_max_lag_frames = 6
        # Number of frames to prefill before starting
        # paced playback to the Sentinel.
        self._tx_prefill_chunks = 20
        self.voice = 'male'
        self.zone = None
        self._cloud_gate = asyncio.Event()
        self._start_session_notified = False
        self._start_session_inflight = False
        self._prewarm_requested = False
        self._idle_task = asyncio.create_task(self._idle_watchdog())
        self._utterance_task = asyncio.create_task(self._utterance_watchdog())
        # Per-instance watchdog that clears stale VO-active
        # flags so no Sentinel can hold ownership forever if
        # its last wake is old.
        try:
            inst = getattr(self.c, 'instance', None)
            if inst is not None and not hasattr(inst, '_vo_watchdog_started'):
                setattr(inst, '_vo_watchdog_started', True)
                asyncio.create_task(self._vo_active_watchdog())
        except Exception:
            pass

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
                opus_sr = 24000
                pcm_stream_buffer = bytearray()
                opus_stream_buffer = bytearray()
                stream_queue = None
                stream_consumer = None
                stream_done = asyncio.Event()
                opus_pipeline = None
                ws_closed_ok = False
                ws_closed_error = False
                ws_closed_code = None
                async def _stream_consumer():
                    """Pace streaming audio to device using a global clock.

                    - Sends an initial prefill of ``_tx_prefill_chunks`` frames
                      as soon as they are available.
                    - Then, on a 10ms tick, compares wall-clock time against
                      the ideal schedule (32 ms per frame) and sends as many
                      frames as needed to catch up.
                    - Frames are prepared upstream into ``stream_queue`` by
                      the decode pipeline so they are ready when the clock
                      ticks.
                    """
                    nonlocal stream_queue
                    self._reset_stream_throttle(reason='stream_consumer')
                    frame_bytes = self.PLAY_CHUNK_BYTES
                    samples_per_frame = frame_bytes // 2  # 16-bit mono
                    frame_interval = samples_per_frame / 16000.0  # 32 ms
                    prefill = self._tx_prefill_chunks

                    frames = deque()
                    producer_done = False

                    async def _producer():
                        nonlocal producer_done
                        try:
                            while True:
                                chunk = await stream_queue.get()
                                if chunk is None:
                                    producer_done = True
                                    break
                                if chunk:
                                    frames.append(chunk)
                        finally:
                            producer_done = True

                    prod_task = asyncio.create_task(_producer())

                    try:
                        # Initial prefill: send up to ``prefill`` frames as
                        # soon as they are available.
                        frames_sent = 0
                        while frames_sent < prefill:
                            while not frames:
                                if producer_done:
                                    break
                                await asyncio.sleep(0.005)
                            if not frames:
                                break
                            chunk = frames.popleft()
                            samples = len(chunk) // 2
                            now = time.monotonic()
                            self._tx_stream_prefill_sent += 1
                            wait_info = {
                                'stage': 'prefill',
                                'interval': frame_interval,
                                'target': now,
                                'prefill_seq': self._tx_stream_prefill_sent,
                                'play_seq': 0,
                            }
                            ok = await self._send_pcm_frame(chunk, wait_info=wait_info)
                            if not ok:
                                return
                            frames_sent += 1

                        if frames_sent == 0:
                            return

                        # Anchor clock after prefill
                        start = time.monotonic()
                        # Number of logical frames that should have been sent
                        # by ``start`` (including the prefill).
                        base_frames = frames_sent

                        while True:
                            if producer_done and not frames:
                                break
                            await asyncio.sleep(0.01)
                            now = time.monotonic()
                            elapsed = now - start
                            ideal_frames = int(elapsed / frame_interval) + base_frames
                            # Send as many frames as needed to catch up to
                            # the ideal schedule, limited by what we have.
                            while frames_sent < ideal_frames and frames:
                                chunk = frames.popleft()
                                samples = len(chunk) // 2
                                play_seq = frames_sent - base_frames + 1
                                target_time = start + ((frames_sent - base_frames) * frame_interval)
                                lag = now - target_time
                                wait_info = {
                                    'stage': 'play',
                                    'sleep': 0.0,
                                    'interval': frame_interval,
                                    'target': target_time,
                                    'prefill_seq': self._tx_stream_prefill_sent,
                                    'play_seq': play_seq,
                                    'lag': lag,
                                }
                                ok = await self._send_pcm_frame(chunk, wait_info=wait_info)
                                if not ok:
                                    return
                                frames_sent += 1
                    finally:
                        try:
                            prod_task.cancel()
                        except Exception:
                            pass
                        stream_done.set()

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
                            if opus_pipeline:
                                await self._write_opus_stream(opus_pipeline, msg)
                            else:
                                opus_stream_buffer.extend(msg)
                            continue
                        if streaming:
                            if stream_queue is None:
                                continue
                            pcm_stream_buffer.extend(msg)
                            while len(pcm_stream_buffer) >= self.PLAY_CHUNK_BYTES:
                                chunk = bytes(pcm_stream_buffer[:self.PLAY_CHUNK_BYTES])
                                del pcm_stream_buffer[:self.PLAY_CHUNK_BYTES]
                                await stream_queue.put(chunk)
                            continue
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
                                    pcm_stream_buffer.clear()
                                    stream_queue = asyncio.Queue(32)
                                    stream_done.clear()
                                    stream_consumer = asyncio.create_task(_stream_consumer())
                                    print(
                                        f"VA STREAM START format=pcm16le chunksz={self.PLAY_CHUNK_BYTES}B prefill={self._tx_prefill_chunks}"
                                    )
                                    continue
                            if audio and audio.get('format') == 'opus':
                                # Buffer the entire Opus stream in memory and
                                # decode it to PCM in one shot once the
                                # website finishes sending. This ensures all
                                # PCM frames are ready before we start
                                # pacing them to the device.
                                streaming_opus = True
                                opus_sr = int(audio.get('sr', 24000) or 24000)
                                opus_stream_buffer.clear()
                                stream_queue = None
                                stream_done.clear()
                                stream_consumer = None
                                opus_pipeline = None
                                print(
                                    f"VA STREAM START format=opus sr={opus_sr} chunksz={self.PLAY_CHUNK_BYTES}B prefill={self._tx_prefill_chunks}"
                                )
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
                if stream_queue is None:
                    await self._play_to_device(bytes(pcm_stream_buffer))
                else:
                    if pcm_stream_buffer:
                        await stream_queue.put(bytes(pcm_stream_buffer))
                    await stream_queue.put(None)
                    if stream_consumer:
                        await stream_done.wait()
                if self._end_after_playback:
                    await self._end_session(cloud_also=False)
                    self._end_after_playback = False
            elif streaming_opus:
                if opus_pipeline:
                    await self._stop_opus_stream_decoder(opus_pipeline)
                    opus_pipeline = None
                    if stream_queue is not None:
                        await stream_queue.put(None)
                        if stream_consumer:
                            await stream_done.wait()
                else:
                    pcm_out = await self._decode_opus_stream(bytes(opus_stream_buffer), opus_sr)
                    if stream_queue is None or not pcm_out:
                        if pcm_out:
                            await self._play_to_device(pcm_out)
                    else:
                        for offset in range(0, len(pcm_out), self.PLAY_CHUNK_BYTES):
                            chunk = pcm_out[offset:offset + self.PLAY_CHUNK_BYTES]
                            if not chunk:
                                continue
                            await stream_queue.put(chunk)
                        await stream_queue.put(None)
                        if stream_consumer:
                            await stream_done.wait()
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
            try:
                if 'opus_pipeline' in locals() and locals().get('opus_pipeline'):
                    await self._stop_opus_stream_decoder(locals().get('opus_pipeline'))
            except Exception:
                pass
            if self.active and not self.playing and not self._end_after_playback:
                await self._start_followup_timer()

    async def _send_pcm_frame(self, pcm_chunk: bytes, wait_info=None) -> bool:
        if not pcm_chunk or (len(pcm_chunk) & 1):
            return False
        samples = len(pcm_chunk) // 2
        if samples <= 0:
            return False
        # ADPCM4 framing for Sentinel speaker channel:
        #   byte 0: channel id | ADPCM flag (0x80)
        #   bytes 1–2: sample count (little-endian)
        #   bytes 3–4: predictor (little-endian, signed 16-bit)
        #   byte 5: step index (0..88)
        #   bytes 6+: ADPCM nibbles
        state = self._tx_adpcm_state
        start_pred = state.predictor
        start_idx = state.index
        encoded = adpcm4.encode(pcm_chunk, state, self._tx_adpcm_buf)
        enc_len = len(encoded)
        if not enc_len:
            return False
        packet = self._tx_packet_buf
        packet[0] = SPK_CHANNEL_ID | ADPCM_FRAME_FLAG
        packet[1] = samples & 0xFF
        packet[2] = (samples >> 8) & 0xFF
        pred = start_pred & 0xFFFF
        packet[3] = pred & 0xFF
        packet[4] = (pred >> 8) & 0xFF
        packet[5] = start_idx & 0xFF
        packet[ADPCM_HEADER_SIZE:ADPCM_HEADER_SIZE + enc_len] = encoded
        frame = bytes(packet[:ADPCM_HEADER_SIZE + enc_len])
        seq = self._tx_debug_seq
        self._tx_debug_seq += 1
        try:
            send_start_wall = time.time()
            send_start_mon = time.monotonic()
            actual_dt = 0.0
            if self._tx_last_send_ts is not None:
                actual_dt = send_start_wall - self._tx_last_send_ts
            self._tx_last_send_ts = send_start_wall
            drift = 0.0
            stage = 'raw'
            sleep = 0.0
            if wait_info:
                stage = wait_info.get('stage', 'raw')
                sleep = wait_info.get('sleep', 0.0)
                target = wait_info.get('target')
                if stage == 'play' and target is not None:
                    drift = send_start_mon - target
            self._log_tx_frame(stage, seq, samples, enc_len, sleep, drift, actual_dt, wait_info)
            await self.c.send(bytes_data=frame)
            self.last_tx_audio_ts = time.time()
            return True
        except Exception:
            return False

    async def _send_pcm_frames(self, pcm_bytes: bytes):
        """Send PCM to the device using a single strict-clock path.

        Behavior:
        - Slice ``pcm_bytes`` into PLAY_CHUNK_BYTES frames.
        - Immediately prefill up to ``_tx_prefill_chunks`` frames.
        - Then schedule each remaining frame against a monotonically
          increasing target timestamp spaced by ``PLAY_CHUNK_INTERVAL``
          seconds, sleeping precisely until the next target. This
          keeps long responses aligned to a single global clock
          instead of accumulating per-frame drift.
        """
        if not pcm_bytes:
            return 0, 0

        frame_bytes = self.PLAY_CHUNK_BYTES
        # Target interval per PCM frame, with a
        # slight bias to compensate for Python
        # encode + websocket overhead.
        frame_interval = self.PLAY_CHUNK_INTERVAL * self.TX_PACE_BIAS

        view = memoryview(pcm_bytes)
        total = len(view)
        if total <= 0:
            return 0, 0

        # Build a simple list of frames so we can prefill and then walk
        # them with a global clock.
        frames = []
        for offset in range(0, total, frame_bytes):
            chunk = bytes(view[offset:offset + frame_bytes])
            if chunk:
                frames.append(chunk)

        if not frames:
            return 0, 0

        self._reset_stream_throttle(reason='pcm_strict')

        sent = 0
        chunks = 0

        # Initial prefill: burst-send up to ``_tx_prefill_chunks``
        # frames so the Sentinel can build its jitter buffer before we
        # start pacing playback.
        prefill_target = min(self._tx_prefill_chunks, len(frames))
        for idx in range(prefill_target):
            chunk = frames[idx]
            now_mon = time.monotonic()
            self._tx_stream_prefill_sent = idx + 1
            wait_info = {
                'stage': 'prefill',
                'interval': frame_interval,
                'target': now_mon,
                'prefill_seq': self._tx_stream_prefill_sent,
                'play_seq': 0,
            }
            ok = await self._send_pcm_frame(chunk, wait_info=wait_info)
            if not ok:
                return sent, chunks
            sent += len(chunk)
            chunks += 1

        # If the whole clip fit into the prefill window, we are done.
        if prefill_target >= len(frames):
            return sent, chunks

        # Strict-clock playback for remaining frames. We maintain a
        # target timestamp that advances by exactly ``frame_interval``
        # for each logical frame and sleep until this target before
        # sending the next frame. Any processing overhead is absorbed
        # by shortening the subsequent sleep so that the overall period
        # stays ~frame_interval on average.
        next_target = time.monotonic() + frame_interval
        frames_sent = prefill_target

        while frames_sent < len(frames):
            now = time.monotonic()
            sleep_for = next_target - now
            if sleep_for > 0:
                try:
                    await asyncio.sleep(sleep_for)
                except asyncio.CancelledError:
                    return sent, chunks

            # Update actual send time and drift relative to the target
            send_target = next_target
            now_mon = time.monotonic()
            lag = now_mon - send_target

            chunk = frames[frames_sent]
            play_seq = frames_sent - prefill_target + 1
            self._tx_stream_play_chunks = play_seq
            wait_info = {
                'stage': 'play',
                'sleep': 0.0,
                'interval': frame_interval,
                'target': send_target,
                'prefill_seq': prefill_target,
                'play_seq': play_seq,
                'lag': lag,
            }
            ok = await self._send_pcm_frame(chunk, wait_info=wait_info)
            if not ok:
                return sent, chunks
            sent += len(chunk)
            chunks += 1
            frames_sent += 1

            # Advance target for the next frame relative to the
            # previous target so overall drift does not accumulate.
            next_target += frame_interval

        return sent, chunks

    def _reset_stream_throttle(self, reason=None):
        self._tx_stream_deadline = None
        self._tx_stream_prefill_sent = 0
        self._tx_stream_play_chunks = 0
        self._tx_debug_seq = 0
        self._tx_last_send_ts = None
        self._tx_clock_base = None
        self._tx_clock_frames = 0
        self._tx_clock_target = None
        if reason:
            try:
                print(f"VA STREAM THROTTLE reset reason={reason}")
            except Exception:
                pass

    async def _complete_frame_slot(self, info):
        if not info:
            return
        stage = info.get('stage')
        if stage == 'prefill' and self._tx_stream_prefill_sent >= self._tx_prefill_chunks:
            base = time.monotonic()
            self._tx_clock_base = base
            self._tx_clock_target = base
            self._tx_clock_frames = 0
            return
        if stage != 'play':
            return
        interval = info.get('interval', self.PLAY_CHUNK_INTERVAL)
        target = info.get('target')
        if target is None:
            target = time.monotonic()
        next_target = target + interval
        self._tx_clock_target = next_target
        now = time.monotonic()
        sleep_for = next_target - now
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    async def _wait_for_stream_slot(self, samples: int):
        if samples <= 0:
            return {'stage': 'noop', 'interval': 0.0, 'target': None}
        # Nominal interval for these samples (at 16 kHz), with a
        # slight bias so we send just a bit faster than strict
        # real-time. This helps keep the Sentinel's playback buffer
        # from drifting empty due to small scheduler delays.
        interval = (samples / 16000.0) * self.TX_PACE_BIAS
        now = time.monotonic()
        if self._tx_stream_prefill_sent < self._tx_prefill_chunks:
            self._tx_stream_prefill_sent += 1
            self._tx_clock_base = None
            self._tx_clock_frames = 0
            self._tx_clock_target = None
            self._tx_stream_play_chunks = 0
            return {
                'stage': 'prefill',
                'interval': interval,
                'target': now,
                'prefill_seq': self._tx_stream_prefill_sent,
                'play_seq': self._tx_clock_frames,
            }
        if self._tx_clock_base is None:
            self._tx_clock_base = now
            self._tx_clock_frames = 0
            self._tx_clock_target = now
        target = self._tx_clock_target or now
        lag = now - target
        max_lag = self._tx_max_lag_frames * interval
        if lag > max_lag:
            skips = int(lag // interval) - self._tx_max_lag_frames
            if skips < 1:
                skips = 1
            self._tx_clock_frames += skips
            self._tx_clock_target = target + skips * interval
            self._tx_stream_play_chunks = self._tx_clock_frames
            return {
                'stage': 'drop',
                'interval': interval,
                'target': self._tx_clock_target,
                'prefill_seq': self._tx_stream_prefill_sent,
                'play_seq': self._tx_clock_frames,
                'lag': lag,
            }
        self._tx_clock_frames += 1
        self._tx_stream_play_chunks = self._tx_clock_frames
        return {
            'stage': 'play',
            'sleep': 0.0,
            'interval': interval,
            'target': target,
            'prefill_seq': self._tx_stream_prefill_sent,
            'play_seq': self._tx_clock_frames,
            'lag': lag,
        }

    def _log_tx_frame(self, stage, seq, samples, enc_len, sleep, drift, actual_dt, wait_info):
        # Throttle logs to avoid overwhelming the console. Always log
        # prefill frames; for steady-state playback, log every 16th
        # frame and any frame with unusually high drift.
        try:
            if stage == 'play':
                if seq % 16 != 0 and (drift is None or abs(drift) < 0.050):
                    return
            parts = [
                f"VA TX FRAME stage={stage}",
                f"seq={seq}",
                f"samples={samples}",
                f"enc={enc_len}B",
                f"sleep_ms={sleep * 1000:.1f}",
                f"drift_ms={drift * 1000:.1f}",
                f"actual_dt_ms={actual_dt * 1000:.1f}",
                f"prefill_sent={self._tx_stream_prefill_sent}",
                f"play_chunks={self._tx_stream_play_chunks}",
            ]
            if wait_info:
                if wait_info.get('prefill_seq') is not None:
                    parts.append(f"prefill_seq={wait_info['prefill_seq']}")
                if wait_info.get('play_seq') is not None:
                    parts.append(f"play_seq_sched={wait_info['play_seq']}")
                if wait_info.get('lag') is not None:
                    parts.append(f"lag_ms={wait_info['lag'] * 1000:.1f}")
            print(' '.join(parts))
        except Exception:
            pass

    async def _start_opus_stream_decoder(self, input_sr: int, stream_queue: asyncio.Queue):
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-v', 'error', '-i', 'pipe:0',
                '-f', 's16le', '-ar', '16000', '-ac', '1', 'pipe:1',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            print('VA: failed to start ffmpeg for streaming opus decode:', exc, file=sys.stderr)
            return None
        reader_task = asyncio.create_task(self._opus_stdout_reader(proc, stream_queue))
        return {'proc': proc, 'reader_task': reader_task}

    async def _write_opus_stream(self, pipeline, data: bytes):
        if not pipeline or not data:
            return
        proc = pipeline.get('proc')
        if not proc or proc.stdin is None:
            return
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except Exception as exc:
            print('VA: opus stream write failed:', exc, file=sys.stderr)

    async def _stop_opus_stream_decoder(self, pipeline):
        if not pipeline:
            return
        proc = pipeline.get('proc')
        if proc and proc.stdin:
            try:
                proc.stdin.write_eof()
            except Exception:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        reader_task = pipeline.get('reader_task')
        if reader_task:
            try:
                await reader_task
            except Exception:
                pass
        if proc:
            try:
                await proc.wait()
            except Exception:
                pass

    async def _opus_stdout_reader(self, proc, stream_queue: asyncio.Queue):
        chunk = bytearray()
        try:
            while True:
                data = await proc.stdout.read(self.PLAY_CHUNK_BYTES)
                if not data:
                    break
                chunk.extend(data)
                while len(chunk) >= self.PLAY_CHUNK_BYTES:
                    frame = bytes(chunk[:self.PLAY_CHUNK_BYTES])
                    del chunk[:self.PLAY_CHUNK_BYTES]
                    if stream_queue:
                        await stream_queue.put(frame)
        except Exception as exc:
            print('VA: opus reader error:', exc, file=sys.stderr)
        finally:
            if chunk and stream_queue:
                await stream_queue.put(bytes(chunk))

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

    async def _decode_opus_stream(self, opus_bytes: bytes, input_sr: int = 24000):
        if not opus_bytes:
            return b""
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-v', 'error', '-i', 'pipe:0',
                '-f', 's16le', '-ar', '16000', '-ac', '1', 'pipe:1',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            print('VA: failed to start ffmpeg for opus decode:', e, file=sys.stderr)
            return None
        stdout, stderr = await proc.communicate(opus_bytes)
        if proc.returncode != 0:
            try:
                msg = stderr.decode()
            except Exception:
                msg = str(stderr)
            print('VA: opus decode failed:', msg, file=sys.stderr)
            return None
        return stdout

    async def _play_to_device(self, pcm_bytes: bytes):
        self.playing = True
        try:
            print(f"VA TX START (hub→device) pcm={len(pcm_bytes)}B")
            pace_start = time.time()
            sent_total, chunks = await self._send_pcm_frames(pcm_bytes)
        finally:
            self.playing = False
            try:
                elapsed = time.time() - pace_start if 'pace_start' in locals() else 0.0
                audio_sec = (sent_total // 2) / 16000.0 if sent_total else 0.0
                print(
                    f"VA TX END (hub→device) sent≈{sent_total}B chunks={chunks} "
                    f"elapsed={elapsed:.2f}s audio={audio_sec:.2f}s "
                    f"ratio={elapsed/audio_sec if audio_sec else 0:.2f}"
                )
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

    async def _vo_active_watchdog(self):
        """Clear stale is_vo_active flags based on last_wake.

        Runs per instance (one task per Django Instance object) and
        periodically resets is_vo_active=False for any colonels that
        still hold it but whose last_wake is older than a safety
        window (2 minutes).
        """
        STALE_SEC = 120
        INTERVAL_SEC = 60
        try:
            Colonels = self.c.colonel.__class__
            instance = self.c.instance
        except Exception:
            return

        while True:
            try:
                await asyncio.sleep(INTERVAL_SEC)
                cutoff = timezone.now() - timedelta(seconds=STALE_SEC)

                def _clear_stale():
                    qs = (Colonels.objects
                          .filter(instance=instance, is_vo_active=True)
                          .filter(Q(last_wake__lt=cutoff) | Q(last_wake__isnull=True)))
                    # Use a single UPDATE per instance to clear all
                    # stale owners.
                    if qs.exists():
                        qs.update(is_vo_active=False)
                await sync_to_async(_clear_stale, thread_sensitive=True)()
            except asyncio.CancelledError:
                return
            except Exception:
                print("VA VO-active watchdog error\n", traceback.format_exc(), file=sys.stderr)

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
        # Reset arbitrator so each new VA session gets a
        # fresh busy/winner decision and cannot reuse a
        # stale _busy_rejected flag from a prior turn.
        try:
            if getattr(self.c, '_arb', None) is not None:
                self.c._arb = None
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
                # First, clear any stale VO-active flags for colonels
                # that are no longer connected. These can be left over
                # across hub restarts or crashes.
                qs_stale = (self.c.colonel.__class__.objects
                            .filter(instance=self.c.instance,
                                    is_vo_active=True,
                                    socket_connected=False))
                if qs_stale.exists():
                    qs_stale.update(is_vo_active=False)

                # Consider only colonels that are both VO-active and
                # currently connected as truly "active" owners.
                return (self.c.colonel.__class__.objects
                        .filter(instance=self.c.instance,
                                is_vo_active=True,
                                socket_connected=True)
                        .exclude(id=self.c.colonel.id)
                        .exists())
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
                # Clear any VO-active flags for colonels that are not
                # currently connected; these are stale and should not
                # block a new session from becoming the winner.
                qs_stale = (self.c.colonel.__class__.objects
                            .filter(instance=self.c.instance,
                                    is_vo_active=True,
                                    socket_connected=False))
                if qs_stale.exists():
                    qs_stale.update(is_vo_active=False)

                # Only treat colonels that are *both* VO-active and
                # connected as other active owners.
                return (self.c.colonel.__class__.objects
                        .filter(instance=self.c.instance,
                                is_vo_active=True,
                                socket_connected=True)
                        .exclude(id=self.c.colonel.id)
                        .exists())
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
