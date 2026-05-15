##############################################################################
#
# Ultra8 PySwitch — ULTRA8_LABELED_BUTTON action (Unit 6.5)
#
# Drop-in replacement for CUSTOM_MESSAGE on buttons whose corner label should
# reflect the current Ultra8 MIDI assignment rather than a hardcoded string.
#
# Differences from CUSTOM_MESSAGE:
#   - Takes `control_id` (int, 0–4) instead of `text`.
#   - update_displays() reads assignments.get_label(control_id) every frame,
#     so the corner label updates automatically after an assignment message
#     is received from Ultra8 without requiring a firmware restart.
#   - Fallback: if assignments module is unavailable (e.g. emulator), the
#     static _NAMES in assignments.py already return the function name so
#     the label is always readable.
#
# Control ID → default label (before any assignment message arrives):
#   0 → "REC/PLY"   1 → "PLY/STP"   2 → "CLR"
#   3 → "MON"       4 → "UNDO"
#
# Usage in inputs.py:
#   from pyswitch.clients.ultra8.actions.labeled_button import ULTRA8_LABELED_BUTTON
#
#   ULTRA8_LABELED_BUTTON(
#       control_id     = 1,          # PLY/STP
#       message        = _cc(22),
#       color          = Colors.LIGHT_GREEN,
#       led_brightness = 0.3,
#       display        = DISPLAY_HEADER_1,
#   )
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action
from ....colors import Colors
from adafruit_midi.midi_message import MIDIMessage


def ULTRA8_LABELED_BUTTON(
    control_id,              # Assignment control ID (0 = REC_PLY, 1 = PLY_STP, …)
    message,                 # Raw MIDI bytes sent on button press
    message_release = None,  # Raw MIDI bytes sent on release (default: None)
    color = Colors.WHITE,    # LED + corner-label back-colour
    led_brightness = 0.15,   # LED brightness [0..1]
    display = None,          # DisplayLabel for the corner label
    use_leds = True,
    id = None,
    enable_callback = None,
):
    """Send a fixed CC on press; show a dynamic assignment label on screen."""
    return Action({
        "callback": _LabeledButtonCallback(
            control_id      = control_id,
            message         = message,
            message_release = message_release,
            color           = color,
            led_brightness  = led_brightness,
        ),
        "display":        display,
        "useSwitchLeds":  use_leds,
        "id":             id,
        "enableCallback": enable_callback,
    })


class _LabeledButtonCallback(Callback):

    class _RawMessage(MIDIMessage):
        def __init__(self, data):
            self.__data = bytearray(data)
        def __bytes__(self):
            return self.__data

    def __init__(self, control_id, message, message_release, color, led_brightness):
        super().__init__()
        self.__control_id      = control_id
        self.__message         = message
        self.__message_release = message_release
        self.__color           = color
        self.__led_brightness  = led_brightness

        # assignments module — loaded once in init() to avoid repeated imports.
        self.__assignments = None

    def init(self, appl, listener = None):
        self.__appl = appl

        # Late-import the shared assignment store.
        try:
            from pyswitch.clients.ultra8 import assignments
            self.__assignments = assignments
        except ImportError:
            pass   # running without the Ultra8 client (tests, emulator)

    def push(self):
        msg = self.__message() if callable(self.__message) else self.__message
        self.__appl.client.midi.send(self._RawMessage(msg))

    def release(self):
        if self.__message_release:
            msg = self.__message_release() if callable(self.__message_release) else self.__message_release
            self.__appl.client.midi.send(self._RawMessage(msg))

    def update_displays(self):
        self.action.switch_color      = self.__color
        self.action.switch_brightness = self.__led_brightness

        if self.action.label:
            # Dynamic: read the current label from the assignment store.
            # Falls back to the static function name if no message received yet.
            if self.__assignments is not None:
                label_text = self.__assignments.get_label(self.__control_id)
            else:
                label_text = "???"
            self.action.label.text       = label_text
            self.action.label.back_color = self.__color
