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
#   Switch A  short  → CC 20  REC/PLY      (record/play/overdub)
#   Switch A  long   → CC 21  CLR          (clear lane)
#   Switch 1  short  → CC 22  PLY/STP      (play/stop toggle)
#   Switch 1  long   → CC 23  MON          (toggle monitor/speaker)
#   Switch 2  short  → CC 25  STOP-LANE    (stop this lane)
#   Switch B  short  → CC 24  UNDO         (undo last record)
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
    # Short: PLY/STP (CC22)   Long: MON (CC23)
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_1,
        "actions": [
            CUSTOM_MESSAGE(
                message        = _cc(22),
                text           = "PLY/STP",
                color          = Colors.LIGHT_GREEN,
                led_brightness = 0.3,
                display        = DISPLAY_HEADER_1,
            ),
        ],
        "actionsHold": [
            CUSTOM_MESSAGE(
                message        = _cc(23),
                text           = "MON",
                color          = Colors.BLUE,
                led_brightness = 0.3,
                display        = DISPLAY_HEADER_1,
                use_leds       = False,   # hold action does not own LED pixels;
                                          # all 3 NeoPixels on Switch 1 belong to
                                          # the PLY/STP short-press action.
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
                lane    = DEFAULT_PAGE - 1,  # 0-indexed (device A = lane 0)
                message = _cc(20),
                text    = "REC/PLY",
                display = DISPLAY_FOOTER_1,
            ),
        ],
        "actionsHold": [
            CUSTOM_MESSAGE(
                message        = _cc(21),
                text           = "CLR",
                color          = Colors.PURPLE,
                led_brightness = 0.3,
                display        = DISPLAY_FOOTER_1,
                use_leds       = False,   # CLR hold does not own any LED pixels;
                                          # all 3 NeoPixels on Switch A belong to
                                          # ULTRA8_LANE_STATE (feedback-driven).
            ),
        ],
    },

    # ── Switch B (front-right) ───────────────────────────────────────────────
    # Short: UNDO (CC24)   Long: reserved
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_B,
        "actions": [
            CUSTOM_MESSAGE(
                message        = _cc(24),
                text           = "UNDO",
                color          = Colors.YELLOW,
                led_brightness = 0.3,
                display        = DISPLAY_FOOTER_2,
            ),
        ],
    },

]
