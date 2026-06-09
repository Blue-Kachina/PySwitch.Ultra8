##############################################################################
#
# Ultra8 PySwitch — ULTRA8_TUNER_ACTION action
#
# Tuner Ph1: New module.
#
# Button A long press handler for the chromatic tuner overlay.
#
# ── Behaviour ────────────────────────────────────────────────────────────────
#
#   push() (fires on long-press release):
#     If tuner is NOT active: send CC26=127 (TUNER_ON) and call
#       tuner_state.enter() → transitions to TUNER_PENDING.
#     If tuner IS active (second long-press = toggle off): send CC26=0
#       (TUNER_OFF) and call tuner_state.exit_to_normal() → transitions to
#       NORMAL_PENDING.
#
#   update_displays() (called every loop cycle):
#     ① Checks non-blocking timeouts via tuner_state.check_timeouts(),
#       passing _send_cc26_off as the zero-arg callable for auto-exit.
#     ② When tuner is active (any state except NORMAL): writes tuner data
#       from tuner_state to the center display labels.
#     ③ When not active: writes nothing (center display is owned by the
#       short-press lane_action for button A).
#
# ── Center display content ───────────────────────────────────────────────────
#
#   DISPLAY_LANE  → "TUNER"
#   DISPLAY_STATE → note + octave + cents, e.g. "E1  -7c"
#                   or "WAITING..." (TUNER_PENDING) / "NO DATA" (TUNER_NO_DATA)
#   DISPLAY_SEQ   → confidence indicator, e.g. "conf:104" or blank
#
# ── LED / label ownership ────────────────────────────────────────────────────
#
#   inputs.py wires this action with use_leds=False, display=None
#   (same as all other hold actions).  LED and corner label are owned by
#   the short-press ULTRA8_LANE_ACTION for button A.
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....colors import Colors
from adafruit_midi.midi_message import MIDIMessage

# Note names for display (prefer sharps)
_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _format_pitch(note, octave, cents_mag, cents_sign):
    """Return a short pitch string like 'E1  -7c' or 'A4  +0c'."""
    note_str  = _NOTE_NAMES[note % 12] if 0 <= note <= 11 else "?"
    sign_char = "-" if cents_sign == 0 else "+"
    return "{}{:<2}  {}{}c".format(note_str, octave, sign_char, cents_mag)


