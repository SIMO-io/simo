from django.utils import timezone
from simo.core.models import Component
from .models import Interface, CustomDaliDevice
from .controllers import (
    TempHumSensor, AirQualitySensor, AmbientLightSensor,
    RoomPresenceSensor, RoomZonePresenceSensor
)


class Frame:
    """A DALI frame.

    A Frame consists of one start bit, n data bits, and one stop
    condition.  The most significant bit is always transmitted first.

    Instances of this object are mutable.
    """

    def __init__(self, bits, data=0):
        """Initialise a Frame with the supplied number of data bits.

        :parameter bits: the number of data bits in the Frame
        :parameter data: initial data for the Frame as an integer or
        an iterable sequence of integers
        """
        if not isinstance(bits, int):
            raise TypeError(
                "Number of bits must be an integer")
        if bits < 1:
            raise ValueError(
                "Frames must contain at least 1 data bit")
        self._bits = bits
        if isinstance(data, int):
            self._data = data
        else:
            self._data = int.from_bytes(data, 'big')
        if self._data < 0:
            raise ValueError("Initial data must not be negative")
        if len(self.pack) > bits:
            raise ValueError(
                "Initial data will not fit in {} bits".format(bits))
        self._error = False

    @property
    def error(self):
        """Frame was received with a framing error."""
        return self._error

    def __len__(self):
        return self._bits

    def __eq__(self, other):
        try:
            return self._bits == other._bits and self._data == other._data
        except Exception:
            return False

    def __ne__(self, other):
        try:
            return self._bits != other._bits or self._data != other._data
        except Exception:
            return True

    def _readslice(self, key):
        """Check that a slice is valid, return indices

        The slice must have indices that are integers.  The indices
        must be in the range 0..(len(self)-1).
        """
        if not isinstance(key.start, int) or not isinstance(key.stop, int):
            raise TypeError("slice indices must be integers")
        if key.step not in (None, 1):
            raise TypeError("slice with step not supported")
        hi = max(key.start, key.stop)
        lo = min(key.start, key.stop)
        if hi < 0 or lo < 0:
            raise IndexError("slice indices must be >= 0")
        if hi >= self._bits or lo >= self._bits:
            raise IndexError("slice index out of range")
        return hi, lo

    def __getitem__(self, key):
        """Read a bit or group of bits from the frame

        If the key is an integer, return that bit as True or False or
        raise IndexError if the key is out of bounds.

        If the key is a slice, return that slice as an integer or
        raise IndexError if out of bounds.  We abuse the slice
        mechanism slightly such that slice(5,7) and slice(7,5) are
        treated the same.  Slices with a step or a negative index are
        not supported.
        """
        if isinstance(key, slice):
            hi, lo = self._readslice(key)
            d = self._data >> lo
            return d & ((1 << (hi + 1 - lo)) - 1)
        elif isinstance(key, int):
            if key < 0 or key >= self._bits:
                raise IndexError("index out of range")
            return (self._data & (1 << key)) != 0
        raise TypeError

    def __setitem__(self, key, value):
        """Write a bit or a group of bits to the frame

        If the key is an integer, set that bit to the truth value of
        value or raise IndexError if the key is out of bounds.

        If the key is a slice, value must be an integer that fits
        within the slice; set that slice to value or raise IndexError
        if out of bounds.  We abuse the slice mechanism slightly such
        that slice(5,7) and slice(7,5) are treated the same.  Slices
        with a step or a negative index are not supported.
        """
        if isinstance(key, slice):
            hi, lo = self._readslice(key)
            if not isinstance(value, int):
                raise TypeError("value must be an integer")
            if len(bin(value)) - 2 > (hi + 1 - lo):
                raise ValueError("value will not fit in supplied slice")
            if value < 0:
                raise ValueError("value must not be negative")
            template = ((1 << hi + 1 - lo) - 1) << lo
            mask = ((1 << self._bits) - 1) ^ template
            self._data = self._data & mask | (value << lo)
        elif isinstance(key, int):
            if key < 0 or key >= self._bits:
                raise IndexError("index out of range")
            if value:
                self._data = self._data | (1 << key)
            else:
                self._data = self._data \
                    & (((1 << self._bits) - 1) ^ (1 << key))
        else:
            raise TypeError

    def __contains__(self, item):
        if item is True:
            return self._data != 0
        if item is False:
            return self._data != (1 << self._bits) - 1
        return False

    def __add__(self, other):
        try:
            return Frame(self._bits + other._bits,
                         self._data << other._bits | other._data)
        except Exception:
            raise TypeError("Frame can only be added to another Frame")

    @property
    def as_integer(self):
        """The contents of the frame represented as an integer."""
        return self._data

    @property
    def as_byte_sequence(self):
        """The contents of the frame represented as a sequence.

        Returns a sequence of integers each in the range 0..255
        representing the data in the frame, with the most-significant
        bits first.  If the frame is not an exact multiple of 8 bits
        long, the first element in the sequence contains fewer than 8
        bits.
        """
        return list(self.pack)

    @property
    def pack(self):
        """The contents of the frame represented as a byte string.

        If the frame is not an exact multiple of 8 bits long, the
        first byte in the string will contain fewer than 8 bits.
        """
        return self._data.to_bytes(
            (len(self) // 8) + (1 if len(self) % 8 else 0),
            'big')

    def pack_len(self, l):
        """The contents of the frame represented as a fixed length byte string.

        The least significant bit of the frame is aligned to the end
        of the byte string.  The start of the byte string is padded
        with zeroes.

        If the frame will not fit in the byte string, raises
        OverflowError.
        """
        return self._data.to_bytes(l, 'big')

    def __str__(self):
        return "{}({},{})".format(self.__class__.__name__, len(self),
                                  self.as_byte_sequence)


def process_frame(colonel_id, interface_no, data):
    interface = Interface.objects.filter(
        colonel_id=colonel_id, no=interface_no
    ).first()
    if not interface:
        return

    data = bytes.fromhex(data)
    frame = Frame(len(data) * 8, data)

    device_address = frame[0:7]
    device = CustomDaliDevice.objects.filter(
        random_address=device_address, instance=interface.colonel.instance
    ).first()
    if not device:
        return

    device.interface = interface
    device.last_seen = timezone.now()
    device.save()

    print("Frame received: ", frame.pack)

    if frame[8:11] == 0:
        # climate and air quality data
        temp = (frame[12:21] - 512) / 10
        humidity = round(frame[22:27] / 64 * 100)
        comp = Component.objects.filter(
            controller_uid=TempHumSensor.uid, config__dali_device=device.id
        ).first()
        if comp:
            comp.controller._receive_from_device({'temp': temp, 'humidity': humidity})
        voc = frame[28:38]
        comp = Component.objects.filter(
            controller_uid=AirQualitySensor.uid, config__dali_device=device.id
        ).first()
        if comp:
            comp.controller._receive_from_device(voc)

    elif frame[8:11] == 1:
        comp = Component.objects.filter(
            controller_uid=AmbientLightSensor.uid, config__dali_device=device.id
        ).first()
        if comp:
            comp.controller._receive_from_device(frame[12:22] * 2)
        comp = Component.objects.filter(
            controller_uid=RoomPresenceSensor.uid, config__dali_device=device.id
        ).first()
        if comp:
            comp.controller._receive_from_device(frame[23])

        zone_sensors = {}
        for slot in range(8):
            comp = Component.objects.filter(
                controller_uid=RoomZonePresenceSensor.uid,
                config__dali_device=device.id, config__slot=slot
            ).first()
            if comp:
                zone_sensors[slot] = comp

        for slot in range(8):
            if frame[24 + slot * 2]:
                comp = zone_sensors.get(slot)
                if comp:
                    comp.controller._receive_from_device(frame[25 + slot * 2])
                else:
                    # component no longer exists, probably deleted by user
                    # need to inform device about that!
                    f = Frame(40, bytes(bytearray(5)))
                    f[8:11] = 15  # command to custom dali device
                    f[12:15] = 2  # action to perform: delete zone sensor
                    f[16:18] = slot
                    device.transmit(f)
            elif zone_sensors.get(slot):
                # not yet picked up by the device itself or
                # was never successfully created
                if zone_sensors[slot].alive:
                    zone_sensors[slot].alive = False
                    zone_sensors[slot].save()