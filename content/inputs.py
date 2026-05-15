##############################################################################
#
# Ultra8 NANO4 — Button input definitions.
#
# Maps the four NANO4 footswitches to Ultra8 CC commands.
# MIDI channel is derived from ultra8_config.DEFAULT_PAGE so this file
# is identical across all physical devices.
#
# Button layout (top view of NANO4):
#
#   [ 1 - back-left  ]  [ 2 - back-right ]
#   [ A - front-left ]  [ B - front-right]
#
# CC assignments (ground truth: nano4config/page0.txt):
#
#   Switch A  short  → CC 20  REC          (record/play/overdub)
#   Switch A  long   → CC 21  CLR          (clear lane)
#   Switch 1  short  → CC 22              (label driven by Ultra8 assignment)
#   Switch 1  long   → CC 23  MON          (toggle monitor/speaker)
#   Switch 2  short  → CC 25  STOP-LANE    (stop this lane)
#   Switch B  short  → CC 24              (label driven by Ultra8 assignment)
#
# B long and 2 long are reserved (not assigned) in this release.
#
# Press behaviour: messages fire on SHORT RELEASE (not on physical
# press-down). When a button has both `actions` and `actionsHold`,
# PySwitch delays firing `actions` until it confirms the press was
# short, so the correct CC fires even for adjacent short/long gestures.
# Value 127 is sent on activation; no release (value 0) message is sent,
# matching the stock nano4config behaviour.
#
##############################################################################

from pyswitch.hardware.devices.pa_midicaptain_nano_4 import *
from pyswitch.clients.local.actions.custom import CUSTOM_MESSAGE
from pyswitch.clients.ultra8.actions.lane_state import ULTRA8_LANE_STATE
from pyswitch.clients.ultra8.actions.labeled_button import ULTRA8_LABELED_BUTTON
from pyswitch.colors import Colors
from display import DISPLAY_HEADER_1, DISPLAY_HEADER_2, DISPLAY_FOOTER_1, DISPLAY_FOOTER_2
from ultra8_config import DEFAULT_PAGE

# ── MIDI helpers ─────────────────────────────────────────────────────────────

# Control Change status byte for the configured lane channel (0xB0 = ch1).
_CC_STATUS = 0xB0 + (DEFAULT_PAGE - 1)

def _cc(number):
    """Return raw CC bytes [status, cc_number, 127] for the device's lane channel."""
    return [_CC_STATUS, number, 127]


# ── Inputs ───────────────────────────────────────────────────────────────────

Inputs = [

    # ── Switch 1 (back-left) ─────────────────────────────────────────────────
    # Short: CC22   Long: MON (CC23)
    # Corner label owned by the short-press action only; hold gets display=None
    # so it never overwrites the short-press label between presses.
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_1,
        "actions": [
            ULTRA8_LABELED_BUTTON(
                control_id     = 4,          # UNDO — label tracks Ultra8 assignment for CC22
                message        = _cc(22),
                color          = Colors.YELLOW,
                led_brightness = 0.3,
                display        = DISPLAY_HEADER_1,
            ),
        ],
        "actionsHold": [
            ULTRA8_LABELED_BUTTON(
                control_id     = 3,          # MON
                message        = _cc(23),
                color          = Colors.BLUE,
                led_brightness = 0.3,
                display        = None,        # hold does not own the corner label
                use_leds       = False,       # all 3 NeoPixels belong to short action
            ),
        ],
    },

    # ── Switch 2 (back-right) ────────────────────────────────────────────────
    # Short: STOP-LANE (CC25)   Long: reserved
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_2,
        "actions": [
            CUSTOM_MESSAGE(
                message        = _cc(25),
                text           = "STOP",
                color          = Colors.ORANGE,
                led_brightness = 0.3,
                display        = DISPLAY_HEADER_2,
            ),
        ],
    },

    # ── Switch A (front-left) ────────────────────────────────────────────────
    # Short: REC/PLY (CC20) — LED driven by Ultra8 feedback, not local state.
    # Long:  CLR (CC21)
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_A,
        "actions": [
            ULTRA8_LANE_STATE(
                lane       = DEFAULT_PAGE - 1,  # 0-indexed (device A = lane 0)
                message    = _cc(20),
                control_id = 0,                 # REC_PLY — drives corner label
                text       = "REC/PLY",         # static fallback before assignment arrives
                display    = DISPLAY_FOOTER_1,
            ),
        ],
        "actionsHold": [
            ULTRA8_LABELED_BUTTON(
                control_id     = 2,          # CLR
                message        = _cc(21),
                color          = Colors.PURPLE,
                led_brightness = 0.3,
                display        = None,        # hold does not own the corner label
                use_leds       = False,       # all 3 NeoPixels belong to ULTRA8_LANE_STATE
            ),
        ],
    },

    # ── Switch B (front-right) ───────────────────────────────────────────────
    # Short: CC24   Long: reserved
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_B,
        "actions": [
            ULTRA8_LABELED_BUTTON(
                control_id     = 1,          # PLAY — label tracks Ultra8 assignment for CC24
                message        = _cc(24),
                color          = Colors.LIGHT_GREEN,
                led_brightness = 0.3,
                display        = DISPLAY_FOOTER_2,
            ),
        ],
    },

]
