##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LANE_ACTION action (QoL Phase 4 Units 4.2–4.4)
#
# Replaces ULTRA8_LANE_STATE and ULTRA8_LABELED_BUTTON for buttons marked
# "dynamic: true" in their lane JSON config (currently buttons A and B).
#
# ── What it does ──────────────────────────────────────────────────────────────
#
#   SEND:
#       On button press, sends a raw CC byte sequence to Ultra8.
#
#   LED (dynamic=True):
#       Drives NeoPixels from dynamic_leds.json based on:
#         1. Which Ultra8 function is currently mapped to this button's CC,
#            discovered by matching against incoming SysEx assignment messages
#            (msg_type=0x02) — no pre-declared control_id required.
#         2. The current lane state in the latest SysEx snapshot (msg_type=0x01).
#       Cold-boot fallback (before any assignment or snapshot arrives):
#         uses the `color` field from the JSON button config.
#
#   LED (dynamic=False):
#       Fixed color from JSON, updated every cycle.
#
#   CORNER LABEL (three-tier resolution):
#       Tier 3 — Live SysEx assignment match → function display name
#                 (e.g. CC20 matches REC_PLY → "REC/PLY")
#       Tier 2 — JSON button-level `label` field (e.g. "REC/PLY")
#       Tier 1 — Auto-fallback: "CC{N}"
#
#   CENTER DISPLAY (drives_display=True only — intended for button A):
#       Drives DISPLAY_LANE, DISPLAY_STATE, DISPLAY_PROGRESS, DISPLAY_SEQ
#       from the current lane snapshot each cycle (same logic as the former
#       ULTRA8_LANE_STATE).
#
# ── State names for dynamic_leds.json ────────────────────────────────────────
#
#   Snapshot state enum:
#     0 (STOPPED, dirty=False) → "empty"
#     0 (STOPPED, dirty=True)  → "stopped"
#     1 (PLAYING)              → "playing"
#     2 (RECORDING)            → "recording"
#     3 (OVERDUBBING)          → "overdubbing"
#     other                    → "error"
#   No snapshot yet            → "waiting"
#
#   Function-specific state mapping is handled by _state_to_name():
#     REC_PLY / PLY_STP: use above enum mapping
#     CLR:               "has_audio" if dirty else "empty"
#     REV:               "active" if reverse else "inactive"
#     UNDO:              "available" / "redo_available" / "unavailable"
#     others:            "waiting" (safe fallback)
#
# ── Usage in inputs.py ────────────────────────────────────────────────────────
#
#   from pyswitch.clients.ultra8.actions.lane_action import ULTRA8_LANE_ACTION
#
#   # Switch A — dynamic, drives center display
#   ULTRA8_LANE_ACTION(
#       message        = _cc(20),
#       cc_number      = 20,
#       label          = "REC/PLY",   # JSON button.label (tier-2)
#       color          = Colors.DARK_GRAY,
#       led_brightness = 0.3,
#       dynamic        = True,
#       drives_display = True,
#       lane           = DEFAULT_PAGE - 1,   # DEFAULT_PAGE from load_default_lane()
#       display        = DISPLAY_FOOTER_1,
#   )
#
#   # Switch B — dynamic, corner label only (no center display)
#   ULTRA8_LANE_ACTION(
#       message        = _cc(24),
#       cc_number      = 24,
#       color          = Colors.DARK_GRAY,
#       led_brightness = 0.3,
#       dynamic        = True,
#       drives_display = False,
#       display        = DISPLAY_FOOTER_2,
#   )
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....colors import Colors
from adafruit_midi.midi_message import MIDIMessage


# ── Center-display constants ──────────────────────────────────────────────────

_STATE_STOPPED     = 0
_STATE_PLAYING     = 1
_STATE_RECORDING   = 2
_STATE_OVERDUBBING = 3

_BAR_WIDTH = 14


