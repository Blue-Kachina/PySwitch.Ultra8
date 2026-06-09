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

    def _update_tuner_display(self, tuner_state):
        """Write tuner overlay to center display labels.

        Signal level and confidence drive the main state text:
          confidence > 0          → show note + cents (pitch detected)
          signal_level >= 8, conf=0  → "Listening..."  (signal present, no pitch yet)
          signal_level < 8           → "No signal"     (nothing detected)
        The threshold of 8/127 (~0.03 FS) is a low but meaningful floor —
        background noise in a quiet studio typically stays below this.
        """
        _SIGNAL_THRESHOLD = 8   # 0-127; below this → "No signal"

        state = tuner_state.get_state()

        if self._lane_label:
            self._lane_label.text = "TUNER"

        if self._state_label:
            if state == tuner_state.TUNER_ACTIVE:
                sig   = tuner_state.last_signal_level or 0
                conf  = tuner_state.last_confidence   or 0
                if conf > 0 and tuner_state.last_note is not None:
                    # Pitch detected — show note and cents
                    self._state_label.text = _format_pitch(
                        tuner_state.last_note,
                        tuner_state.last_octave,
                        tuner_state.last_cents_mag,
                        tuner_state.last_cents_sign,
                    )
                    self._state_label.text_color = Colors.GREEN if tuner_state.last_stable else Colors.WHITE
                elif sig >= _SIGNAL_THRESHOLD:
                    # Signal present but no pitch — Phase 3 / waiting for Phase 4
                    self._state_label.text       = "Listening..."
                    self._state_label.text_color = Colors.YELLOW
                else:
                    # No meaningful signal
                    self._state_label.text       = "No signal"
                    self._state_label.text_color = Colors.DARK_GRAY
            elif state == tuner_state.TUNER_PENDING:
                self._state_label.text       = "WAITING..."
                self._state_label.text_color = Colors.DARK_GRAY
            elif state == tuner_state.TUNER_NO_DATA:
                self._state_label.text       = "NO DATA"
                self._state_label.text_color = Colors.ORANGE
            elif state == tuner_state.NORMAL_PENDING:
                self._state_label.text       = "EXITING..."
                self._state_label.text_color = Colors.DARK_GRAY

        if self._seq_label:
            if state == tuner_state.TUNER_ACTIVE:
                sig  = tuner_state.last_signal_level or 0
                conf = tuner_state.last_confidence   or 0
                # Show signal bar in Phase 3; switch to conf display once Phase 4 adds pitch
                if conf > 0:
                    self._seq_label.text = "conf:{}".format(conf)
                elif sig > 0:
                    # Simple ASCII level bar: 10 chars wide
                    filled = max(0, min(10, sig * 10 // 127))
                    self._seq_label.text = "[{}{}]".format("#" * filled, "-" * (10 - filled))
                else:
                    self._seq_label.text = ""
            else:
                self._seq_label.text = ""
