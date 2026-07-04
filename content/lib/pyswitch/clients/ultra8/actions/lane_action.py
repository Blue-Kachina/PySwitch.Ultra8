##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LANE_ACTION action
#
# Replaces ULTRA8_LANE_STATE and ULTRA8_LABELED_BUTTON for all buttons that
# participate in the Ultra8 LED feedback system.
#
# ── Architecture (post Phase 3/4 state machine refactor) ─────────────────────
#
#   SEND:
#       On button press, sends a raw CC byte sequence to Ultra8.
#
#   LOCAL STATE MACHINE:
#       Each callback holds a _current_state_name string that tracks the
#       button's LED state.  All state changes flow through _apply_state(),
#       which updates _current_state_name, _current_led_entry, _current_color,
#       and _current_brightness in one atomic step.
#
#       State is set from three sources, in priority order:
#         1. push()           — immediate optimistic prediction on button press
#         2. _broadcast()     — cross-button cascade from another button's press
#         3. reconcile_snapshot() — authoritative correction from Ultra8 snapshot
#
#   BROADCAST REGISTRY:
#       All callbacks register in _registry at init() time.  When push()
#       predicts a new state, _broadcast() delivers the update to every other
#       callback.  _receive_state_update() applies direct matches and
#       cross-button cascades defined in _CASCADE.
#
#   SNAPSHOT RECONCILIATION:
#       protocol.py calls reconcile_snapshot(snapshot, lane_index) after each
#       accepted snapshot.  For any callback whose _current_state_name disagrees
#       with the authoritative snapshot state, _apply_state() + _broadcast()
#       are called to correct all affected callbacks as a single consistent pass.
#
#   LED (function button):
#       Color and brightness come from leds.json keyed by (function, state_name).
#       At boot, the "default" state from leds.json is applied immediately
#       without waiting for any SysEx.
#
#   CORNER LABEL (four-tier resolution):
#       Tier 3a — State-driven label from leds.json state entry "label" key
#       Tier 3  — Static function display name from assignment store
#       Tier 2  — JSON button-level `label` field
#       Tier 1  — Auto-fallback "CC{N}"
#
#   CENTER DISPLAY (drives_display=True only — button A):
#       Drives DISPLAY_LANE, DISPLAY_STATE, DISPLAY_PROGRESS, DISPLAY_SEQ
#       from the current snapshot each cycle (reads directly from protocol.snapshot).
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
#   Function-specific state mapping (_state_to_name):
#     REC_PLY / PLY_STP — lane state enum + dirty flag
#     CLR               — dirty flag ("has_audio" if dirty else "empty")
#     REV               — reverse flag ("active" / "inactive")
#     UNDO_REDO         — undo_redo_state (0=unavailable, 1=available, 2=redo_available)
#     others            — "waiting" (safe fallback)
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....colors import Colors
from ....misc import get_current_millis
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
    return "#" * filled + "-" * (_BAR_WIDTH - filled)


