##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LANE_STATE action (Unit 2.3 / 2.4)
#
# Combines two behaviours in one action:
#
#   SEND: on button press, sends a raw CC byte sequence to Ultra8 (same as
#         CUSTOM_MESSAGE).
#
#   RECEIVE: registers a persistent listener for the Ultra8 debug feedback CC
#            (CC 100+lane on MIDI channel 16).  When the CC arrives, decodes
#            the packed state byte and updates:
#              • the button LED colour / brightness
#              • DISPLAY_STATUS text and colour (if available)
#
# Encoding (set by Ultra8's @block debug emitter, Unit 2.2):
#   CC value = (st_state * 8) + (st_dirty > 0 ? 4 : 0) + st_monmode
#   st_state : 0=stopped, 1=playing, 2=recording/overdub
#   st_dirty : boolean — lane has recorded content
#   st_monmode: 0/1/2 (not used for LED colour in this milestone)
#
# LED colours:
#   Recording  → RED
#   Playing    → LIGHT_GREEN
#   Stopped with content → dim BLUE
#   Empty      → off (BLACK)
#   Waiting / stale (no feedback yet, or timed out) → dim GRAY
#
# Stale detection (Unit 2.4):
#   parameter_changed() stamps __last_feedback_ms on every received CC.
#   update_displays() checks elapsed time each cycle; if it exceeds
#   FEEDBACK_TIMEOUT_MS (from ultra8_config) the LED and status bar revert
#   to the waiting state automatically.  They recover on the next CC.
#
# Must match Ultra8 JSFX constants:
#   g_dbg_fb_cc_base = 100   (CC 100+lane)
#   g_dbg_fb_chan    = 15    (0-indexed → MIDI channel 16)
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....controller.client import ClientParameterMapping
from ....colors import Colors
from ....misc import get_current_millis
from adafruit_midi.control_change import ControlChange
from adafruit_midi.midi_message import MIDIMessage

# ── Constants (must match Ultra8 JSFX) ───────────────────────────────────────
_FEEDBACK_CC_BASE = 100   # CC number = _FEEDBACK_CC_BASE + lane_index

# ── LED colours per state ─────────────────────────────────────────────────────
_COLOR_RECORDING = Colors.RED
_COLOR_PLAYING   = Colors.LIGHT_GREEN
_COLOR_STOPPED   = Colors.BLUE          # stopped with recorded content
_COLOR_EMPTY     = Colors.BLACK         # lane has no content
_COLOR_WAITING   = Colors.DARK_GRAY     # no feedback received yet (initial)

_BRIGHTNESS_ACTIVE  = 0.3
_BRIGHTNESS_STOPPED = 0.15             # dimmer for stopped-with-content
_BRIGHTNESS_EMPTY   = 0.02             # near-off for truly empty


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
        # Build a response-only mapping so the framework creates a permanent
        # (non-expiring) listener: no `request` field → lifetime = None.
        self.__mapping = ClientParameterMapping.get(
            name     = "Ultra8LaneFB" + str(lane),
            response = ControlChange(_FEEDBACK_CC_BASE + lane, 0),
        )
        super().__init__(mappings = [self.__mapping])

        self.__message         = message
        self.__message_release = message_release
        self.__text            = text

        # Current display state — starts in "waiting" before first feedback
        self.__current_color      = _COLOR_WAITING
        self.__current_brightness = _BRIGHTNESS_EMPTY
        self.__status_label       = None

        # Stale detection: timestamp of the last received feedback CC (ms).
        # None means no feedback has ever arrived this session.
        self.__last_feedback_ms   = None
        self.__feedback_timeout_ms = None  # loaded from ultra8_config in init()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener = None):
        self.__appl = appl
        super().init(appl, listener)   # registers mapping with client

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

    # ── Feedback receipt (called by the framework when a new CC arrives) ──────

    def parameter_changed(self, mapping):
        """Stamp the arrival time so update_displays() can detect staleness."""
        self.__last_feedback_ms = get_current_millis()
        super().parameter_changed(mapping)

    # ── Display update (called every loop cycle, and on each feedback CC) ─────

    def update_displays(self):
        # ── Stale check ───────────────────────────────────────────────────────
        # Feedback is considered stale if no CC has arrived within the timeout.
        # This covers two cases:
        #   • __last_feedback_ms is None  → no feedback ever received this session
        #   • elapsed > timeout           → feedback has stopped arriving
        stale = (
            self.__last_feedback_ms is None or
            (get_current_millis() - self.__last_feedback_ms) > self.__feedback_timeout_ms
        )

        if stale:
            self.__current_color      = _COLOR_WAITING
            self.__current_brightness = _BRIGHTNESS_EMPTY
            if self.__status_label:
                self.__status_label.text_color = Colors.DARK_GRAY
                self.__status_label.text       = "Waiting for snapshot..."

        else:
            # ── Decode fresh feedback ─────────────────────────────────────────
            # CC value = state*8 + dirty*4 + monmode
            v     = self.__mapping.value
            state = v >> 3          # 0=stopped, 1=playing, 2=recording
            dirty = (v >> 2) & 1    # 1 = lane has recorded content

            if state == 2:
                self.__current_color      = _COLOR_RECORDING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                status_text  = "REC"
                status_color = Colors.RED

            elif state == 1:
                self.__current_color      = _COLOR_PLAYING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                status_text  = "PLY"
                status_color = Colors.LIGHT_GREEN

            elif dirty:
                self.__current_color      = _COLOR_STOPPED
                self.__current_brightness = _BRIGHTNESS_STOPPED
                status_text  = "STP"
                status_color = Colors.DARK_GRAY

            else:
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
