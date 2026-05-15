##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LANE_STATE action (Units 2.3 / 2.4 / 3.7 / 5.1 / 5.2 / 5.4)
#
# Combines two behaviours in one action:
#
#   SEND: on button press, sends a raw CC byte sequence to Ultra8.
#
#   RECEIVE: polls protocol.snapshot each display cycle and decodes the lane
#       block for this device's configured lane:
#           • LED colour / brightness (Switch A NeoPixels)
#           • DISPLAY_STATE  — big state name, coloured (Unit 5.2)
#           • DISPLAY_PROGRESS — ASCII loop-phase bar (Unit 5.4)
#           • DISPLAY_SEQ    — tiny snapshot sequence counter (Unit 5.2)
#
# Lane state enum (from protocol_sysex_v0_1.md):
#   0 = STOPPED     — no audio recorded, or stopped
#   1 = PLAYING     — loop is running
#   2 = RECORDING   — first-pass record (loop length not yet set)
#   3 = OVERDUBBING — overdub on an existing loop
#   >3              — unknown/error (future protocol versions)
#
# LED colours (Unit 5.1):
#   RECORDING   → RED          _BRIGHTNESS_ACTIVE
#   OVERDUBBING → ORANGE       _BRIGHTNESS_ACTIVE
#   PLAYING     → LIGHT_GREEN  _BRIGHTNESS_ACTIVE
#   STP w/audio → dim BLUE     _BRIGHTNESS_STOPPED
#   STP empty   → near-off     _BRIGHTNESS_EMPTY
#   Unknown/ERR → PURPLE       _BRIGHTNESS_ACTIVE
#   Waiting     → dim GRAY     _BRIGHTNESS_EMPTY
#
# Progress bar (Unit 5.4):
#   PLAYING / OVERDUBBING → 14-char block bar driven by loop_phase (0–127)
#   RECORDING             → empty (no loop exists yet)
#   All other states      → empty
#
# Stale detection:
#   Reads protocol.last_feedback_ms each cycle. Reverts to "wait" state if
#   None (no snapshot ever received) or older than FEEDBACK_TIMEOUT_MS ms.
#   Recovers automatically on the next valid snapshot.
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
_COLOR_ERROR       = Colors.PURPLE      # unknown / out-of-range state enum

_BRIGHTNESS_ACTIVE  = 0.3
_BRIGHTNESS_STOPPED = 0.15             # dimmer for stopped-with-content
_BRIGHTNESS_EMPTY   = 0.02             # near-off for truly empty

# Lane state enum — must match protocol_sysex_v0_1.md and protocol.py
_STATE_STOPPED    = 0
_STATE_PLAYING    = 1
_STATE_RECORDING  = 2
_STATE_OVERDUBBING = 3

# Progress bar (Unit 5.4)
_BAR_WIDTH = 14   # number of fill characters in the bar

def _make_bar(loop_phase):
    """Convert loop_phase 0–127 to a 14-char block progress bar.

    Uses Unicode block characters (█ full, ░ light shade).
    If the font on the device does not support these, substitute ASCII:
        return "=" * filled + "-" * (_BAR_WIDTH - filled)
    """
    filled = max(0, min(_BAR_WIDTH, int(loop_phase / 127 * _BAR_WIDTH)))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


# ── Public factory function ───────────────────────────────────────────────────

