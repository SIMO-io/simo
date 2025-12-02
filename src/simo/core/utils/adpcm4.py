"""IMA ADPCM (4-bit) codec helpers (shared with Sentinel firmware).

This module mirrors the MicroPython implementation used by Sentinel so that
the hub can encode/decode the exact same framing without extra dependencies.
"""

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17,
    19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
    130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
    337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
    876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
    5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)

INDEX_TABLE = (
    -1, -1, -1, -1, 2, 4, 6, 8,
    -1, -1, -1, -1, 2, 4, 6, 8,
)


class ImaAdpcmState:
    """Holds the ADPCM predictor and step index for streaming use."""

    __slots__ = ("predictor", "index")

    def __init__(self, predictor=0, index=0):
        self.predictor = _clamp_pcm(int(predictor))
        self.index = _clamp_index(int(index))

    def copy(self):
        return ImaAdpcmState(self.predictor, self.index)


def encode(pcm, state=None, out=None):
    """Encode 16-bit little-endian PCM into IMA ADPCM."""

    mv = memoryview(pcm)
    length = len(mv)
    if length == 0:
        if out is None:
            return bytearray(0)
        return out[:0]
    if length & 1:
        raise ValueError("PCM buffer must have an even number of bytes")

    if state is None:
        state = ImaAdpcmState()

    samples = length >> 1
    out_len = (samples + 1) >> 1
    if out is None:
        out = bytearray(out_len)
    elif len(out) < out_len:
        raise ValueError("output buffer too small")

    predictor = state.predictor
    index = state.index
    have_low = False
    low_nibble = 0
    out_pos = 0

    for i in range(0, length, 2):
        sample = mv[i] | (mv[i + 1] << 8)
        if sample & 0x8000:
            sample -= 0x10000

        nibble, predictor, index = _encode_sample(sample, predictor, index)

        if not have_low:
            low_nibble = nibble
            have_low = True
        else:
            out[out_pos] = low_nibble | (nibble << 4)
            out_pos += 1
            have_low = False

    if have_low:
        out[out_pos] = low_nibble
        out_pos += 1

    state.predictor = predictor
    state.index = index
    if out_pos == len(out):
        return out
    return out[:out_pos]


def decode(adpcm, state=None, out=None, samples=None):
    """Decode IMA ADPCM data back to 16-bit little-endian PCM."""

    mv = memoryview(adpcm)
    length = len(mv)
    if length == 0:
        if out is None:
            return bytearray(0)
        return out[:0]

    if state is None:
        state = ImaAdpcmState()

    max_samples = length * 2
    if samples is None:
        samples = max_samples
    elif samples > max_samples:
        raise ValueError("not enough ADPCM data for requested samples")

    pcm_len = samples * 2
    if out is None:
        out = bytearray(pcm_len)
    elif len(out) < pcm_len:
        raise ValueError("output buffer too small")

    predictor = state.predictor
    index = state.index
    out_pos = 0
    produced = 0

    for byte in mv:
        if produced >= samples:
            break
        lo = byte & 0x0F
        predictor, index = _decode_nibble(lo, predictor, index)
        out[out_pos] = predictor & 0xFF
        out[out_pos + 1] = (predictor >> 8) & 0xFF
        out_pos += 2
        produced += 1

        if produced >= samples:
            break
        hi = (byte >> 4) & 0x0F
        predictor, index = _decode_nibble(hi, predictor, index)
        out[out_pos] = predictor & 0xFF
        out[out_pos + 1] = (predictor >> 8) & 0xFF
        out_pos += 2
        produced += 1

    state.predictor = predictor
    state.index = index
    if out_pos == len(out):
        return out
    return out[:out_pos]


def _encode_sample(sample, predictor, index):
    diff = sample - predictor
    sign = 0
    if diff < 0:
        sign = 8
        diff = -diff

    step = STEP_TABLE[index]
    delta = 0
    temp = step
    if diff >= temp:
        delta |= 4
        diff -= temp
    temp >>= 1
    if diff >= temp:
        delta |= 2
        diff -= temp
    temp >>= 1
    if diff >= temp:
        delta |= 1

    delta |= sign

    predictor = _apply_delta(predictor, step, delta)
    index = _clamp_index(index + INDEX_TABLE[delta & 0x0F])
    return delta & 0x0F, predictor, index


def _decode_nibble(nibble, predictor, index):
    step = STEP_TABLE[index]
    predictor = _apply_delta(predictor, step, nibble)
    index = _clamp_index(index + INDEX_TABLE[nibble & 0x0F])
    return predictor, index


def _apply_delta(predictor, step, nibble):
    diffq = step >> 3
    if nibble & 4:
        diffq += step
    if nibble & 2:
        diffq += step >> 1
    if nibble & 1:
        diffq += step >> 2
    if nibble & 8:
        predictor -= diffq
    else:
        predictor += diffq
    return _clamp_pcm(predictor)


def _clamp_pcm(val):
    if val < -32768:
        return -32768
    if val > 32767:
        return 32767
    return val


def _clamp_index(val):
    if val < 0:
        return 0
    if val > 88:
        return 88
    return val


def self_test():
    pcm = bytearray()
    import math
    for i in range(0, 320):
        sample = int(3000 * math.sin(i / 10))
        pcm.append(sample & 0xFF)
        pcm.append((sample >> 8) & 0xFF)

    enc_state = ImaAdpcmState()
    enc = encode(pcm, enc_state)
    dec_state = ImaAdpcmState()
    dec = decode(enc, dec_state)

    max_err = 0
    for i in range(0, len(pcm), 2):
        orig = pcm[i] | (pcm[i + 1] << 8)
        if orig & 0x8000:
            orig -= 0x10000
        back = dec[i] | (dec[i + 1] << 8)
        if back & 0x8000:
            back -= 0x10000
        err = orig - back
        if err < 0:
            err = -err
        if err > max_err:
            max_err = err

    return max_err


__all__ = [
    "ImaAdpcmState",
    "encode",
    "decode",
    "self_test",
]

