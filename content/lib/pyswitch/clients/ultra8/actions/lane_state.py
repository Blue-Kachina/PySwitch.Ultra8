##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LANE_STATE action (Units 2.3 / 2.4 / 3.7)
#
# Combines two behaviours in one action:
#
#   SEND: on button press, sends a raw CC byte sequence to Ultra8 (same as
#         CUSTOM_MESSAGE).
#
#   RECEIVE (Unit 3.7): polls protocol.snapshot each display cycle instead
#         of the Unit 2.x debug CC (CC 100+lane, channel 16).  Looks up the
#         lane block for this device's configured lane and decodes:
#              • the button LED colour / brightness
#              • DISPLAY_STATUS text and colour (if available)
#
#         Stale detection reads protocol.last_feedback_ms (set by the SysEx
#         parser on every accepted snapshot) rather than tracking CC arrivals
#         locally.
#
# Lane state enum (from protocol_sysex_v0_1.md):
#   0 = STOPPED     — no audio recorded, or stopped
#   1 = PLAYING     — loop is running
#   2 = RECORDING   — first-pass record (loop length not yet set)
#   3 = OVERDUBBING — overdub on an existing loop
#
# LED colours:
#   RECORDING   → RED
#   OVERDUBBING → ORANGE   (distinct from first-record RED)
#   PLAYING     → LIGHT_GREEN
#   Stopped, content present  → dim BLUE
#   Stopped, empty            → near-off (BLACK)
#   Waiting / stale           → dim GRAY
#
# Stale detection (Unit 2.4, extended in 3.7):
#   update_displays() reads protocol.last_feedback_ms each cycle.  If it is
#   None (no snapshot ever received) or too old, the LED and status bar revert
#   to the waiting state automatically.  They recover on the next snapshot.
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....colors import Colors
from ....misc import get_current_millis
from adafruit_midi.midi_message import MIDIMessage

# ── LED colours per state ─────────────────────────────────────────────────────
_COLOR_RECORDING   = Colors.RED
_COLOR_OVERDUBBING = Colors.ORANGE
_COLOR_PLAYING     = Colors.LIGHT_GREEN
_COLOR_STOPPED     = Colors.BLUE        # stopped with recorded content
_COLOR_EMPTY       = Colors.BLACK       # lane has no content
_COLOR_WAITING     = Colors.DARK_GRAY   # no snapshot received / stale

_BRIGHTNESS_ACTIVE  = 0.3
_BRIGHTNESS_STOPPED = 0.15             # dimmer for stopped-with-content
_BRIGHTNESS_EMPTY   = 0.02             # near-off for truly empty

# Lane state enum — must match protocol_sysex_v0_1.md and protocol.py
_STATE_STOPPED    = 0
_STATE_PLAYING    = 1
_STATE_RECORDING  = 2
_STATE_OVERDUBBING = 3


# ── Public factory function ───────────────────────────────────────────────────

def ULTRA8_LANE_STATE(
    lane,                   # 0-indexed lane index (DEFAULT_CHANNEL - 1)
    message,                # Raw bytes sent on short press (NANO4 → Ultra8)
    message_release = None, # Raw bytes sent on release (optional)
    text = "",              # Button label text
    display = None,         # DisplayLabel for screen corner label
    use_leds = True,
    id = None,
    enable_callback = None,
):
    """
    Action that sends a CC on press and drives its LED purely from Ultra8
    state feedback — never from local guessing.
    """
    return Action({
        "callback": _LaneStateCallback(
            lane            = lane,
            message         = message,
            message_release = message_release,
            text            = text,
        ),
        "display":         display,
        "useSwitchLeds":   use_leds,
        "id":              id,
        "enableCallback":  enable_callback,
    })


# ── Internal callback ─────────────────────────────────────────────────────────

