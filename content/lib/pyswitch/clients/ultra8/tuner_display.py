##############################################################################
#
# Ultra8 NANO4 -- Tuner Animation Display (T2/T5)
#
# Owns all graphical elements for the tuner overlay:
#   - Horizontal track line (Rect)
#   - Fixed open ring at center (Circle, target zone)
#   - Moving ball: white when out of tune, green when within _IN_TUNE_CENTS
#     Two pre-built Circles are toggled via .hidden because Circle.fill
#     writes do not propagate to the display at runtime in this firmware build.
#   - Note name label below the shapes (DisplayLabel, PTSans-NarrowBold-40)
#
# All elements start hidden.  Call show()/hide() to toggle and
# update() each frame to reposition the ball and refresh the note name.
#
# -- Layout (y coords, 240x240 display) ---------------------------------------
#
#   y=113  ------------------------------------------  track line (3px Rect)
#   y=115  --------------(o)------------------        ring, fixed x=120, r=18
#          --------------*-------------------          ball, x=120+offset, r=12
#   y=142  E1                                          note name (PTSans 40px)
#
# -- Ball x formula -----------------------------------------------------------
#
#   direction  = +1 if sharp (cents_sign==1), else -1
#   offset     = direction * cents_mag * 90 // 50    (range: -90..+90 px)
#   ball.x     = ball_base_x + offset
#               where ball_base_x = x0 - r = 120 - 12 = 108  (Group initial x)
#
#   Net screen center of ball = ball_base_x + offset + r = 120 + offset
#
# -- adafruit_display_shapes positioning note ---------------------------------
#
#   Circle(x0=120) bakes center into the bitmap AND sets Group.x = x0-r.
#   Assigning group.x = value REPLACES the initial x (not additive).
#   So: self._ball.x = self._ball_x0 + offset, NOT self._ball.x = offset.
#
# -- In-tune zone -------------------------------------------------------------
#
#   Ball exits ring when |offset| > r_ring - r_ball = 18 - 12 = 6 px
#   => tolerance approx +/-3 cents
#
# -- Draw order (bottom to top) -----------------------------------------------
#
#   line        (Rect, white fill)
#   ring        (Circle, black fill + white outline)
#   _ball_white (Circle, white fill)  -- shown when out of tune
#   _ball_green (Circle, green fill)  -- shown when in tune
#   note_label  (DisplayLabel, PTSans-NarrowBold-40)
#
#   display.py appends shapes via _GroupElement and note_label directly.
#
##############################################################################

from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.circle import Circle
from pyswitch.ui.elements import DisplayLabel
from pyswitch.ui.ui import DisplayBounds
from pyswitch.colors import Colors

# -- Layout constants ---------------------------------------------------------

_CX            = 120   # Center x (in-tune position)
_LINE_Y        = 113   # Top edge of the track Rect
_RING_CY       = 115   # y-center for ring and ball
_RING_R        = 18    # Ring radius (px)
_BALL_R        = 12    # Ball radius (px)
_MAX_OFF       = 90    # Pixel offset at +/-50 cents
_IN_TUNE_CENTS = 5     # Ball turns green within this many cents

_NOTE_LABEL_Y  = 142   # Top of note name label
_NOTE_LABEL_H  = 40    # Height (matches PTSans-NarrowBold-40 cap height)


class TunerAnimDisplay:
    """Graphical tuner overlay: track line, target ring, sliding ball, note name.

    Lifecycle
    ---------
    display.py instantiates one TUNER_ANIM at module level.
    Shapes are wrapped in _GroupElement and added to the Splashes children list.
    note_label is a DisplayLabel and is added directly to Splashes children.
    All elements start hidden.

    tuner_action.py calls:
      show()                          -- when TUNER_ACTIVE and note locked
      hide()                          -- all other states
      update(mag, sign, note_str)     -- each frame while shown
    """

    def __init__(self):
        # Track line (white horizontal bar)
        self._line = Rect(
            x      = 18,
            y      = _LINE_Y,
            width  = 204,
            height = 3,
            fill   = 0xFFFFFF,
        )

        # Target ring (fixed center). Black fill = transparent on black bg.
        self._ring = Circle(
            x0      = _CX,
            y0      = _RING_CY,
            r       = _RING_R,
            fill    = 0x000000,
            outline = 0xFFFFFF,
            stroke  = 2,
        )

        # Two pre-built balls: Circle.fill does not propagate at runtime in this
        # firmware build, so we maintain one white and one green Circle and toggle
        # .hidden between them (which does propagate).
        self._ball_white = Circle(
            x0   = _CX,
            y0   = _RING_CY,
            r    = _BALL_R,
            fill = 0xFFFFFF,
        )
        self._ball_green = Circle(
            x0   = _CX,
            y0   = _RING_CY,
            r    = _BALL_R,
            fill = Colors.LIGHT_GREEN,
        )
        # Both balls share the same base x (same x0 and r).
        self._ball_x0 = self._ball_white.x   # = _CX - _BALL_R = 108

        # Note name label (large, below shapes).
        # DisplayLabel.hidden does not work (backing Group is a framework-internal
        # local variable).  We clear .text to "" to make it invisible instead.
        self.note_label = DisplayLabel(
            bounds = DisplayBounds(0, _NOTE_LABEL_Y, 240, _NOTE_LABEL_H),
            layout = {
                "font":      "/fonts/PTSans-NarrowBold-40.pcf",
                "text":      "",
                "textColor": Colors.WHITE,
            },
        )

        # shapes: raw displayio groups wrapped by _GroupElement in display.py
        # note_label: DisplayElement added directly to Splashes children
        self.shapes = [self._line, self._ring, self._ball_white, self._ball_green]

        # Delta gates
        self._last_offset    = None
        self._last_note_str  = None
        self._last_in_tune   = None   # bool: was ball green last frame?

        self.hide()

    # -- Visibility -----------------------------------------------------------

    def show(self):
        """Make track and ring visible. Balls are revealed by update()."""
        self._line.hidden = False
        self._ring.hidden = False
        # Balls are shown/hidden by update() based on cents; leave as-is here.

    def hide(self):
        """Hide all shapes and clear the note label."""
        for shape in self.shapes:
            shape.hidden = True
        self.note_label.text = ""
        # Reset gates so the next show()+update() cycle writes fresh state
        self._last_offset   = None
        self._last_note_str = None
        self._last_in_tune  = None

    # -- Per-frame update -----------------------------------------------------

    def update(self, cents_mag, cents_sign, note_str):
        """Reposition the ball and refresh the note name label.

        cents_mag:  int 0-50   (magnitude)
        cents_sign: int 0=flat, 1=sharp
        note_str:   str e.g. "A", "E1", "C#2"
        """
        direction = 1 if cents_sign == 1 else -1
        offset    = direction * cents_mag * _MAX_OFF // 50

        if offset != self._last_offset:
            new_x = self._ball_x0 + offset
            self._ball_white.x = new_x
            self._ball_green.x = new_x
            self._last_offset  = offset

        in_tune = cents_mag <= _IN_TUNE_CENTS
        if in_tune != self._last_in_tune:
            self._ball_green.hidden = not in_tune
            self._ball_white.hidden = in_tune
            self._last_in_tune      = in_tune

        if note_str != self._last_note_str:
            self.note_label.text = note_str
            self._last_note_str  = note_str
