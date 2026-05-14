##############################################################################
#
# Ultra8 NANO4 — Display layout definition.
#
# 240 × 240 TFT layout:
#
#   y=  0 ┌──────────────────────────────────┐
#          │  DISPLAY_HEADER_1  │ DISPLAY_HEADER_2  │  h=40  (back buttons: 1, 2)
#   y= 40 ├──────────────────────────────────┤
#          │                                  │
#          │          ULTRA8                  │  large title
#          │                                  │
#          │         Lane N                   │  lane number from config
#          │                                  │
#          │     Waiting for snapshot…        │  static until Milestone 3 adds
#          │                                  │  live snapshot callbacks
#          │                                  │
#   y=200 ├──────────────────────────────────┤
#          │  DISPLAY_FOOTER_1  │ DISPLAY_FOOTER_2  │  h=40  (front buttons: A, B)
#   y=240 └──────────────────────────────────┘
#
# DISPLAY_HEADER_* and DISPLAY_FOOTER_* are exported so inputs.py can
# attach them to button actions. The center area is static for this
# milestone; it will become dynamic in Milestone 3 (snapshot parsing)
# and Milestone 5 (full lane-status UI).
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

# Status label — exported so Ultra8Protocol can update it on incoming MIDI.
# Initial text: waiting state. Protocol changes this to "RX OK" on first receive.
DISPLAY_STATUS = DisplayLabel(
    bounds = DisplayBounds(0, 165, _W, 30),
    layout = {
        "font":      "/fonts/H20.pcf",
        "text":      "Waiting for snapshot...",
        "textColor": Colors.DARK_GRAY,
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

            # "ULTRA8" — large title in the centre
            DisplayLabel(
                bounds = DisplayBounds(0, 55, _W, 70),
                layout = {
                    "font":      "/fonts/PTSans-NarrowBold-40.pcf",
                    "text":      "ULTRA8",
                    "textColor": Colors.WHITE,
                },
            ),

            # Lane number — derived from per-device config
            DisplayLabel(
                bounds = DisplayBounds(0, 130, _W, 35),
                layout = {
                    "font":      "/fonts/H20.pcf",
                    "text":      "Lane " + str(DEFAULT_PAGE),
                    "textColor": Colors.GRAY,
                },
            ),

            # Status line — updated live by Ultra8Protocol when MIDI is received.
            # Exported as DISPLAY_STATUS so protocol.py can late-import it.
            DISPLAY_STATUS,
        ],
    )
)
