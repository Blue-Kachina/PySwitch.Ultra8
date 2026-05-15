##############################################################################
#
# Ultra8 NANO4 — Display layout definition. (Milestone 5 redesign)
#
# 240 × 240 TFT layout:
#
#   y=  0 ┌─────────────────────────────────────┐
#          │  DISPLAY_HEADER_1 │ DISPLAY_HEADER_2 │  h=40  (back buttons: 1, 2)
#   y= 40 ├─────────────────────────────────────┤
#          │           Lane N                    │  small gray header  (h=28)
#          │─────────────────────────────────────│
#          │                                     │
#          │           PLY                       │  DISPLAY_STATE: big coloured
#          │                                     │  state name (h=65)
#          │─────────────────────────────────────│
#          │   ████████░░░░░░                    │  DISPLAY_PROGRESS: bar  (h=30)
#          │─────────────────────────────────────│
#          │   #42                               │  DISPLAY_SEQ: seq counter (h=28)
#   y=200 ├─────────────────────────────────────┤
#          │  DISPLAY_FOOTER_1 │ DISPLAY_FOOTER_2 │  h=40  (front buttons: A, B)
#   y=240 └─────────────────────────────────────┘
#
# Center area breakdown (y=40..200, 160px):
#   y= 50  h=28  Lane label (static)
#   y= 78  h=65  DISPLAY_STATE   — updated by lane_state.py (state name, big)
#   y=143  h=30  DISPLAY_PROGRESS — updated by lane_state.py (ASCII bar)
#   y=173  h=22  DISPLAY_SEQ     — updated by lane_state.py (seq counter)
#   Total used: 145px; 15px breathing room before footer.
#
# DISPLAY_HEADER_* and DISPLAY_FOOTER_* are exported so inputs.py can
# attach them to button actions.
#
# Font notes:
#   PTSans-NarrowBold-40.pcf — 40px, used for state name (DISPLAY_STATE).
#       Short labels (REC / PLY / OVDB / STP / ---) fit comfortably at 240px width.
#   H20.pcf — 20px, used for lane label, progress bar, seq counter.
#   Adjust bounds if any font renders taller than expected.
#
##############################################################################

from micropython import const
from pyswitch.colors import Colors, DEFAULT_LABEL_COLOR
from pyswitch.ui.ui import DisplayElement, DisplayBounds
from pyswitch.ui.elements import DisplayLabel
from pyswitch.clients.local.callbacks.splashes import SplashesCallback
from ultra8_config import DEFAULT_PAGE

# ── Dimensions ───────────────────────────────────────────────────────────────

_W  = const(240)    # Display width
_H  = const(240)    # Display height
_SW = const(120)    # Slot width (half display)
_SH = const(40)     # Slot height (header / footer rows)
_FY = const(200)    # Footer top-y
_CY = const(40)     # Center area top-y  (below header)
_CH = const(160)    # Center area height (above footer)

# ── Layout constants ──────────────────────────────────────────────────────────

_ACTION_LABEL_LAYOUT = {
    "font":      "/fonts/H20.pcf",
    "backColor": DEFAULT_LABEL_COLOR,
    "stroke":    1,
}

# ── Button slot labels (exported to inputs.py) ────────────────────────────────

DISPLAY_HEADER_1 = DisplayLabel(           # Switch 1, back-left
    layout = _ACTION_LABEL_LAYOUT,
    bounds = DisplayBounds(0,    0,   _SW, _SH),
)
DISPLAY_HEADER_2 = DisplayLabel(           # Switch 2, back-right
    layout = _ACTION_LABEL_LAYOUT,
    bounds = DisplayBounds(_SW,  0,   _SW, _SH),
)
DISPLAY_FOOTER_1 = DisplayLabel(           # Switch A, front-left
    layout = _ACTION_LABEL_LAYOUT,
    bounds = DisplayBounds(0,    _FY, _SW, _SH),
)
DISPLAY_FOOTER_2 = DisplayLabel(           # Switch B, front-right
    layout = _ACTION_LABEL_LAYOUT,
    bounds = DisplayBounds(_SW,  _FY, _SW, _SH),
)

# ── Center dynamic labels (exported for lane_state.py to update) ──────────────

# Primary state name — large, coloured text.
# Updated by lane_state.py to: "REC", "PLY", "OVDB", "STP", "---", "wait", "ERR"
DISPLAY_STATE = DisplayLabel(
    bounds = DisplayBounds(0, 78, _W, 65),
    layout = {
        "font":      "/fonts/PTSans-NarrowBold-40.pcf",
        "text":      "wait",
        "textColor": Colors.DARK_GRAY,
    },
)

# Loop progress bar — ASCII block characters.
# Updated by lane_state.py when PLAYING or OVERDUBBING; empty otherwise.
DISPLAY_PROGRESS = DisplayLabel(
    bounds = DisplayBounds(0, 143, _W, 30),
    layout = {
        "font":      "/fonts/H20.pcf",
        "text":      "",
        "textColor": Colors.DARK_GRAY,
    },
)

# Snapshot sequence counter — tiny, dark gray.
# Updated by lane_state.py to "#N" on each accepted snapshot; empty when stale.
DISPLAY_SEQ = DisplayLabel(
    bounds = DisplayBounds(0, 173, _W, 22),
    layout = {
        "font":      "/fonts/H20.pcf",
        "text":      "",
        "textColor": Colors.DARK_GRAY,
    },
)

# ── Lane label (exported so lane_state.py can update it on page change) ──────

# Text is initialised from DEFAULT_PAGE; lane_state.py overwrites it every
# update_displays() cycle with the current page_state value.
DISPLAY_LANE = DisplayLabel(
    bounds = DisplayBounds(0, 50, _W, 28),
    layout = {
        "font":      "/fonts/H20.pcf",
        "text":      "Lane " + str(DEFAULT_PAGE),
        "textColor": Colors.GRAY,
    },
)

# ── Splash screen ─────────────────────────────────────────────────────────────

Splashes = SplashesCallback(
    splashes = DisplayElement(
        bounds   = DisplayBounds(0, 0, _W, _H),
        children = [
            # Button corner labels
            DISPLAY_HEADER_1,
            DISPLAY_HEADER_2,
            DISPLAY_FOOTER_1,
            DISPLAY_FOOTER_2,

            # Lane number — updated at runtime by lane_state.py when page changes.
            DISPLAY_LANE,

            # Primary state — updated live by lane_state.py
            DISPLAY_STATE,

            # Loop progress bar — updated live by lane_state.py
            DISPLAY_PROGRESS,

            # Snapshot sequence counter — updated live by lane_state.py
            DISPLAY_SEQ,
        ],
    )
)
