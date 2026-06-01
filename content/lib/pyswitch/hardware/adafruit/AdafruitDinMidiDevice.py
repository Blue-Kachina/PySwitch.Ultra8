from adafruit_midi import MIDI as _MIDI
from adafruit_midi.system_exclusive import SystemExclusive as _SystemExclusive
from adafruit_midi.midi_message import MIDIUnknownEvent as _MIDIUnknownEvent
from busio import UART as _UART

# DIN MIDI Device
#
# receive() implements its own SysEx assembler rather than using adafruit_midi's
# receive() path.  adafruit_midi has a bug where an incomplete variable-length
# message (SysEx with no F7 yet) causes all currently-buffered bytes to be
# discarded instead of preserved.  Because the firmware loop polls fast enough
# to catch the SysEx mid-transmission, the first read often gets a partial
# header (e.g. 7 bytes of a 33-byte packet), which adafruit_midi then throws
# away.  The continuation bytes arrive on the next read without the F0 header,
# so the packet can never be assembled.
#
# Our assembler accumulates bytes across reads in _sysex_buf and only produces
# a SystemExclusive object when the complete F0…F7 frame has arrived.  Per the
# MIDI spec, real-time bytes (0xF8–0xFF) are silently skipped mid-SysEx; any
# other unexpected status byte aborts the current frame.
#
# DIN on this device only receives SysEx from Ultra8 (state snapshots and
# assignment messages), so non-SysEx bytes outside of a SysEx frame are
# intentionally ignored on the receive path.  The send path still uses
# adafruit_midi so that outgoing CC messages are formatted correctly.

class AdafruitDinMidiDevice:
    def __init__(self,
                 gpio_in,
                 gpio_out,
                 in_buf_size,
                 baudrate,
                 timeout,
                 in_channel = None,
                 out_channel = 0,
        ):

        midi_uart = _UART(
            gpio_in,
            gpio_out,
            baudrate = baudrate,
            timeout = timeout,
            receiver_buffer_size = 2048  # survive up to ~655ms loop spikes at 31250 baud
        )

        self._uart = midi_uart  # direct UART reference for our SysEx assembler

        # adafruit_midi is used for the send path only
        self.__midi = _MIDI(
            midi_out = midi_uart,
            out_channel = out_channel,
            midi_in = midi_uart,   # not used for receive; kept for send path
            in_channel = in_channel,
            in_buf_size = in_buf_size,
        )

        self._sysex_buf     = None  # bytearray being assembled; None = not in SysEx
        self._sysex_pending = []    # fully assembled SystemExclusive objects waiting to be returned

    def send(self, midi_message):
        if isinstance(midi_message, _MIDIUnknownEvent):
            return
        self.__midi.send(midi_message)

    def receive(self):
        # Drain the UART into our SysEx assembler
        raw = self._uart.read(256)
        if raw:
            for b in raw:
                if b == 0xF0:
                    # Start of a new SysEx frame (resets any in-progress frame)
                    self._sysex_buf = bytearray([0xF0])

                elif self._sysex_buf is not None:
                    if b == 0xF7:
                        # Complete frame — build the object and queue it
                        self._sysex_buf.append(b)
                        try:
                            msg = _SystemExclusive.from_bytes(bytes(self._sysex_buf))
                            self._sysex_pending.append(msg)
                        except Exception:
                            pass
                        self._sysex_buf = None

                    elif b >= 0xF8:
                        # Real-time byte mid-SysEx: ignore per MIDI spec
                        pass

                    elif b >= 0x80:
                        # Any other status byte mid-SysEx aborts the frame
                        self._sysex_buf = None

                    else:
                        # Data byte: accumulate
                        self._sysex_buf.append(b)

                # else: non-SysEx byte outside a frame — ignored
                # (DIN only carries SysEx from Ultra8 on the receive path)

        # Return one message per call
        if self._sysex_pending:
            return self._sysex_pending.pop(0)
        return None