def _state_to_name(function_name, state, dirty, reverse, undo_redo_state=0):
    """Map a snapshot lane block to a leds.json state name.

    Different function types use different dimensions of the lane block:
      REC_PLY / PLY_STP  — lane recording state enum + dirty flag
      CLR                — dirty flag (has audio content)
      REV                — reverse flag (1 = loop is playing in reverse)
      UNDO_REDO          — undo_redo_state (0=none, 1=undo available, 2=redo available)
      others             — "waiting" (safe unknown fallback)

    Used both in reconcile_snapshot() (authoritative path) and push()
    (prediction path via _PRESS_DELTA field composition).
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
        if state == _STATE_STOPPED and not dirty:
            return "empty"
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
# None in a field means "use a safe default (False/0/STOPPED) for state_name
# derivation — the exact current value is irrelevant for this function's mapping".
#
# push() applies the delta to compute a predicted state name via _state_to_name(),
# then calls _apply_state() + _broadcast() immediately.

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
    # CLR stops the lane, clears all content, resets undo/redo and reverse.
    ("CLR", "has_audio"):       (_STATE_STOPPED, False, False, 0),

    # ── REV ──────────────────────────────────────────────────────────────────
    # dirty=True: pressing REV from "inactive"/"active" implies audio is present.
    # Without it, the None→False sentinel would satisfy the "empty" check in
    # _state_to_name() and predict the wrong state.
    ("REV", "inactive"):        (None, True, True,  None),
    ("REV", "active"):          (None, True, False, None),

    # ── UNDO_REDO ─────────────────────────────────────────────────────────────
    # After undo, redo becomes available; after redo, undo is available again.
    ("UNDO_REDO", "available"):      (None, None, None, 2),
    ("UNDO_REDO", "redo_available"): (None, None, None, 1),
}


# ── Cross-button cascade table ────────────────────────────────────────────────
#
# When a button press is broadcast, some transitions should drive additional
# buttons to new states.  For example, pressing CLR clears all lane audio, so
# REC_PLY and PLY_STP should also show "empty" and UNDO_REDO "unavailable".
#
# Format: {(function_name, new_state_name): [(target_function, target_state), ...]}
#
# _receive_state_update() checks this table after a broadcast is received.
# Cascades apply _apply_state() only — they do NOT re-broadcast, preventing loops.

_CASCADE = {

    # ── CLR: all audio cleared ───────────────────────────────────────────────
    ("CLR", "empty"): [
        ("REC_PLY",   "empty"),
        ("PLY_STP",   "empty"),
        ("UNDO_REDO", "unavailable"),
        ("REV",       "empty"),
    ],

    # ── REC_PLY: first-pass recording begun (no audio committed yet) ─────────
    ("REC_PLY", "recording"): [
        ("PLY_STP",   "recording"),
        # CLR/REV stay "empty" — dirty=False until recording completes
    ],

    # ── REC_PLY: playback started (audio committed, dirty=True) ─────────────
    ("REC_PLY", "playing"): [
        ("PLY_STP",   "playing"),
        ("CLR",       "has_audio"),
        ("UNDO_REDO", "available"),
        ("REV",       "inactive"),  # audio present; optimistically assume forward
    ],

    # ── REC_PLY: overdubbing ─────────────────────────────────────────────────
    ("REC_PLY", "overdubbing"): [
        ("PLY_STP",   "overdubbing"),
        ("CLR",       "has_audio"),
        ("UNDO_REDO", "available"),
        # REV left unchanged — reverse state unknown at this point
    ],

    # ── REC_PLY: stopped with audio ──────────────────────────────────────────
    ("REC_PLY", "stopped"): [
        ("PLY_STP",   "stopped"),
        ("CLR",       "has_audio"),
        # REV left unchanged
    ],

    # ── REC_PLY: empty (e.g. after undo back to nothing) ────────────────────
    ("REC_PLY", "empty"): [
        ("PLY_STP",   "empty"),
        ("CLR",       "empty"),
        ("UNDO_REDO", "unavailable"),
        ("REV",       "empty"),
    ],

    # ── PLY_STP: playback started ────────────────────────────────────────────
    ("PLY_STP", "playing"): [
        ("REC_PLY",   "playing"),
        ("CLR",       "has_audio"),
    ],

    # ── PLY_STP: stopped ─────────────────────────────────────────────────────
    ("PLY_STP", "stopped"): [
        ("REC_PLY",   "stopped"),
        ("CLR",       "has_audio"),
    ],

}


# ── Module-level callback registry ───────────────────────────────────────────
#
# All _LaneActionCallback instances append self to _registry in init().
# _broadcast() iterates this list to deliver state updates across all buttons.
#
# CircuitPython has no weak references; entries live for the full boot session.
# A clean boot clears the module, so stale entries are never an issue.

_registry = []  # list[_LaneActionCallback]


def _broadcast(function_name, new_state_name, source=None):
    """Deliver a (function_name, new_state_name) update to all registered callbacks.

    Excludes `source` to prevent a callback from receiving its own broadcast.
    Called by push() after a button press prediction and by reconcile_snapshot()
    when the authoritative snapshot state disagrees with local state.

    Args:
        function_name:   e.g. "REC_PLY"
        new_state_name:  e.g. "recording"
        source:          the initiating _LaneActionCallback; excluded from delivery
    """
    for cb in _registry:
        if cb is not source:
            cb._receive_state_update(function_name, new_state_name)


def reconcile_snapshot(snapshot, lane_index):
    """Push authoritative snapshot state to all registered callbacks.

    Called by protocol.py immediately after each accepted snapshot.  For each
    registered callback, computes the authoritative leds.json state name from
    the snapshot lane block and calls _apply_state() + _broadcast() if the
    local state disagrees.

    This is the sole mechanism for snapshot-driven LED updates.
    _update_dynamic_led() no longer re-derives state from the snapshot each cycle.

    Args:
        snapshot:    the freshly accepted _Snapshot from protocol.py
        lane_index:  0-indexed lane this NANO4 device controls
    """
    lb = snapshot.lanes[lane_index]
    for cb in _registry:
        if cb._dynamic_function is None:
            continue
        authoritative = _state_to_name(
            cb._dynamic_function,
            lb.state, lb.dirty, lb.reverse, lb.undo_redo_state,
        )
        if authoritative != cb._current_state_name:
            cb._apply_state(authoritative)
            _broadcast(cb._dynamic_function, authoritative, source=cb)


# ── Public factory ────────────────────────────────────────────────────────────

def ULTRA8_LANE_ACTION(
    message,                        # Raw bytes or callable → bytes, sent on press
    cc_number,                      # CC number for assignment reassignment detection
    label          = None,          # Tier-2 label (JSON button.label; may be None)
    function       = None,          # leds.json function name (e.g. "REC_PLY"); binds at init()
    drives_display = False,         # True → update center display labels each cycle
    lane           = 0,             # Boot-default lane index (0-indexed)
    message_release = None,         # Optional bytes sent on release
    display        = None,          # DisplayLabel for corner
    use_leds       = True,
    id             = None,
    enable_callback = None,
    tuner_led_role = None,          # Phase 7: "flat_main"|"flat_secondary"|"sharp_secondary"|"sharp_main"|None
):
    """
    Send a CC on press.  Drive LED and corner label from leds.json.
    Optionally drive the center lane-state display.

    The `function` parameter (e.g. "REC_PLY") binds the LED function at
    init() time so the button shows its correct default state immediately
    on boot, without waiting for a SysEx assignment message.

    All LED state changes go through _apply_state() — called from:
      push()               — optimistic prediction on button press
      _receive_state_update() — cross-button broadcast from another callback
      reconcile_snapshot() — authoritative correction from Ultra8 snapshot

    tuner_led_role (Phase 7): when set, this button participates in the
      tuner LED overlay.  Physical layout:
        "flat_main"       — front-left  (Switch A): yellow/red when flat
        "flat_secondary"  — back-left   (Switch 1): red when very flat
        "sharp_secondary" — back-right  (Switch 2): red when very sharp
        "sharp_main"      — front-right (Switch B): yellow/red when sharp
    """
    return Action({
        "callback": _LaneActionCallback(
            message         = message,
            cc_number       = cc_number,
            label           = label,
            function        = function,
            drives_display  = drives_display,
            lane            = lane,
            message_release = message_release,
            tuner_led_role  = tuner_led_role,
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

    def __init__(self, message, cc_number, label, function,
                 drives_display, lane, message_release, tuner_led_role=None):
        super().__init__(mappings=[])

        self._message         = message
        self._message_release = message_release
        self._cc_number       = cc_number
        self._label_static    = label           # tier-2: JSON button.label (may be None)
        self._json_function   = function        # JSON-declared function name; bound at init()
        self._drives_display  = drives_display
        self._lane_fallback   = lane
        self._tuner_led_role  = tuner_led_role  # Phase 7: physical button role in tuner LED overlay

        # ── Local state machine ───────────────────────────────────────────────
        # All state changes go through _apply_state().  None until init() runs.
        self._current_state_name = None         # e.g. "empty", "recording"
        self._dynamic_function   = None         # e.g. "REC_PLY"; set at init() from _json_function
        self._default_state_name = None         # boot state from leds.json "default" key

        # ── Resolved LED state ────────────────────────────────────────────────
        # Set by _apply_state(); read every cycle in update_displays().
        self._current_color      = Colors.DARK_GRAY
        self._current_brightness = 0.02
        self._current_led_entry  = None         # cached leds.json state entry dict

        # ── Modules loaded at init() ──────────────────────────────────────────
        self._page_state   = None
        self._assignments  = None
        self._dynamic_leds = None               # nested dict from leds.json

        # ── Dead-reckoning state (Unit A.4) ──────────────────────────────────────
        self._dr_phase    = 0               # loop_phase from last accepted snapshot
        self._dr_ts       = 0               # get_current_millis() at that snapshot
        self._dr_last_seq = None            # snapshot seq at last DR anchor; None = never anchored
        self._dr_period   = 0               # estimated loop period in ms; 0 = unknown

        # ── Progress bar ref (set in init()) ─────────────────────────────────
        self._progress_bar   = None             # PROGRESS_BAR from display.py

        # ── Center-display label refs (set in init()) ─────────────────────────
        self._lane_label     = None             # DISPLAY_LANE:     "Lane N"
        self._state_label    = None             # DISPLAY_STATE:    big state text
        self._seq_label      = None             # DISPLAY_SEQ:      seq counter

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener=None):
        self._appl = appl
        super().init(appl, listener)

        # Late-import center-display labels (display.py loads after communication.py)
        try:
            from display import DISPLAY_LANE, DISPLAY_STATE, DISPLAY_SEQ, PROGRESS_BAR
            self._lane_label    = DISPLAY_LANE
            self._state_label   = DISPLAY_STATE
            self._seq_label     = DISPLAY_SEQ
            self._progress_bar  = PROGRESS_BAR
        except (ImportError, AttributeError):
            pass   # running without display (tests, emulator)

        # Late-import page_state for runtime lane selection
        try:
            from pyswitch.clients.ultra8 import page_state
            self._page_state = page_state
        except ImportError:
            pass

        # Late-import assignment store for runtime reassignment detection
        try:
            from pyswitch.clients.ultra8 import assignments
            self._assignments = assignments
        except ImportError:
            pass

        # Load leds.json and bind function at init() time.
        # This eliminates the ~1 s boot delay that arose from waiting for
        # the SysEx 0x02 assignment message before _dynamic_function was set.
        if self._json_function is not None:
            try:
                from pyswitch.clients.ultra8.lane_config import load_dynamic_leds, get_led_default
                self._dynamic_leds = load_dynamic_leds()
            except (ImportError, Exception) as exc:
                print("lane_action: could not load dynamic_leds:", exc)
                self._dynamic_leds = {}

            self._dynamic_function = self._json_function

            # Read the default state name from leds.json and apply it immediately.
            # This replaces the DARK_GRAY cold-boot fallback for function buttons.
            if self._dynamic_leds:
                try:
                    default_state = get_led_default(self._dynamic_leds, self._dynamic_function)
                    if default_state is not None:
                        self._default_state_name = default_state
                    else:
                        print("lane_action: no default state in leds.json for",
                              self._dynamic_function)
                except Exception as exc:
                    print("lane_action: error reading default state:", exc)

            boot_state = self._default_state_name if self._default_state_name is not None else "waiting"
            self._current_state_name = boot_state
            self._apply_state(boot_state)

        # Register in the module-level broadcast registry.
        # Must be last so the callback is fully initialised before any broadcast.
        _registry.append(self)

    # ── State machine ─────────────────────────────────────────────────────────

    def _apply_state(self, state_name):
        """Apply state_name and update all derived LED values.

        This is the single point of truth for LED state changes.  Updates:
          _current_state_name   — authoritative local state
          _current_led_entry    — cached leds.json entry (used by label resolver)
          _current_color        — NeoPixel color tuple
          _current_brightness   — NeoPixel brightness [0..1]

        If the function or state is absent from leds.json, falls through to
        the "waiting" entry.  If "waiting" is also absent, leaves color/
        brightness at their last values (no crash).
        """
        self._current_state_name = state_name

        if self._dynamic_function and self._dynamic_leds:
            fn_data    = self._dynamic_leds.get(self._dynamic_function, {})
            states_map = fn_data.get("states", {})
            entry      = states_map.get(state_name)

            # Fall through to "waiting" entry for unknown or error states
            if entry is None and state_name not in ("waiting", "error"):
                entry = states_map.get("waiting")

            self._current_led_entry = entry

            if entry is not None:
                color_name               = entry.get("color", "DARK_GRAY")
                self._current_color      = getattr(Colors, color_name, Colors.WHITE)
                self._current_brightness = entry.get("brightness", 0.3)

    def _receive_state_update(self, function_name, new_state_name):
        """Handle an inbound state broadcast from another callback.

        Applies the update directly if function_name matches this button's
        function.  Also handles cross-button cascades defined in _CASCADE.

        Does NOT itself broadcast further — all cascade application is local
        only (via _apply_state).  This prevents cascade loops.
        """
        if self._dynamic_function is None:
            return

        # Direct match: this button's function received a state update
        if function_name == self._dynamic_function:
            self._apply_state(new_state_name)
            return

        # Cascade: check if this broadcast triggers a cascaded update to our function
        cascades = _CASCADE.get((function_name, new_state_name))
        if cascades:
            for (target_fn, target_state) in cascades:
                if target_fn == self._dynamic_function:
                    self._apply_state(target_state)
                    return

    # ── Button press / release ────────────────────────────────────────────────

    def push(self):
        # ── Tuner intercept ───────────────────────────────────────────────────
        # If the tuner overlay is active, any lane button press is re-routed to
        # exit tuner mode (send CC26=0) instead of the normal lane CC.  This
        # keeps all four footswitches functional as "exit tuner" during tuning.
        try:
            from pyswitch.clients.ultra8 import tuner_state, page_state
            if tuner_state.is_active():
                lane_zero = page_state.get() - 1
                channel_byte = 0xB0 + (lane_zero & 0x0F)
                self._appl.client.midi.send(self._RawMessage([channel_byte, 26, 0]))
                tuner_state.exit_to_normal()
                return
        except ImportError:
            pass
        # ─────────────────────────────────────────────────────────────────────

        msg = self._message() if callable(self._message) else self._message
        self._appl.client.midi.send(self._RawMessage(msg))

        # No prediction possible without a bound function or initialised state.
        if self._dynamic_function is None or self._current_state_name is None:
            return

        # Look up press prediction for (function, current_state).
        delta = _PRESS_DELTA.get((self._dynamic_function, self._current_state_name))
        if delta is None:
            return  # no prediction for this combination; hold current state

        # Compose predicted state name from delta fields.
        # None values in the delta are irrelevant to this function's state mapping;
        # safe defaults (STOPPED/False/0) are substituted — the function's
        # _state_to_name() branch only reads the field(s) that the delta specifies.
        d_state, d_dirty, d_reverse, d_undo = delta
        predicted_name = _state_to_name(
            self._dynamic_function,
            d_state   if d_state   is not None else _STATE_STOPPED,
            d_dirty   if d_dirty   is not None else False,
            d_reverse if d_reverse is not None else False,
            d_undo    if d_undo    is not None else 0,
        )

        # Apply locally and broadcast to all other registered callbacks.
        self._apply_state(predicted_name)
        _broadcast(self._dynamic_function, predicted_name, source=self)

    def release(self):
        if self._message_release:
            msg = (self._message_release()
                   if callable(self._message_release)
                   else self._message_release)
            self._appl.client.midi.send(self._RawMessage(msg))

    # ── Periodic update ───────────────────────────────────────────────────────

    def update(self):
        super().update()
        self.update_displays()

    # ── Display update ────────────────────────────────────────────────────────

    def update_displays(self):
        protocol = self._appl.client.protocol
        lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback

        # Center display (button A only — drives_display=True)
        if self._drives_display:
            self._update_center_display(protocol, lane)

        # LED reassignment check — runs every cycle for all function buttons.
        # This path detects Ultra8 runtime control reassignments (0x02 messages)
        # and is distinct from state derivation.  See _update_dynamic_led().
        if self._dynamic_function is not None:
            self._update_dynamic_led(protocol, lane)

        # Tuner LED override — static dim state while tuner is active.
        # Labels are cleared and LEDs hold dim gray for the duration of tuner
        # mode.  No flat/sharp/confidence animation; the TFT display handles
        # all tuner feedback.  Re-enable dynamic LED animation by replacing
        # the static color assignment with _get_tuner_led_color(tuner_state).
        if self._tuner_led_role is not None:
            try:
                from pyswitch.clients.ultra8 import tuner_state
                if tuner_state.is_active():
                    self.action.switch_color      = Colors.DARK_GRAY
                    self.action.switch_brightness = 0.02
                    if self.action.label:
                        self.action.label.text       = ""
                        self.action.label.back_color = Colors.BLACK
                    return   # skip normal LED apply below
            except ImportError:
                pass

        # Apply LED to NeoPixels (normal path — tuner not active)
        self.action.switch_color      = self._current_color
        self.action.switch_brightness = self._current_brightness

        # Corner label
        if self.action.label:
            self.action.label.text       = self._resolve_corner_label()
            self.action.label.back_color = self._current_color

    # ── Private: dead-reckoning ───────────────────────────────────────────────

    def _get_phase(self, protocol, lane):
        """Return extrapolated loop_phase (0–127) using dead-reckoning.

        If a loop period is known from the timing metadata message, advance
        _dr_phase by the time elapsed since the last snapshot anchor.
        Falls back to the raw snapshot phase when period is unknown (0).
        Only extrapolates in PLAYING or OVERDUBBING states.
        """
        period_ms = protocol.lane_periods[lane] if hasattr(protocol, 'lane_periods') else 0
        if period_ms <= 0:
            period_ms = self._dr_period   # locally estimated fallback (from consecutive snapshots)
        if period_ms <= 0:
            return self._dr_phase         # period still unknown; return raw snapshot phase
        elapsed = get_current_millis() - self._dr_ts
        return int(self._dr_phase + elapsed * 127 // period_ms) % 128

    def _has_loop_confidence(self, protocol, lane):
        """True once both loop length and current position are trustworthy.

        Length: either Ultra8 has sent authoritative timing metadata
        (msg_type 0x03 → protocol.lane_periods[lane] > 0), or two consecutive
        snapshots taken *while actively playing back* let us derive a local
        period estimate (self._dr_period > 0).

        Position: dead-reckoning is only anchored while state is PLAYING or
        OVERDUBBING (see _update_center_display), so a non-zero period here
        always coincides with a fresh position anchor from this playback
        session — never a stale value carried over from a prior recording or
        stop.
        """
        period_ms = protocol.lane_periods[lane] if hasattr(protocol, 'lane_periods') else 0
        if period_ms > 0:
            return True
        return self._dr_period > 0

    # ── Private: center display ───────────────────────────────────────────────

    def _update_center_display(self, protocol, lane):
        """Drive DISPLAY_LANE / STATE / PROGRESS / SEQ from current snapshot."""
        # Yield to tuner overlay when active — tuner_action owns the center display then
        try:
            from pyswitch.clients.ultra8 import tuner_state
            if tuner_state.is_active():
                if self._progress_bar:
                    self._progress_bar.hide()
                return
        except ImportError:
            pass

        if self._lane_label:
            self._lane_label.text = "Lane " + str(lane + 1)

        if protocol.snapshot is None:
            if self._progress_bar:
                self._progress_bar.hide()
            if self._state_label:
                self._state_label.text_color = Colors.DARK_GRAY
                self._state_label.text       = "WAITING"
            if self._seq_label:
                self._seq_label.text = ""
            return

        lb    = protocol.snapshot.lanes[lane]
        state = lb.state
        dirty = lb.dirty
        seq   = protocol.snapshot.seq

        # Anchor dead-reckoning on each NEW snapshot (Unit A.4), but only while
        # actively playing back. RECORDING/STOPPED loop_phase values don't
        # represent a loop position yet, so anchoring across, e.g., a
        # RECORDING→PLAYING boundary produced a garbage period estimate and
        # made the progress bar appear with a bogus length/position. Leaving
        # active playback drops any anchor/estimate so the next playback
        # session has to re-earn confidence rather than inherit stale values.
        #
        # Gated by seq so repeated calls between 1 Hz pulses do NOT reset
        # _dr_ts -- resetting it every frame makes elapsed always ~0 and
        # prevents _get_phase() from extrapolating between pulses.
        now = get_current_millis()
        if state in (_STATE_PLAYING, _STATE_OVERDUBBING):
            if seq != self._dr_last_seq:
                if self._dr_last_seq is not None and self._dr_ts > 0:
                    # Estimate loop period from phase progression between snapshots.
                    # Fallback for when msg_type 0x03 timing messages are not sent.
                    elapsed_ms  = now - self._dr_ts
                    phase_delta = (lb.loop_phase - self._dr_phase) % 128
                    if phase_delta > 0:
                        self._dr_period = elapsed_ms * 127 // phase_delta
                self._dr_phase    = lb.loop_phase
                self._dr_ts       = now
                self._dr_last_seq = seq
        else:
            self._dr_phase    = 0
            self._dr_ts       = 0
            self._dr_last_seq = None
            self._dr_period   = 0

        if state == _STATE_RECORDING:
            state_text  = "RECORDING"
            state_color = Colors.RED
        elif state == _STATE_OVERDUBBING:
            state_text  = "OVERDUBBING"   # verify width on hardware; fallback: "OVERDUB"
            state_color = Colors.RED
        elif state == _STATE_PLAYING:
            state_text  = "PLAYING"
            state_color = Colors.LIGHT_GREEN
        elif state == _STATE_STOPPED:
            state_text  = "STOPPED" if dirty else "EMPTY"
            state_color = Colors.DARK_GRAY
        else:
            state_text  = "ERROR"
            state_color = Colors.PURPLE

        if self._state_label:
            self._state_label.text_color = state_color
            self._state_label.text       = state_text

        # ── Loop progress bar ─────────────────────────────────────────────────
        # Visible during PLAYING (green) and OVERDUBBING (red), and only once
        # we have high confidence in both loop length and current position
        # (see _has_loop_confidence). Otherwise it stays hidden rather than
        # showing a bar built on a guessed/zero length or a stale position.
        # Dead-reckoning phase advances between snapshots for smooth motion.
        if self._progress_bar:
            if state in (_STATE_PLAYING, _STATE_OVERDUBBING) and self._has_loop_confidence(protocol, lane):
                self._progress_bar.update(
                    phase    = self._get_phase(protocol, lane),
                    is_green = (state == _STATE_PLAYING),
                )
            else:
                self._progress_bar.hide()

        # ── Waveform animation placeholder ────────────────────────────────────
        # Dead-reckoning phase is available via self._get_phase(protocol, lane).
        # Bitmap-based waveform rendering was implemented but displayio.Bitmap
        # runtime writes do not propagate to the display in this firmware/driver
        # combination. See docs/animation_brainstorming.md §Bitmap Display
        # Investigation for details. Next approach: adafruit_display_shapes.Rect
        # playhead cursor (confirmed update path).

        if self._seq_label:
            self._seq_label.text_color = Colors.DARK_GRAY
            self._seq_label.text       = "#" + str(seq)

    # ── Private: tuner LED overlay ────────────────────────────────────────────────

    def _get_tuner_led_color(self, ts):
        """Return (color, brightness) for this button's tuner LED role.

        Mapping (tuner_implementation.md §NANO4 LED Design):

          No signal  (sig < 8)           → dim white (all buttons)
          Listening  (sig ≥ 8, conf = 0) → dim yellow (all buttons)
          In tune    (cents ≤ 3)         → bright green (all buttons)
          Slightly flat  (4–15c flat)    → flat_main yellow; others green
          Very flat  (> 15c flat)        → flat_main + flat_secondary red; others off
          Slightly sharp (4–15c sharp)   → sharp_main yellow; others green
          Very sharp (> 15c sharp)       → sharp_main + sharp_secondary red; others off

        While not in TUNER_ACTIVE (PENDING / NO_DATA / NORMAL_PENDING):
          → dim gray on all buttons.
        """
        state = ts.get_state()

        if state != ts.TUNER_ACTIVE:
            return Colors.DARK_GRAY, 0.02

        sig   = ts.last_signal_level or 0
        conf  = ts.last_confidence   or 0

        if sig < 8:
            # No signal
            return Colors.WHITE, 0.04

        if conf == 0 or ts.last_note is None:
            # Signal present but pitch not yet detected (Listening...)
            return Colors.YELLOW, 0.08

        # Pitch detected — use cents data
        cents  = ts.last_cents_mag  or 0
        flat   = (ts.last_cents_sign == 0)   # 0=flat, 1=sharp
        role   = self._tuner_led_role

        if cents <= 3:
            # In tune — all green
            return Colors.LIGHT_GREEN, 1.0

        if cents <= 15:
            # Slightly off — primary side shows yellow; others dim
            if flat and role == "flat_main":
                return Colors.YELLOW, 0.8
            if (not flat) and role == "sharp_main":
                return Colors.YELLOW, 0.8
            return Colors.DARK_GRAY, 0.02

        # Very off (> 15c) — primary and secondary on that side show red
        if flat and role in ("flat_main", "flat_secondary"):
            return Colors.RED, 1.0
        if (not flat) and role in ("sharp_main", "sharp_secondary"):
            return Colors.RED, 1.0
        return Colors.DARK_GRAY, 0.02

    # ── Private: dynamic LED reassignment detection ───────────────────────────────────────────

    def _update_dynamic_led(self, protocol, lane):
        """Detect runtime function reassignment and re-sync LED state.

        This method runs every display cycle to catch the case where Ultra8
        sends a 0x02 assignment message that remaps a CC to a different
        function.  It is NOT the normal LED update path -- LED state is owned
        by the local state machine (_apply_state) and updated by push(),
        _receive_state_update(), or reconcile_snapshot().

        This check is intentionally retained every cycle (not just on
        assignment message receipt) because assignment data may arrive at any
        time and the LED must reflect the live binding.
        """
        if self._assignments is None:
            return

        fn = self._assignments.get_function_by_cc(self._cc_number)
        if fn is None or fn == self._dynamic_function:
            return   # no reassignment; nothing to do

        # Function reassigned -- update binding and re-sync LED state from snapshot
        self._dynamic_function = fn
        if protocol.snapshot is not None:
            lb = protocol.snapshot.lanes[lane]
            state_name = _state_to_name(
                fn, lb.state, lb.dirty, lb.reverse, lb.undo_redo_state,
            )
        else:
            state_name = self._default_state_name or "waiting"
        self._apply_state(state_name)

    # ── Private: corner label ────────────────────────────────────────────────────────────────

    def _resolve_corner_label(self):
        """Four-tier label resolution.

        Tier 3a: state-driven label from leds.json state entry "label" key.
                 A null "label" in JSON means no override -- fall through.
        Tier 3:  static function display name from assignment store.
        Tier 2:  static label from JSON button.label field.
        Tier 1:  auto-fallback "CC{N}".
        """
        # Tier 3a: state-driven label from cached leds.json entry
        if self._dynamic_function is not None and self._current_led_entry is not None:
            state_label = self._current_led_entry.get("label")
            if state_label is not None:
                return state_label

        # Tier 3: live static function name from assignment store
        if self._dynamic_function is not None and self._assignments is not None:
            return self._assignments.get_display_label(self._dynamic_function)

        # Tier 2: static JSON label
        if self._label_static is not None:
            return self._label_static

        # Tier 1: auto-fallback
        if self._cc_number is not None:
            return "CC" + str(self._cc_number)
        return "???"