def _make_bar(loop_phase):
    """14-char block progress bar from loop_phase (0–127)."""
    filled = max(0, min(_BAR_WIDTH, int(loop_phase / 127 * _BAR_WIDTH)))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _state_to_name(function_name, state, dirty, reverse, undo_redo_state=0):
    """Map a snapshot lane block to a dynamic_leds state name.

    Different function types use different dimensions of the lane block:
      REC_PLY / PLY_STP  — lane recording state enum
      CLR                — dirty flag (has audio content)
      REV                — reverse flag (1 = loop is playing in reverse)
      UNDO               — undo_redo_state (0=none, 1=undo available, 2=redo available)
      others             — "waiting" (safe unknown fallback)

    Note: MON is no longer resolved here; monmode was removed from the SysEx
    protocol in favour of the reverse bit. MON buttons will show "waiting".
    """
    if function_name in ("REC_PLY", "PLY_STP"):
        if state == _STATE_STOPPED:
            return "stopped" if dirty else "empty"
        elif state == _STATE_PLAYING:
            return "playing"
        elif state == _STATE_RECORDING:
            return "recording"
        elif state == _STATE_OVERDUBBING:
            return "overdubbing"
        else:
            return "error"
    elif function_name == "CLR":
        return "has_audio" if dirty else "empty"
    elif function_name == "REV":
        return "active" if reverse else "inactive"
    elif function_name == "UNDO":
        if undo_redo_state == 1:
            return "available"
        elif undo_redo_state == 2:
            return "redo_available"
        else:
            return "unavailable"
    else:
        return "waiting"


def _predict_state_name(function_name, current_state_name):
    """Return the optimistically predicted state_name after a button press.

    Returns None if no reliable prediction exists for this (function, state)
    combination — the caller should skip the optimistic update in that case.
    """
    if function_name == "REC_PLY":
        if current_state_name in ("recording", "overdubbing"):
            return "playing"
        elif current_state_name == "playing":
            return "overdubbing"
        elif current_state_name in ("stopped", "empty"):
            return "recording"
    elif function_name == "PLY_STP":
        if current_state_name == "playing":
            return "stopped"
        elif current_state_name in ("stopped", "recording", "overdubbing"):
            return "playing"
    elif function_name == "CLR":
        return "empty"
    elif function_name == "UNDO":
        if current_state_name == "available":
            return "redo_available"
        elif current_state_name == "redo_available":
            return "available"
    # Unknown functions or UNDO with unavailable state: no prediction
    return None


# ── Public factory ────────────────────────────────────────────────────────────

def ULTRA8_LANE_ACTION(
    message,                        # Raw bytes or callable → bytes, sent on press
    cc_number,                      # CC number for assignment matching (tier-3)
    label          = None,          # Tier-2 label from JSON button.label (may be None)
    color          = Colors.DARK_GRAY,  # Cold-boot / non-dynamic LED color
    led_brightness = 0.3,           # LED brightness [0..1]
    dynamic        = False,         # True → drive LED from dynamic_leds.json
    drives_display = False,         # True → update center display labels each cycle
    lane           = 0,             # Boot-default lane index (0-indexed)
    message_release = None,         # Optional bytes sent on release
    display        = None,          # DisplayLabel for corner
    use_leds       = True,
    id             = None,
    enable_callback = None,
):
    """
    Send a CC on press.  Drive LED and corner label from JSON config and
    SysEx feedback.  Optionally drive the center lane-state display.
    """
    return Action({
        "callback": _LaneActionCallback(
            message         = message,
            cc_number       = cc_number,
            label           = label,
            color           = color,
            led_brightness  = led_brightness,
            dynamic         = dynamic,
            drives_display  = drives_display,
            lane            = lane,
            message_release = message_release,
        ),
        "display":        display,
        "useSwitchLeds":  use_leds,
        "id":             id,
        "enableCallback": enable_callback,
    })


# ── Internal callback ─────────────────────────────────────────────────────────

