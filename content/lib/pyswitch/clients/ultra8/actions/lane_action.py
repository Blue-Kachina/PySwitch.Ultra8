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
#       Drives NeoPixels from leds.json based on:
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
# ── State names for leds.json ────────────────────────────────────────────────
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
    """Map a snapshot lane block to a leds.json state name.

    Different function types use different dimensions of the lane block:
      REC_PLY / PLY_STP  — lane recording state enum
      CLR                — dirty flag (has audio content)
      REV                — reverse flag (1 = loop is playing in reverse)
      UNDO               — undo_redo_state (0=none, 1=undo available, 2=redo available)
      others             — "waiting" (safe unknown fallback)

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
    elif function_name == "UNDO_REDO":
        if undo_redo_state == 1:
            return "available"
        elif undo_redo_state == 2:
            return "redo_available"
        else:
            return "unavailable"
    else:
        return "waiting"


# ── Optimistic press-delta table ─────────────────────────────────────────────
#
# Maps (function_name, current_state_name) → (state, dirty, reverse, undo_redo_state)
# describing the predicted lane block immediately after a button press.
#
# None in a slot means "keep this field from the current snapshot unchanged".
# When a button is pressed, the matching delta is merged with the current lane
# block and written to the shared optimistic_lane store so that ALL buttons on
# the lane update instantly — not just the one that was pressed.
#
# Omitted combinations (e.g. CLR on "empty") produce no prediction; the buttons
# hold their pre-press state until the next real SysEx snapshot arrives.

_PRESS_DELTA = {
    # ── REC_PLY ──────────────────────────────────────────────────────────────
    ("REC_PLY", "empty"):       (_STATE_RECORDING,   False, None, None),
    ("REC_PLY", "stopped"):     (_STATE_OVERDUBBING, True,  None, None),
    ("REC_PLY", "playing"):     (_STATE_OVERDUBBING, True,  None, None),
    ("REC_PLY", "recording"):   (_STATE_PLAYING,     True,  None, None),
    ("REC_PLY", "overdubbing"): (_STATE_PLAYING,     True,  None, None),
    ("REC_PLY", "waiting"):     (_STATE_RECORDING,   False, None, None),

    # ── PLY_STP ──────────────────────────────────────────────────────────────
    ("PLY_STP", "playing"):     (_STATE_STOPPED, True, None, None),
    ("PLY_STP", "stopped"):     (_STATE_PLAYING, True, None, None),
    ("PLY_STP", "recording"):   (_STATE_PLAYING, True, None, None),
    ("PLY_STP", "overdubbing"): (_STATE_PLAYING, True, None, None),

    # ── CLR ──────────────────────────────────────────────────────────────────
    # CLR stops the lane, clears content, and resets undo/redo and reverse.
    ("CLR", "has_audio"):       (_STATE_STOPPED, False, False, 0),

    # ── REV ──────────────────────────────────────────────────────────────────
    ("REV", "inactive"):        (None, None, True,  None),
    ("REV", "active"):          (None, None, False, None),

    # ── UNDO_REDO ─────────────────────────────────────────────────────────────
    # After undo, redo becomes available; after redo, undo is available again.
    ("UNDO_REDO", "available"):      (None, None, None, 2),
    ("UNDO_REDO", "redo_available"): (None, None, None, 1),
}


# ── Public factory ────────────────────────────────────────────────────────────

def ULTRA8_LANE_ACTION(
    message,                        # Raw bytes or callable → bytes, sent on press
    cc_number,                      # CC number for assignment matching (tier-3)
    label          = None,          # Tier-2 label from JSON button.label (may be None)
    color          = Colors.DARK_GRAY,  # Cold-boot / non-dynamic LED color
    led_brightness = 0.3,           # LED brightness [0..1]
    dynamic        = False,         # True → drive LED from leds.json
    function       = None,          # leds.json function name (e.g. "REC_PLY"); binds at init()
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

    When `function` is provided (e.g. from the lane JSON "function" key via
    get_gesture()), the LED function binding is established at init() time
    without waiting for a SysEx assignment message (~1 s delay eliminated).
    """
    return Action({
        "callback": _LaneActionCallback(
            message         = message,
            cc_number       = cc_number,
            label           = label,
            color           = color,
            led_brightness  = led_brightness,
            dynamic         = dynamic,
            function        = function,
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
                 dynamic, function, drives_display, lane, message_release):
        super().__init__(mappings=[])

        self._message         = message
        self._message_release = message_release
        self._cc_number       = cc_number
        self._label_static    = label           # tier-2: JSON button.label
        self._color_fallback  = color           # cold-boot color (already a Colors tuple)
        self._led_brightness  = led_brightness
        self._dynamic         = dynamic
        self._json_function   = function        # JSON-declared function name; bound at init()
        self._drives_display  = drives_display
        self._lane_fallback   = lane

        # Resolved LED state — starts at cold-boot color
        self._current_color      = color
        self._current_brightness = led_brightness

        # Function name: set from _json_function at init(); may be overwritten by
        # the live SysEx 0x02 assignment reverse-lookup at runtime.
        self._dynamic_function = None   # e.g. "REC_PLY"

        # Default state name from leds.json — applied at init() and used as the
        # display state when no snapshot has arrived yet.
        self._default_state_name = None   # e.g. "empty"

        # Last resolved leds.json state entry — shared between LED and label
        self._current_led_entry = None  # dict with "color", "brightness", "label"

        # Modules and data loaded in init()
        self._page_state      = None
        self._assignments     = None
        self._dynamic_leds    = None   # nested dict from leds.json
        self._optimistic_lane = None   # shared optimistic_lane module

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

        # Late-import shared optimistic lane state
        try:
            from pyswitch.clients.ultra8 import optimistic_lane
            self._optimistic_lane = optimistic_lane
        except ImportError:
            pass

        # Load leds.json once (module-level cache in lane_config.py)
        if self._dynamic:
            try:
                from pyswitch.clients.ultra8.lane_config import load_dynamic_leds, get_led_default
                self._dynamic_leds = load_dynamic_leds()
            except (ImportError, Exception) as exc:
                print("lane_action: could not load dynamic_leds:", exc)
                self._dynamic_leds = {}

            # Bind function name from JSON at init() time, eliminating the
            # ~1 s boot delay caused by waiting for the SysEx 0x02 message.
            # The live SysEx assignment path in _update_dynamic_led() will
            # still overwrite _dynamic_function if Ultra8 sends a reassignment.
            if self._json_function is not None:
                self._dynamic_function = self._json_function

            # Apply the default LED state from leds.json immediately at boot.
            # This replaces the DARK_GRAY cold-boot fallback for buttons that
            # declare a function key.
            if self._dynamic_function is not None and self._dynamic_leds:
                try:
                    default_state = get_led_default(self._dynamic_leds, self._dynamic_function)
                    if default_state is not None:
                        fn_data = self._dynamic_leds.get(self._dynamic_function, {})
                        entry = fn_data.get("states", {}).get(default_state)
                        if entry is not None:
                            color_name = entry.get("color", "DARK_GRAY")
                            self._current_color      = getattr(Colors, color_name, Colors.WHITE)
                            self._current_brightness = entry.get("brightness", self._led_brightness)
                            self._current_led_entry  = entry
                            self._default_state_name = default_state
                        else:
                            print("lane_action: default state", repr(default_state),
                                  "not found in leds.json for", self._dynamic_function)
                    else:
                        print("lane_action: no default state in leds.json for", self._dynamic_function)
                except Exception as exc:
                    print("lane_action: error applying default state:", exc)

    # ── Button press / release ────────────────────────────────────────────────

    def push(self):
        msg = self._message() if callable(self._message) else self._message
        self._appl.client.midi.send(self._RawMessage(msg))

        # Publish a predicted lane block to the shared optimistic_lane store so
        # that all buttons on this lane update instantly and consistently.
        if (self._dynamic
                and self._dynamic_function is not None
                and self._optimistic_lane is not None):
            protocol = self._appl.client.protocol
            lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback

            if protocol.snapshot is not None:
                lb = protocol.snapshot.lanes[lane]
                cur_state, cur_dirty  = lb.state, lb.dirty
                cur_reverse, cur_undo = lb.reverse, lb.undo_redo_state
                snap_seq              = protocol.snapshot.seq
            elif self._default_state_name is not None:
                # Pre-snapshot boot: use safe defaults and seq=-1 so the
                # prediction is discarded the moment any real snapshot arrives.
                cur_state, cur_dirty  = _STATE_STOPPED, False
                cur_reverse, cur_undo = False, 0
                snap_seq              = -1
            else:
                return  # no basis for a prediction

            # If a previous press left a pending optimistic prediction for this
            # lane (snapshot hasn't advanced yet), use it as the current state.
            # This ensures a rapid second press (e.g. CLR immediately after
            # recording completes) sees the post-first-press state, not the
            # stale snapshot.
            opt = self._optimistic_lane.get(lane)
            if opt is not None:
                opt_state, opt_dirty, opt_reverse, opt_undo, opt_seq = opt
                if opt_seq == snap_seq:
                    cur_state, cur_dirty  = opt_state, opt_dirty
                    cur_reverse, cur_undo = opt_reverse, opt_undo

            current_name = _state_to_name(
                self._dynamic_function,
                cur_state, cur_dirty, cur_reverse, cur_undo,
            )
            delta = _PRESS_DELTA.get((self._dynamic_function, current_name))
            if delta is not None:
                d_state, d_dirty, d_reverse, d_undo = delta
                self._optimistic_lane.set(
                    lane,
                    d_state   if d_state   is not None else cur_state,
                    d_dirty   if d_dirty   is not None else cur_dirty,
                    d_reverse if d_reverse is not None else cur_reverse,
                    d_undo    if d_undo    is not None else cur_undo,
                    snap_seq,
                )

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
        """Resolve LED color from leds.json × (function × state).

        Also caches the full state entry in self._current_led_entry so that
        _resolve_corner_label() can read the "label" key without a second lookup.
        """

        # Step 1: discover which function is bound to this button's CC
        if self._assignments is not None:
            fn = self._assignments.get_function_by_cc(self._cc_number)
            if fn is not None:
                self._dynamic_function = fn

        # Step 2: resolve lane block — shared optimistic prediction takes precedence.
        # All buttons on the same lane see the same prediction, giving consistent
        # feedback across the whole surface the instant any button is pressed.
        opt = self._optimistic_lane.get(lane) if self._optimistic_lane is not None else None
        if opt is not None:
            opt_state, opt_dirty, opt_reverse, opt_undo, opt_seq = opt
            if protocol.snapshot is not None and protocol.snapshot.seq != opt_seq:
                # A newer snapshot arrived — authoritative state wins.
                self._optimistic_lane.clear(lane)
                opt = None

        if opt is not None:
            state_name = _state_to_name(
                self._dynamic_function,
                opt_state, opt_dirty, opt_reverse, opt_undo,
            ) if self._dynamic_function else "waiting"
        elif protocol.snapshot is None:
            state_name = self._default_state_name if self._default_state_name is not None else "waiting"
        elif self._dynamic_function:
            lb = protocol.snapshot.lanes[lane]
            state_name = _state_to_name(
                self._dynamic_function,
                lb.state, lb.dirty, lb.reverse, lb.undo_redo_state,
            )
        else:
            state_name = "waiting"

        # Step 3: look up LED entry in leds.json
        led_entry = None
        if self._dynamic_function and self._dynamic_leds:
            fn_data = self._dynamic_leds.get(self._dynamic_function, {})
            states_map = fn_data.get("states", {})
            led_entry = states_map.get(state_name)
            # If the exact state is absent, fall through to "waiting" fallback
            if led_entry is None and state_name not in ("waiting", "error"):
                led_entry = states_map.get("waiting")

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

        Tier 3a: state-driven label from leds.json state entry "label" key.
                 null label in the JSON means no override -- fall through to tier 3.
        Tier 3:  static function display name from assignment store.
        Tier 2:  static label from JSON button.label field.
        Tier 1:  auto-fallback "CC{N}".
        """
        # Tier 3a (dynamic only): state-driven label from cached leds.json entry
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