def ULTRA8_LANE_STATE(
    lane,                   # 0-indexed lane index (DEFAULT_PAGE - 1)
    message,                # Raw bytes sent on short press (NANO4 → Ultra8)
    message_release = None, # Raw bytes sent on release (optional)
    text = "",              # Button label text (shown in footer corner)
    display = None,         # DisplayLabel for screen corner label
    use_leds = True,
    id = None,
    enable_callback = None,
):
    """
    Action that sends a CC on press and drives its LED/screen purely from
    Ultra8 snapshot feedback — never from local guessing.
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

        # Current LED state — starts in "waiting" before first snapshot
        self.__current_color      = _COLOR_WAITING
        self.__current_brightness = _BRIGHTNESS_EMPTY

        # Display label references — set in init() via late-import
        self.__state_label    = None   # DISPLAY_STATE: big state name
        self.__progress_label = None   # DISPLAY_PROGRESS: ASCII bar
        self.__seq_label      = None   # DISPLAY_SEQ: snapshot seq counter

        self.__feedback_timeout_ms = None  # loaded from ultra8_config in init()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener = None):
        self.__appl = appl
        super().init(appl, listener)

        # Late-import display labels (display.py loads after communication.py).
        try:
            from display import DISPLAY_STATE, DISPLAY_PROGRESS, DISPLAY_SEQ
            self.__state_label    = DISPLAY_STATE
            self.__progress_label = DISPLAY_PROGRESS
            self.__seq_label      = DISPLAY_SEQ
        except (ImportError, AttributeError):
            pass   # running without display (tests, emulator, etc.)

        # Late-import timeout from per-device config. Fallback: 5000 ms.
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
        super().update()
        self.update_displays()

    # ── Display update ───────────────────────────────────────────────────────

    def update_displays(self):
        protocol = self.__appl.client.protocol

        # ── Stale check ───────────────────────────────────────────────────────
        last_ms = protocol.last_feedback_ms
        stale = (
            last_ms is None or
            (get_current_millis() - last_ms) > self.__feedback_timeout_ms
        )

        if stale:
            # ── Waiting / no signal ───────────────────────────────────────────
            self.__current_color      = _COLOR_WAITING
            self.__current_brightness = _BRIGHTNESS_EMPTY

            if self.__state_label:
                self.__state_label.text_color = Colors.DARK_GRAY
                self.__state_label.text       = "wait"

            if self.__progress_label:
                self.__progress_label.text = ""

            if self.__seq_label:
                self.__seq_label.text = ""

        else:
            # ── Decode current lane state from snapshot ───────────────────────
            lane_block = protocol.snapshot.lanes[self.__lane]
            state      = lane_block.state
            dirty      = lane_block.dirty
            loop_phase = lane_block.loop_phase
            seq        = protocol.snapshot.seq

            # Determine LED colour, state label text, and progress bar
            if state == _STATE_RECORDING:
                self.__current_color      = _COLOR_RECORDING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                state_text    = "REC"
                state_color   = Colors.RED
                progress_text = ""              # no loop yet during first-pass

            elif state == _STATE_OVERDUBBING:
                self.__current_color      = _COLOR_OVERDUBBING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                state_text    = "OVDB"
                state_color   = Colors.ORANGE
                progress_text = _make_bar(loop_phase)

            elif state == _STATE_PLAYING:
                self.__current_color      = _COLOR_PLAYING
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                state_text    = "PLY"
                state_color   = Colors.LIGHT_GREEN
                progress_text = _make_bar(loop_phase)

            elif state == _STATE_STOPPED:
                if dirty:
                    # Stopped, has recorded audio
                    self.__current_color      = _COLOR_STOPPED
                    self.__current_brightness = _BRIGHTNESS_STOPPED
                    state_text    = "STP"
                    state_color   = Colors.DARK_GRAY
                else:
                    # Stopped, lane is empty
                    self.__current_color      = _COLOR_EMPTY
                    self.__current_brightness = _BRIGHTNESS_EMPTY
                    state_text    = "---"
                    state_color   = Colors.DARK_GRAY
                progress_text = ""              # stopped = no progress to show

            else:
                # Unknown / out-of-range state enum (future protocol versions)
                self.__current_color      = _COLOR_ERROR
                self.__current_brightness = _BRIGHTNESS_ACTIVE
                state_text    = "ERR"
                state_color   = Colors.PURPLE
                progress_text = ""

            # ── Apply to display labels ───────────────────────────────────────
            if self.__state_label:
                self.__state_label.text_color = state_color
                self.__state_label.text       = state_text

            if self.__progress_label:
                self.__progress_label.text = progress_text

            if self.__seq_label:
                self.__seq_label.text_color = Colors.DARK_GRAY
                self.__seq_label.text       = "#" + str(seq)

        # ── Apply LED colour to Switch A NeoPixels ────────────────────────────
        self.action.switch_color      = self.__current_color
        self.action.switch_brightness = self.__current_brightness

        # ── Update corner label (DISPLAY_FOOTER_1) ────────────────────────────
        if self.action.label:
            self.action.label.text       = self.__text
            self.action.label.back_color = self.__current_color