class _LaneActionCallback(Callback):

    class _RawMessage(MIDIMessage):
        def __init__(self, data):
            self.__data = bytearray(data)
        def __bytes__(self):
            return self.__data

    def __init__(self, message, cc_number, label, color, led_brightness,
                 dynamic, drives_display, lane, message_release):
        super().__init__(mappings=[])

        self._message         = message
        self._message_release = message_release
        self._cc_number       = cc_number
        self._label_static    = label           # tier-2: JSON button.label
        self._color_fallback  = color           # cold-boot color (already a Colors tuple)
        self._led_brightness  = led_brightness
        self._dynamic         = dynamic
        self._drives_display  = drives_display
        self._lane_fallback   = lane

        # Resolved LED state — starts at cold-boot color
        self._current_color      = color
        self._current_brightness = led_brightness

        # Function name discovered via assignment reverse-lookup (tier-3)
        self._dynamic_function = None   # e.g. "REC_PLY"

        # Last resolved dynamic_leds state entry — shared between LED and label
        self._current_led_entry = None  # dict with "color", "brightness", "label"

        # Optimistic state — set on push(), cleared when snapshot seq advances.
        # Structured as a dict with keys "state_name" and "seq" (seq at time of press).
        # None means no pending optimistic update.
        self._optimistic = None

        # Modules and data loaded in init()
        self._page_state   = None
        self._assignments  = None
        self._dynamic_leds = None   # nested dict from dynamic_leds.json

        # Center-display label refs (set in init())
        self._lane_label     = None   # DISPLAY_LANE:     "Lane N"
        self._state_label    = None   # DISPLAY_STATE:    big state text
        self._progress_label = None   # DISPLAY_PROGRESS: progress bar
        self._seq_label      = None   # DISPLAY_SEQ:      seq counter

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener=None):
        self._appl = appl
        super().init(appl, listener)

        # Late-import center-display labels (display.py loads after communication.py)
        try:
            from display import DISPLAY_LANE, DISPLAY_STATE, DISPLAY_PROGRESS, DISPLAY_SEQ
            self._lane_label     = DISPLAY_LANE
            self._state_label    = DISPLAY_STATE
            self._progress_label = DISPLAY_PROGRESS
            self._seq_label      = DISPLAY_SEQ
        except (ImportError, AttributeError):
            pass   # running without display (tests, emulator)

        # Late-import page_state for runtime lane selection
        try:
            from pyswitch.clients.ultra8 import page_state
            self._page_state = page_state
        except ImportError:
            pass

        # Late-import assignment store
        try:
            from pyswitch.clients.ultra8 import assignments
            self._assignments = assignments
        except ImportError:
            pass

        # Load dynamic_leds.json once (module-level cache in lane_config.py)
        if self._dynamic:
            try:
                from pyswitch.clients.ultra8.lane_config import load_dynamic_leds
                self._dynamic_leds = load_dynamic_leds()
            except (ImportError, Exception) as exc:
                print("lane_action: could not load dynamic_leds:", exc)
                self._dynamic_leds = {}

    # ── Button press / release ────────────────────────────────────────────────

    def push(self):
        msg = self._message() if callable(self._message) else self._message
        self._appl.client.midi.send(self._RawMessage(msg))

        # Set optimistic state for immediate LED/label feedback (IG-3)
        if self._dynamic and self._dynamic_function is not None:
            protocol = self._appl.client.protocol
            lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback
            if protocol.snapshot is not None:
                lb = protocol.snapshot.lanes[lane]
                current_name = _state_to_name(
                    self._dynamic_function,
                    lb.state, lb.dirty, lb.reverse, lb.undo_redo_state,
                )
                predicted = _predict_state_name(self._dynamic_function, current_name)
                if predicted is not None:
                    self._optimistic = {
                        "state_name": predicted,
                        "seq":        protocol.snapshot.seq,
                    }

    def release(self):
        if self._message_release:
            msg = self._message_release() if callable(self._message_release) else self._message_release
            self._appl.client.midi.send(self._RawMessage(msg))

    # ── Periodic update ───────────────────────────────────────────────────────

    def update(self):
        super().update()
        self.update_displays()

    # ── Display update ────────────────────────────────────────────────────────

    def update_displays(self):
        protocol = self._appl.client.protocol
        lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback

        # ── Center display (button A only) ────────────────────────────────────
        if self._drives_display:
            self._update_center_display(protocol, lane)

        # ── LED color ─────────────────────────────────────────────────────────
        if self._dynamic:
            self._update_dynamic_led(protocol, lane)
        else:
            self._current_color      = self._color_fallback
            self._current_brightness = self._led_brightness

        # ── Apply LED to NeoPixels ─────────────────────────────────────────────
        self.action.switch_color      = self._current_color
        self.action.switch_brightness = self._current_brightness

        # ── Corner label ──────────────────────────────────────────────────────
        if self.action.label:
            self.action.label.text       = self._resolve_corner_label()
            self.action.label.back_color = self._current_color

    # ── Private: center display ───────────────────────────────────────────────

    def _update_center_display(self, protocol, lane):
        """Drive DISPLAY_LANE / STATE / PROGRESS / SEQ from current snapshot."""
        if self._lane_label:
            self._lane_label.text = "Lane " + str(lane + 1)

        if protocol.snapshot is None:
            if self._state_label:
                self._state_label.text_color = Colors.DARK_GRAY
                self._state_label.text       = "WAITING"
            if self._progress_label:
                self._progress_label.text = ""
            if self._seq_label:
                self._seq_label.text = ""
            return

        lb         = protocol.snapshot.lanes[lane]
        state      = lb.state
        dirty      = lb.dirty
        loop_phase = lb.loop_phase
        seq        = protocol.snapshot.seq

        if state == _STATE_RECORDING:
            state_text  = "RECORDING"
            state_color = Colors.RED
            progress    = ""
        elif state == _STATE_OVERDUBBING:
            state_text  = "OVERDUBBING"   # verify width on hardware; fallback: "OVERDUB"
            state_color = Colors.RED
            progress    = _make_bar(loop_phase)
        elif state == _STATE_PLAYING:
            state_text  = "PLAYING"
            state_color = Colors.LIGHT_GREEN
            progress    = _make_bar(loop_phase)
        elif state == _STATE_STOPPED:
            state_text  = "STOPPED" if dirty else "EMPTY"
            state_color = Colors.DARK_GRAY
            progress    = ""
        else:
            state_text  = "ERROR"
            state_color = Colors.PURPLE
            progress    = ""

        if self._state_label:
            self._state_label.text_color = state_color
            self._state_label.text       = state_text
        if self._progress_label:
            self._progress_label.text = progress
        if self._seq_label:
            self._seq_label.text_color = Colors.DARK_GRAY
            self._seq_label.text       = "#" + str(seq)

    # ── Private: dynamic LED resolution ──────────────────────────────────────

    def _update_dynamic_led(self, protocol, lane):
        """Resolve LED color from dynamic_leds.json × (function × state).

        Also caches the full state entry in self._current_led_entry so that
        _resolve_corner_label() can read the "label" key without a second lookup.
        """

        # Step 1: discover which function is bound to this button's CC
        if self._assignments is not None:
            fn = self._assignments.get_function_by_cc(self._cc_number)
            if fn is not None:
                self._dynamic_function = fn

        # Optimistic state override (IG-3): use predicted state if snapshot has not
        # advanced since the button was pressed. Clear the override once it has.
        if self._optimistic is not None:
            if protocol.snapshot is not None and protocol.snapshot.seq != self._optimistic["seq"]:
                # New snapshot arrived — authoritative state takes over, clear override.
                self._optimistic = None

        # Step 2: map lane block to a state name (uses optimistic if active)
        if protocol.snapshot is None:
            state_name = "waiting"
        elif self._optimistic is not None:
            state_name = self._optimistic["state_name"]
        elif self._dynamic_function:
            lb = protocol.snapshot.lanes[lane]
            state_name = _state_to_name(
                self._dynamic_function,
                lb.state,
                lb.dirty,
                lb.reverse,
                lb.undo_redo_state,
            )
        else:
            # Function not yet known — use generic waiting state
            state_name = "waiting"

        # Step 3: look up LED entry in dynamic_leds.json
        led_entry = None
        if self._dynamic_function and self._dynamic_leds:
            fn_map = self._dynamic_leds.get(self._dynamic_function, {})
            led_entry = fn_map.get(state_name)
            # If the exact state is absent, fall through to fallback
            if led_entry is None and state_name not in ("waiting", "error"):
                led_entry = fn_map.get("waiting")

        # Cache entry for label resolution (shared with _resolve_corner_label)
        self._current_led_entry = led_entry

        if led_entry is not None:
            color_name = led_entry.get("color", "DARK_GRAY")
            self._current_color      = getattr(Colors, color_name, Colors.WHITE)
            self._current_brightness = led_entry.get("brightness", self._led_brightness)
        else:
            # Cold-boot fallback (no assignment yet) or missing dynamic_leds key
            if protocol.snapshot is None:
                self._current_color      = Colors.DARK_GRAY
                self._current_brightness = 0.02
            else:
                self._current_color      = self._color_fallback
                self._current_brightness = self._led_brightness

    # ── Private: corner label ─────────────────────────────────────────────────

    def _resolve_corner_label(self):
        """Four-tier label resolution.

        Tier 3a: state-driven label from dynamic_leds.json state entry "label" key
                 (e.g. REC_PLY in "empty" state → "REC"; in "playing" → "OVDB").
                 null in the JSON means "no override — fall through to tier 3".
        Tier 3:  static function display name from assignment store
                 (e.g. CC20 matches REC_PLY → "REC/PLY")
        Tier 2:  static label from JSON button.label field
        Tier 1:  auto-fallback "CC{N}"
        """
        # Tier 3a (dynamic only): state-driven label from cached dynamic_leds entry
        if self._dynamic and self._current_led_entry is not None:
            state_label = self._current_led_entry.get("label")
            if state_label is not None:
                return state_label

        # Tier 3 (dynamic only): live static function name from assignment store
        if self._dynamic and self._dynamic_function is not None:
            if self._assignments is not None:
                return self._assignments.get_display_label(self._dynamic_function)

        # Tier 2: static JSON label
        if self._label_static is not None:
            return self._label_static

        # Tier 1: auto-fallback
        if self._cc_number is not None:
            return "CC" + str(self._cc_number)
        return "???"
