##############################################################################
#
# Ultra8 NANO4 — Button input definitions.
#
# Maps the four NANO4 footswitches to Ultra8 CC commands.
#
# MIDI channel is derived at press time from page_state.get(), so changing
# the page with a long-press immediately affects the next button action.
# This file is identical across all physical devices.
#
# Button layout (top view of NANO4):
#
#   [ 1 - back-left  ]  [ 2 - back-right ]
#   [ A - front-left ]  [ B - front-right]
#
# The active lane is read at boot from:
#   nano4_button_maps/default_lane.txt  (single integer, 1–8)
# CC assignments are loaded at startup from:
#   nano4_button_maps/lane_<DEFAULT_PAGE>.json
#
# If the JSON file is unavailable, the fallback CC numbers below apply:
#   Switch A  short  → CC 20  (REC/PLY)
#   Switch A  long   → CC 21  (CLR)
#   Switch 1  short  → CC 22  (UNDO/REDO)
#   Switch 1  long   → CC 23  (CLR)
#   Switch 2  short  → CC 25  (REV)
#   Switch 2  long   →        PAGE UP      (next_lane)
#   Switch B  short  → CC 24  (PLY/STP)
#   Switch B  long   →        PAGE DOWN    (prev_lane)
#
# LED behavior:
#   All four buttons are function-bound — their LED color and corner label
#   are driven by leds.json based on the Ultra8 function key in the lane JSON
#   and the live lane state from SysEx snapshots.
#   The "function" key binds the LED function at init() time, so buttons
#   show their default state immediately on boot without waiting for SysEx.
#
# Press behaviour: messages fire on SHORT RELEASE.  When a button has both
# `actions` and `actionsHold`, PySwitch delays firing `actions` until the
# press is confirmed short.  Value 127 sent on activation; no release CC.
#
##############################################################################

from pyswitch.hardware.devices.pa_midicaptain_nano_4 import *
from pyswitch.clients.local.actions.custom import CUSTOM_MESSAGE
from pyswitch.clients.ultra8.actions.lane_action import ULTRA8_LANE_ACTION
from pyswitch.clients.ultra8.actions.page_nav import ULTRA8_PAGE_NAV
from pyswitch.clients.ultra8 import page_state as _page_state
from pyswitch.colors import Colors
from pyswitch.clients.ultra8.lane_config import load_lane_config, load_default_lane, get_gesture
from display import DISPLAY_HEADER_1, DISPLAY_HEADER_2, DISPLAY_FOOTER_1, DISPLAY_FOOTER_2

# Lane number (1-indexed) read from nano4_button_maps/default_lane.txt at boot.
# Falls back to the lowest-numbered lane_<n>.json, then to lane 1.
DEFAULT_PAGE = load_default_lane()


# ── MIDI helper ───────────────────────────────────────────────────────────────

def _cc(number):
    """Return a callable that produces CC bytes on the *current* lane channel.

    Evaluated at press time (not at import time), so page navigation takes
    effect immediately on the next button press.
    """
    def _make():
        return [0xB0 + (_page_state.get() - 1), number, 127]
    return _make


# ── Load lane JSON config ─────────────────────────────────────────────────────
#
# Reads nano4_button_maps/lane_<DEFAULT_PAGE>.json.  On error (file missing,
# bad JSON) load_lane_config() logs to serial and returns None — all helpers
# below then return safe fallback values so the device boots with functional
# defaults even if the JSON file is unavailable.

_config = load_lane_config(DEFAULT_PAGE)


def _cc_index(button, gesture, fallback):
    """Return the CC index (int) for a button gesture from the loaded config.
    Falls back to `fallback` if config is None or the field is absent.
    """
    g = get_gesture(_config, button, gesture)
    v = g.get("index")
    return v if isinstance(v, int) else fallback


def _btn_label(button):
    """Return the tier-2 label from the JSON button object (may be None)."""
    g = get_gesture(_config, button, "short")
    return g.get("label", None)


def _btn_function(button):
    """Return the leds.json function name for a button, or None if absent."""
    g = get_gesture(_config, button, "short")
    return g.get("function", None)


# ── Resolved CC numbers ───────────────────────────────────────────────────────
# Default values match the pre-Phase-4 hardcoded assignments.

_CC_A_SHORT = _cc_index("A", "short", 20)   # REC/PLY
_CC_A_LONG  = _cc_index("A", "long",  21)   # CLR
_CC_1_SHORT = _cc_index("1", "short", 22)   # UNDO/REDO
_CC_1_LONG  = _cc_index("1", "long",  23)   # CLR
_CC_2_SHORT = _cc_index("2", "short", 25)   # REV
_CC_B_SHORT = _cc_index("B", "short", 24)   # PLY/STP

# PAGE NAV direction from JSON internal index ("next_lane" / "prev_lane")
# Falls back to +1 / -1 if JSON is unavailable.
def _nav_direction(button, gesture, default_direction):
    g = get_gesture(_config, button, gesture)
    idx = g.get("index")
    if idx == "next_lane":
        return +1
    if idx == "prev_lane":
        return -1
    return default_direction

