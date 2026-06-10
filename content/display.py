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
#   y= 78  h=65  DISPLAY_STATE   — updated by lane_action.py (state name, big)
#   y=143  h=30  DISPLAY_PROGRESS — updated by lane_action.py (ASCII bar)
#   y=173  h=22  DISPLAY_SEQ     — updated by lane_action.py (seq counter)
#   Total used: 145px; 15px breathing room before footer.
#
# DISPLAY_HEADER_* and DISPLAY_FOOTER_* are exported so inputs.py can
# attach them to button actions.
#
# Font notes:
#   PTSans-NarrowBold-40.pcf — 40px, used for state name (DISPLAY_STATE).
#       Labels: PLAYING / RECORDING / STOPPED / EMPTY fit comfortably at 240px width.
#       OVERDUBBING (11 chars) is the widest — verify on hardware; use OVERDUB if it clips.
#   H20.pcf — 20px, used for lane label, progress bar, seq counter.
#   Adjust bounds if any font renders taller than expected.
#
##############################################################################

import displayio
from micropython import const
from pyswitch.colors import Colors, DEFAULT_LABEL_COLOR
from pyswitch.ui.ui import DisplayElement, DisplayBounds
from pyswitch.ui.elements import DisplayLabel
from pyswitch.clients.local.callbacks.splashes import SplashesCallback
from pyswitch.clients.ultra8.lane_config import load_default_lane as _load_default_lane
from pyswitch.clients.ultra8.tuner_display import TunerAnimDisplay


class _GroupElement(DisplayElement):
    """Thin DisplayElement wrapper for a raw displayio.Group (or subclass).

    adafruit_display_shapes objects (Rect, Circle, etc.) subclass displayio.Group
    but do not implement the PySwitch init(ui, appl) / initialized() lifecycle.
    This wrapper appends the group to ui.splash during init() so the framework
    can iterate the Splashes children list safely.
    """

    def __init__(self, group):
        super().__init__()
        self._group = group

    def init(self, ui, appl):
        ui.splash.append(self._group)
        super().init(ui, appl)


class _TileGridElement(DisplayElement):
    """Thin DisplayElement wrapper for a raw displayio.TileGrid.

    The PySwitch framework calls child.initialized() and child.init(ui, appl)
    on every entry in the Splashes children list.  Raw TileGrid objects do not
    have these methods, so they must be wrapped.  This class appends the
    TileGrid to ui.splash (the displayio Group) during init(), which is exactly
    what DisplayLabel does with its own backing Group.
    """

    def __init__(self, tile_grid):
        super().__init__()
        self._tile_grid = tile_grid

    def init(self, ui, appl):
        # Wrap TileGrid in a Group, matching how DisplayLabel adds its content.
        # Adding a TileGrid directly to the root splash Group prevents runtime
        # bitmap/palette updates from propagating to the display.
        wrapper = displayio.Group()
        wrapper.append(self._tile_grid)
        ui.splash.append(wrapper)
        super().init(ui, appl)
DEFAULT_PAGE = _load_default_lane()   # initial lane for DISPLAY_LANE text

# ── Tuner animation shapes ─────────────────────────────────────────────────────
#
# TunerAnimDisplay owns the line/ring/ball shapes for the graphical tuner
# overlay.  Shapes start hidden; tuner_action.py calls show()/hide()/update().
#
TUNER_ANIM = TunerAnimDisplay()

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

# ── Center dynamic labels (exported for lane_action.py to update) ──────────────

# Primary state name — large, coloured text.
# Updated by lane_action.py to: "PLAYING", "RECORDING", "OVERDUBBING", "STOPPED", "EMPTY", "WAITING", "ERROR"
# Note: "OVERDUBBING" is the widest string at 40px narrow bold — verify on hardware; fallback is "OVERDUB".
DISPLAY_STATE = DisplayLabel(
    bounds = DisplayBounds(0, 78, _W, 65),
    layout = {
        "font":      "/fonts/PTSans-NarrowBold-40.pcf",
        "text":      "WAITING",
        "textColor": Colors.DARK_GRAY,
    },
)

# ── Waveform canvas (Unit B.1b) ───────────────────────────────────────────────
#
# Replaces the old ASCII DISPLAY_PROGRESS label.
# A raw displayio.Bitmap at y=143 (30px tall, full 240px wide) drawn by
# waveform.py each animation frame via WAVEFORM_BITMAP pixel writes.
#
# Palette indices:
#   0 — background (black)
#   1 — PLAYING color  (green)
#   2 — OVERDUBBING color (red/amber)
#   3 — reserved / dim (dark gray, future use)
#
_WAVE_W = const(240)
_WAVE_H = const(30)
_WAVE_Y = const(143)    # matches old DISPLAY_PROGRESS y

WAVEFORM_PALETTE    = displayio.Palette(4)
WAVEFORM_PALETTE[0] = 0x000000   # background
WAVEFORM_PALETTE[1] = 0x00BB44   # playing  (green)
WAVEFORM_PALETTE[2] = 0xCC3300   # overdubbing (red)
WAVEFORM_PALETTE[3] = 0x333333   # dim / reserved

WAVEFORM_BITMAP    = displayio.Bitmap(_WAVE_W, _WAVE_H, 4)
WAVEFORM_TILE      = displayio.TileGrid(
    WAVEFORM_BITMAP,
    pixel_shader = WAVEFORM_PALETTE,
    x = 0,
    y = _WAVE_Y,
)
WAVEFORM_ELEMENT   = _TileGridElement(WAVEFORM_TILE)

# Snapshot sequence counter — tiny, dark gray.
# Updated by lane_action.py to "#N" on each accepted snapshot; empty when stale.
DISPLAY_SEQ = DisplayLabel(
    bounds = DisplayBounds(0, 173, _W, 22),
    layout = {
        "font":      "/fonts/H20.pcf",
        "text":      "",
        "textColor": Colors.DARK_GRAY,
    },
)

# ── Lane label (exported so lane_action.py can update it on page change) ──────

# Text is initialised from DEFAULT_PAGE; lane_action.py overwrites it every
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

            # Lane number — updated at runtime by lane_action.py when page changes.
            DISPLAY_LANE,

            # Primary state — updated live by lane_action.py
            DISPLAY_STATE,

            # Waveform canvas — drawn live by lane_action.py via waveform.py
            WAVEFORM_ELEMENT,

            # Snapshot sequence counter — updated live by lane_action.py
            DISPLAY_SEQ,

            # Tuner animation elements — hidden by default; shown by tuner_action.py
            # when TUNER_ACTIVE with a locked note.  Rendered on top of text labels
            # because they are last in the children list.
            # Shapes are raw displayio.Group subclasses — wrapped in _GroupElement.
            # note_label is a DisplayLabel (DisplayElement) — added directly.
            _GroupElement(TUNER_ANIM.shapes[0]),   # line        (Rect)
            _GroupElement(TUNER_ANIM.shapes[1]),   # ring        (Circle, fixed)
            _GroupElement(TUNER_ANIM.shapes[2]),   # ball_white  (Circle, out of tune)
            _GroupElement(TUNER_ANIM.shapes[3]),   # ball_green  (Circle, in tune)
            TUNER_ANIM.note_label,                 # note name   (PTSans-NarrowBold-40)
        ],
    )
)