def _format_needle(cents_mag, cents_sign):
    """Return a 12-char cents needle like '[----<----]' or '[-----|--->]'.

    10-character inner field, center position 5.
    Flat  (cents_sign=0): marker '<' moves left of center.
    Sharp (cents_sign=1): marker '>' moves right of center.
    In tune (cents_mag=0): '|' sits at center.
    """
    if cents_mag == 0:
        marker = "|"
        pos    = 5
    elif cents_sign == 0:   # flat
        marker = "<"
        pos    = 5 - min(4, (cents_mag * 4 + 25) // 50)
    else:                   # sharp
        marker = ">"
        pos    = 5 + min(4, (cents_mag * 4 + 25) // 50)
    inner = "-" * pos + marker + "-" * (9 - pos)
    return "[" + inner + "]"


# ── Public factory ────────────────────────────────────────────────────────────

def ULTRA8_TUNER_ACTION(
    lane           = 0,         # Boot-default lane index (0-indexed)
    display        = None,      # DisplayLabel for corner (usually None for hold)
    use_leds       = False,     # False: LED owned by short-press lane_action
    id             = None,
    enable_callback = None,
):
    """Button A long press — chromatic tuner overlay.

    Sends CC26 value=127 (TUNER_ON) on press.  Drives the center display
    with live pitch data from tuner SysEx packets.  Handles the non-blocking
    30 s no-data timeout and manual toggle-off (second long-press).
    """
    return Action({
        "callback": _TunerActionCallback(lane=lane),
        "display":        display,
        "useSwitchLeds":  use_leds,
        "id":             id,
        "enableCallback": enable_callback,
    })


# ── Internal callback ─────────────────────────────────────────────────────────

class _TunerActionCallback(Callback):

    class _RawMessage(MIDIMessage):
        def __init__(self, data):
            self.__data = bytearray(data)
        def __bytes__(self):
            return self.__data

    def __init__(self, lane):
        super().__init__(mappings=[])
        self._lane_fallback = lane
        self._page_state    = None
        # Center-display label refs (set in init())
        self._lane_label    = None   # DISPLAY_LANE
        self._state_label   = None   # DISPLAY_STATE
        self._seq_label     = None   # DISPLAY_SEQ

        # ── Note hysteresis / lock-and-hold state ─────────────────────────────
        # Candidate tracking: gate note display until 2 consecutive matching frames.
        self._candidate_note  = None   # (note, octave) being evaluated
        self._candidate_count = 0      # consecutive same-note frames at conf >= 25

        # Locked note: what is actually shown on screen.
        self._locked_note   = None     # (note, octave) currently displayed
        self._lock_stable   = False    # True when locked via stable==1
        self._stable_lost   = 0        # frames since stable/conf last seen (for unlock)

        # Delta gate: avoid TFT writes when nothing changed.
        self._last_state_text  = None
        self._last_state_color = None
        self._last_seq_text    = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def init(self, appl, listener=None):
        self._appl = appl
        super().init(appl, listener)

        try:
            from pyswitch.clients.ultra8 import page_state
            self._page_state = page_state
        except ImportError:
            pass

        try:
            from display import DISPLAY_LANE, DISPLAY_STATE, DISPLAY_SEQ
            self._lane_label  = DISPLAY_LANE
            self._state_label = DISPLAY_STATE
            self._seq_label   = DISPLAY_SEQ
        except (ImportError, AttributeError):
            pass   # running without display (tests / emulator)

    # ── Button press ──────────────────────────────────────────────────────────

    def push(self):
        from pyswitch.clients.ultra8 import tuner_state

        if tuner_state.is_active():
            # Second long-press: toggle tuner off
            self._send_cc26_off()
        else:
            # First long-press: enter tuner mode
            lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback
            self._send_cc26(lane, 127)
            tuner_state.enter()

    def release(self):
        pass   # no release action for tuner

    # ── Periodic update ───────────────────────────────────────────────────────

    def update(self):
        super().update()
        self.update_displays()

    def update_displays(self):
        from pyswitch.clients.ultra8 import tuner_state

        # ① Non-blocking timeout check — may send CC26=0 and advance state
        tuner_state.check_timeouts(self._send_cc26_off)

        # ② Center display
        if tuner_state.is_active():
            self._update_tuner_display(tuner_state)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _send_cc26(self, lane_zero_indexed, value):
        """Send the TUN CC with `value` on the lane's MIDI channel.

        Uses the dynamically-assigned CC from the assignment store (control ID 6).
        Falls back to CC 26 before the first assignment message is received.
        """
        from pyswitch.clients.ultra8 import assignments
        cc = assignments.get_cc_for_control(6)   # 6 = TUNER control ID
        if cc is None:
            cc = 26   # default before first assignment message
        channel_byte = 0xB0 + (lane_zero_indexed & 0x0F)
        self._appl.client.midi.send(self._RawMessage([channel_byte, cc, value]))

    def _send_cc26_off(self):
        """Send CC26=0 (TUNER_OFF) and advance state machine to NORMAL_PENDING.

        Passed as a zero-arg callable to tuner_state.check_timeouts() so that
        the state module itself has no direct MIDI dependency.
        """
        from pyswitch.clients.ultra8 import tuner_state
        lane = (self._page_state.get() - 1) if self._page_state else self._lane_fallback
        self._send_cc26(lane, 0)
        tuner_state.exit_to_normal()

    def _set_state_label(self, text, color):
        """Write to state label only when value has changed (delta gate)."""
        if self._state_label and (text != self._last_state_text or
                                   color != self._last_state_color):
            self._state_label.text       = text
            self._state_label.text_color = color
            self._last_state_text        = text
            self._last_state_color       = color

    def _set_seq_label(self, text):
        """Write to seq label only when value has changed (delta gate)."""
        if self._seq_label and text != self._last_seq_text:
            self._seq_label.text = text
            self._last_seq_text  = text

    def _reset_tuner_display_state(self):
        """Clear all note-tracking state on tuner entry or non-active states."""
        self._candidate_note  = None
        self._candidate_count = 0
        self._locked_note     = None
        self._lock_stable     = False
        self._stable_lost     = 0

    def _update_tuner_display(self, tuner_state):
        """Write tuner overlay to center display labels.

        Note stability is enforced in two layers:
          1. Hysteresis: a note must appear for MIN_HOLD_COUNT consecutive frames
             at or above CONF_THRESHOLD before it is committed to the display.
          2. Lock-and-hold: once the JSFX stable flag fires (5 identical detections),
             the displayed note is frozen.  It stays frozen until UNLOCK_FRAMES of
             low-confidence or no-signal frames have elapsed.

        The DISPLAY_SEQ label shows a 12-char cents needle when a note is locked,
        or the incoming signal bar while listening (no note locked yet).

        All label writes are delta-gated — the TFT is only touched when the
        displayed value actually changes.
        """
        _SIGNAL_THRESHOLD = 8    # 0-127; below this → "No signal"
        _CONF_THRESHOLD   = 25   # min confidence to count a detection toward lock
        _MIN_HOLD_COUNT   = 2    # consecutive same-note frames before committing display
        _UNLOCK_FRAMES    = 3    # low-conf/no-signal frames required to break stable hold

        state = tuner_state.get_state()

        # ── Lane header ───────────────────────────────────────────────────────
        if self._lane_label and self._lane_label.text != "TUNER":
            self._lane_label.text = "TUNER"

        # ── Non-active states ─────────────────────────────────────────────────
        if state == tuner_state.TUNER_PENDING:
            self._reset_tuner_display_state()
            self._set_state_label("WAITING...", Colors.DARK_GRAY)
            self._set_seq_label("")
            return
        if state == tuner_state.TUNER_NO_DATA:
            self._reset_tuner_display_state()
            self._set_state_label("NO DATA", Colors.ORANGE)
            self._set_seq_label("")
            return
        if state == tuner_state.NORMAL_PENDING:
            self._set_state_label("EXITING...", Colors.DARK_GRAY)
            self._set_seq_label("")
            return

        # ── TUNER_ACTIVE ──────────────────────────────────────────────────────
        sig  = tuner_state.last_signal_level or 0
        conf = tuner_state.last_confidence   or 0
        stbl = tuner_state.last_stable       or 0

        if conf >= _CONF_THRESHOLD and tuner_state.last_note is not None:
            # Valid detection: update candidate streak
            new_key = (tuner_state.last_note, tuner_state.last_octave)
            if new_key == self._candidate_note:
                self._candidate_count += 1
            else:
                self._candidate_note  = new_key
                self._candidate_count = 1

            if stbl == 1:
                # JSFX stable flag: lock immediately, reset lost counter
                self._locked_note  = new_key
                self._lock_stable  = True
                self._stable_lost  = 0
            elif self._candidate_count >= _MIN_HOLD_COUNT and not self._lock_stable:
                # Hysteresis satisfied: commit the note without full stability
                self._locked_note  = new_key
            self._stable_lost = 0  # conf is good, reset unlock counter

        else:
            # Low confidence or no signal
            self._candidate_count = 0
            if self._lock_stable:
                # Grace period before breaking stable hold
                self._stable_lost += 1
                if self._stable_lost >= _UNLOCK_FRAMES:
                    self._lock_stable = False
                    self._locked_note = None
            elif sig < _SIGNAL_THRESHOLD:
                # No signal at all — clear uncommitted note
                self._locked_note = None

        # ── Render state label ────────────────────────────────────────────────
        if self._locked_note is not None:
            note, octave = self._locked_note
            pitch_text  = _format_pitch(
                note, octave,
                tuner_state.last_cents_mag  or 0,
                tuner_state.last_cents_sign or 1,
            )
            note_color = Colors.GREEN if self._lock_stable else Colors.WHITE
            self._set_state_label(pitch_text, note_color)
        elif sig >= _SIGNAL_THRESHOLD:
            self._set_state_label("Listening...", Colors.YELLOW)
        else:
            self._set_state_label("No signal", Colors.DARK_GRAY)

        # ── Render seq label: needle (locked) or signal bar (unlocked) ────────
        if self._locked_note is not None:
            needle = _format_needle(
                tuner_state.last_cents_mag  or 0,
                tuner_state.last_cents_sign or 1,
            )
            self._set_seq_label(needle)
        elif sig > 0:
            filled = max(0, min(10, sig * 10 // 127))
            self._set_seq_label("[{}{}]".format("#" * filled, "-" * (10 - filled)))
        else:
            self._set_seq_label("")