_DIR_2_LONG = _nav_direction("2", "long", +1)   # Switch 2 long: PAGE UP
_DIR_B_LONG = _nav_direction("B", "long", -1)   # Switch B long: PAGE DOWN


# ── Inputs ────────────────────────────────────────────────────────────────────

Inputs = [

    # ── Switch 1 (back-left) ─────────────────────────────────────────────────
    # Short: UNDO_REDO (CC22) — function-bound LED + state-driven label.
    # Long:  CLR (CC23) — function-bound; fires optimistic lane clear + broadcast.
    # LED reflects undo_redo_state from SysEx snapshot (available / redo_available / unavailable).
    # Corner label is state-driven: "UNDO" normally, "REDO" when redo stack is ready.
    # Hold does not own LEDs or corner label.
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_1,
        "actions": [
            ULTRA8_LANE_ACTION(
                message        = _cc(_CC_1_SHORT),
                cc_number      = _CC_1_SHORT,
                label          = _btn_label("1"),       # tier-2: "UN/REDO" from JSON
                function       = _btn_function("1"),    # "UNDO_REDO" — binds LED at init()
                drives_display = False,                 # center display owned by Switch A
                lane           = DEFAULT_PAGE - 1,
                display        = DISPLAY_HEADER_1,
            ),
        ],
        "actionsHold": [
            ULTRA8_LANE_ACTION(
                message        = _cc(_CC_1_LONG),
                cc_number      = _CC_1_LONG,
                function       = "CLR",           # publishes optimistic clear + broadcast on press
                drives_display = False,
                lane           = DEFAULT_PAGE - 1,
                display        = None,    # hold does not own corner label
                use_leds       = False,   # LEDs belong to the short-press action
            ),
        ],
    },

    # ── Switch 2 (back-right) ────────────────────────────────────────────────
    # Short: REV (CC25) — function-bound LED + tier-3 label from leds.json.
    # Long:  PAGE UP
    # LED reflects rev_active from SysEx snapshot (lit orange when reversed).
    # Hold does not own LEDs or corner label.
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_2,
        "actions": [
            ULTRA8_LANE_ACTION(
                message        = _cc(_CC_2_SHORT),
                cc_number      = _CC_2_SHORT,
                label          = _btn_label("2"),       # tier-2: "REV" from JSON
                function       = _btn_function("2"),    # "REV" — binds LED at init()
                drives_display = False,
                lane           = DEFAULT_PAGE - 1,
                display        = DISPLAY_HEADER_2,
            ),
        ],
        "actionsHold": [
            ULTRA8_PAGE_NAV(
                direction      = _DIR_2_LONG,
                display        = None,    # hold does not own corner label
                use_leds       = False,   # LEDs belong to ULTRA8_LANE_ACTION
            ),
        ],
    },

    # ── Switch A (front-left) ────────────────────────────────────────────────
    # Short: REC/PLY (CC20) — function-bound LED + tier-3 label + center display.
    # Long:  CC21 — unassigned in Ultra8; CUSTOM_MESSAGE placeholder.
    # Hold does not own LEDs or corner label.
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_A,
        "actions": [
            ULTRA8_LANE_ACTION(
                message        = _cc(_CC_A_SHORT),
                cc_number      = _CC_A_SHORT,
                label          = _btn_label("A"),       # tier-2: "REC/PLY" from JSON
                function       = _btn_function("A"),    # "REC_PLY" — binds LED at init()
                drives_display = True,                  # owns center DISPLAY_* labels
                lane           = DEFAULT_PAGE - 1,
                display        = DISPLAY_FOOTER_1,
            ),
        ],
        "actionsHold": [
            CUSTOM_MESSAGE(
                message        = _cc(_CC_A_LONG),
                text           = "CC{}".format(_CC_A_LONG),
                color          = Colors.BLUE,
                led_brightness = 0.3,
                display        = None,    # hold does not own corner label
                use_leds       = False,   # LEDs belong to the short-press action
            ),
        ],
    },

    # ── Switch B (front-right) ───────────────────────────────────────────────
    # Short: PLY/STP (CC24) — function-bound LED + tier-3 label.
    # Long:  PAGE DOWN
    # Hold does not own LEDs or corner label.
    {
        "assignment": PA_MIDICAPTAIN_NANO_SWITCH_B,
        "actions": [
            ULTRA8_LANE_ACTION(
                message        = _cc(_CC_B_SHORT),
                cc_number      = _CC_B_SHORT,
                label          = _btn_label("B"),       # tier-2: None (no label in JSON)
                function       = _btn_function("B"),    # "PLY_STP" — binds LED at init()
                drives_display = False,                 # center display owned by Switch A
                lane           = DEFAULT_PAGE - 1,
                display        = DISPLAY_FOOTER_2,
            ),
        ],
        "actionsHold": [
            ULTRA8_PAGE_NAV(
                direction      = _DIR_B_LONG,
                display        = None,    # hold does not own corner label
                use_leds       = False,   # LEDs belong to ULTRA8_LANE_ACTION
            ),
        ],
    },

]
