##############################################################################
#
# Ultra8 NANO4 -- Progress Bar Display
#
# A thin horizontal bar at the bottom of the center display area that shows
# how far through the current loop the playback position is.
#
# The bar is visible only during PLAYING and OVERDUBBING states.  It is
# hidden during RECORDING (no loop length yet), STOPPED, EMPTY, and while
# the tuner overlay is active.
#
# Bar color matches the state text color:
#   PLAYING      -- LIGHT_GREEN
#   OVERDUBBING  -- RED
#
# -- Layout (y coords, 240x240 display) ----------------------------------------
#
#   y=192  >>>>>>>>>>>>>>>>::::::::   progress bar (8px tall, full 240px wide)
#   y=200  ─────────────────────────  footer top edge
#
# -- Drawing technique ---------------------------------------------------------
#
# Two colored background Rects (green, red) sit at y=192, w=240.
# A black mask Rect (same size) sits on top.  Moving mask.x rightward
# reveals more of the colored bar from the left.
#
#   mask.x = phase * 240 // 127
#
# When mask.x=0:   mask covers all (nothing visible).
# When mask.x=240: mask is off-screen (full bar visible).
#
# The .x assignment on adafruit_display_shapes Rect objects (Group subclasses)
# propagates correctly in this firmware build (confirmed via tuner ball motion).
# .fill does not propagate at runtime; separate pre-built Rects are used for
# each color so only .hidden toggling is needed for color switching.
#
# -- Z-order in display.py -----------------------------------------------------
#
# shapes[0] = bar_green  (bottom)
# shapes[1] = bar_red
# shapes[2] = mask       (top -- black rect that slides right)
#
# display.py wraps each in _GroupElement and adds them to Splashes children.
# The mask must be added last (highest z-order) so it occludes the bars.
#
##############################################################################

from adafruit_display_shapes.rect import Rect
from pyswitch.colors import Colors

_BAR_Y = 192
_BAR_H = 8
_BAR_W = 240


class ProgressBarDisplay:
    """Thin progress bar at the bottom of the center display area.

    Lifecycle
    ---------
    display.py instantiates one PROGRESS_BAR at module level.
    Shapes are wrapped in _GroupElement and added to Splashes children list.
    All shapes start hidden.

    lane_action.py calls:
      update(phase, is_green)   -- each frame while PLAYING or OVERDUBBING
      hide()                    -- all other states and when tuner is active
    """

    def __init__(self):
        # Green bar: visible during PLAYING
        self._bar_green = Rect(
            x      = 0,
            y      = _BAR_Y,
            width  = _BAR_W,
            height = _BAR_H,
            fill   = Colors.LIGHT_GREEN,
        )

        # Red bar: visible during OVERDUBBING
        self._bar_red = Rect(
            x      = 0,
            y      = _BAR_Y,
            width  = _BAR_W,
            height = _BAR_H,
            fill   = Colors.RED,
        )

        # Black mask: sits on top, slides right to reveal the colored bar.
        # Width stays 240 always; .x is repositioned each frame.
        # When x=0:   covers entire bar (nothing visible).
        # When x=240: fully off-screen (bar fully visible).
        self._mask = Rect(
            x      = 0,
            y      = _BAR_Y,
            width  = _BAR_W,
            height = _BAR_H,
            fill   = 0x000000,
        )

        # shapes: raw displayio Group subclasses wrapped by _GroupElement in display.py.
        # Order is significant: bars first, mask last (mask must be highest z-order).
        self.shapes = [self._bar_green, self._bar_red, self._mask]

        # Delta gates to avoid redundant display writes
        self._last_phase    = None
        self._last_is_green = None

        self.hide()

    def hide(self):
        """Hide all shapes and reset delta gates."""
        for shape in self.shapes:
            shape.hidden = True
        self._last_phase    = None
        self._last_is_green = None

    def update(self, phase, is_green):
        """Reveal bar up to `phase` (0-127).

        Args:
            phase:    int 0-127, loop playback position from snapshot /
                      dead-reckoning.  0 = start of loop, 127 = end of loop.
            is_green: True = PLAYING state (green bar).
                      False = OVERDUBBING state (red bar).
        """
        # Toggle color bars when state changes (only .hidden propagates reliably)
        if is_green != self._last_is_green:
            self._bar_green.hidden = not is_green
            self._bar_red.hidden   = is_green
            self._last_is_green    = is_green

        # Reposition mask to reveal bar up to `phase`
        if phase != self._last_phase:
            self._mask.x      = phase * _BAR_W // 127
            self._mask.hidden = False
            self._last_phase  = phase