class _LaneStateCallback(Callback):

    # Minimal raw MIDI wrapper (same pattern as CUSTOM_MESSAGE)
    class _RawMessage(MIDIMessage):
        def __init__(self, data):
            self.__data = bytearray(data)
        def __bytes__(self):
            return self.__data

    def __init__(self, lane, message, message_release, text):
        # No CC listener — update_displays() polls protocol.snapshot directly.
        super().__init__(mappings = [])

        self.__lane            = lane
        self.__message         = message
        self.__message_release = message_release
        self.__text            = text

        # Current display state — starts in "waiting" before first snapshot
        self.__current_color      = _COLOR_WAITING
        self.__current_brightness = _BRIGHTNESS_EMPTY
        self.__status_label       = None

        self.__feedback_timeout_ms = None  # loaded from ultra8_config in init()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener = None):
        self.__appl = appl
        super().init(appl, listener)

        # Late-import DISPLAY_STATUS (display.py loads after communication.py)
        try:
            from display import DISPLAY_STATUS
            self.__status_label = DISPLAY_STATUS
        except ImportError:
            pass   # running without display (tests, emulator, etc.)

        # Late-import timeout setting from per-device config.
        # Falls back to 5000 ms if ultra8_config is unavailable (e.g. tests).
        try:
            from ultra8_config import FEEDBACK_TIMEOUT_MS
            self.__feedback_timeout_ms = FEEDBACK_TIMEOUT_MS
        except (ImportError, AttributeError):
            self.__feedback_timeout_ms = 5000

    # ── Button press / release ────────────────────────────────────────────────

    def push(self):
        self.__appl.client.midi.send(self._RawMessage(self.__message))

    def release(self):
        if self.__message_release:
            self.__appl.client.midi.send(self._RawMessage(self.__message_release))

    # ── Periodic update (called every loop cycle by the framework) ───────────

    def update(self):
        # The base Callback.update() calls client.request() for each registered
        # mapping.  With mappings=[], that is a no-op.  We override here to also
        # call update_displays() so LED/screen state refreshes every cycle
        # without waiting for a MIDI event to trigger it.
        super().update()
        self.update_displays()

    # ── Display update (called every loop cycle via update(), and on init) ───

    def update_displays(self):
        protocol = self.__appl.client.protocol

        # ── Stale check ───────────────────────────────────────────────────────
        # Snapshot is stale if no valid SysEx has arrived within the timeout.
        last_ms = protocol.last_feedback_ms
        stale = (
            last_ms is None or
            (get_current_millis() - last_ms) > self.__feedback_timeout_ms
        )

        if stale:
            self.__current_color      = _COLOR_WAITING
            self.__current_brightness = _BRIGHTNESS_EMPTY
            if self.__status_label:
                self.__status_label.text_color = Colors.DARK_GRAY
                self.__status_label.text       = "Waiting for snapshot..."

        else:
            # ── Decode current lane state from snapshot ───────────────────────
            lane_block = protocol.snapshot.lanes[self.__lane]
            state = lane_block.state
            dirty = lane_block.dirty

            if state == _STATE_RECORDING:
                self.__current_color      = _COLOR_RECORDING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                status_text  = "REC"
                status_color = Colors.RED

            elif state == _STATE_OVERDUBBING:
                self.__current_color      = _COLOR_OVERDUBBING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                status_text  = "OVDB"
                status_color = Colors.ORANGE

            elif state == _STATE_PLAYING:
                self.__current_color      = _COLOR_PLAYING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                status_text  = "PLY"
                status_color = Colors.LIGHT_GREEN

            elif dirty:
                # STOPPED but has recorded content
                self.__current_color      = _COLOR_STOPPED
                self.__current_brightness = _BRIGHTNESS_STOPPED
                status_text  = "STP"
                status_color = Colors.DARK_GRAY

            else:
                # STOPPED, no content
                self.__current_color      = _COLOR_EMPTY
                self.__current_brightness = _BRIGHTNESS_EMPTY
                status_text  = "EMPTY"
                status_color = Colors.DARK_GRAY

            if self.__status_label:
                self.__status_label.text_color = status_color
                self.__status_label.text       = "Lane: " + status_text

        # ── Apply to LED and corner label (every cycle) ───────────────────────
        self.action.switch_color      = self.__current_color
        self.action.switch_brightness = self.__current_brightness

        if self.action.label:
            self.action.label.text       = self.__text
            self.action.label.back_color = self.__current_color
