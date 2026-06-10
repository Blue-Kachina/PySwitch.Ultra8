##############################################################################
#
# Ultra8 NANO4 — Tuner Animation Display (Unit T2)
#
# Self-contained class that owns the three graphical elements for the
# tuner overlay: a horizontal line, a fixed open ring (target zone), and a
# filled ball that slides along the line proportionally to cents deviation.
#
# All elements are hidden by default.  Call show() / hide() to toggle, and
# update() once per frame to reposition the ball.
#
# Text (note name and cents) is handled by tuner_action.py via the existing
# DISPLAY_STATE and DISPLAY_SEQ labels — this module only manages shapes.
#
# ── Layout ───────────────────────────────────────────────────────────────────
#
#   y=113  ────────────────────────────────  horizontal line  (3px Rect)
#   y=115  ──────────────(○)──────────────  ring, fixed at x=120, r=18
#          ──────────────●─────────────────  ball, x=120+offset, r=12
#
# ── Ball x formula ───────────────────────────────────────────────────────────
#
#   direction  = +1 if sharp (cents_sign==1), else -1
#   offset     = direction * cents_mag * 90 // 50    (range: -90..+90 px)
#   ball.x     = offset
#
#   Circle(x0=120) bakes the center position into the shape's geometry.
#   Setting ball.x = offset shifts the whole Group by `offset` pixels, so
#   the ball center appears at screen x = 120 + offset.
#
# ── In-tune zone ─────────────────────────────────────────────────────────────
#
#   Ball exits ring when |offset| > r_ring - r_ball = 18 - 12 = 6 px
#   → ≈ ±3 cents tolerance
#
# ── Draw order ────────────────────────────────────────────────────────────────
#
#   Elements are added to ui.splash (via _GroupElement in display.py) after
#   the text labels, so they render on top:
#
#     1. _line  (white Rect — the track)
#     2. _ring  (Circle, black fill + white outline — the target)
#     3. _ball  (Circle, white fill — the indicator)
#
#   The ring's black fill matches the display background, making it look like
#   an open circle.  The ball renders on top of both line and ring.
#
##############################################################################

from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.circle import Circle

# ── Layout constants ──────────────────────────────────────────────────────────

_CX       = 120   # Center x — in-tune position (pixels from left)
_LINE_Y   = 113   # Top of the horizontal track Rect
_RING_CY  = 115   # y-centre for both ring and ball
_RING_R   = 18    # Target ring radius  (px)
_BALL_R   = 12    # Moving ball radius  (px)
_MAX_OFF  = 90    # Pixel offset at ±50 cents


class TunerAnimDisplay:
    """Three displayio shapes that form the graphical tuner needle.

    Lifecycle
    ---------
    display.py instantiates one instance at module level (TUNER_ANIM).
    It wraps each shape in _GroupElement and adds them to the Splashes
    children list so the framework calls their init path correctly.

    tuner_action.py imports TUNER_ANIM and calls:
      show()              — when TUNER_ACTIVE + note locked
      hide()              — all other states
      update(mag, sign)   — each frame while shown
    """

    def __init__(self):
        # Track (white horizontal line)
        self._line = Rect(
            x      = 18,
            y      = _LINE_Y,
            width  = 204,
            height = 3,
            fill   = 0xFFFFFF,
        )

        # Target ring (fixed, always at x=_CX)
        # Black fill looks transparent against the black display background.
        self._ring = Circle(
            x0      = _CX,
            y0      = _RING_CY,
            r       = _RING_R,
            fill    = 0x000000,
            outline = 0xFFFFFF,
            stroke  = 2,
        )

        # Moving ball — x0=_CX bakes center into the Group geometry.
        # adafruit_display_shapes sets Group.x = x0 - r on construction.
        # We must ADD the per-frame offset to that base, not replace it.
        self._ball = Circle(
            x0   = _CX,
            y0   = _RING_CY,
            r    = _BALL_R,
            fill = 0xFFFFFF,
        )
        # Cache the Group's initial x so update() can apply offsets cleanly.
        self._ball_x0 = self._ball.x   # = _CX - _BALL_R = 108

        # Expose for display.py to wrap and add to Splashes
        self.shapes = [self._line, self._ring, self._ball]

        # Delta gate — avoid redundant Group.x writes
        self._last_offset = None

        # Start hidden; show() is called by tuner_action when a note locks
        self.hide()

    # ── Visibility ────────────────────────────────────────────────────────────

    def show(self):
        """Make all three shapes visible."""
        for shape in self.shapes:
            shape.hidden = False

    def hide(self):
        """Hide all three shapes."""
        for shape in self.shapes:
            shape.hidden = True

    # ── Per-frame update ──────────────────────────────────────────────────────

    def update(self, cents_mag, cents_sign):
        """Reposition the ball to reflect current cents deviation.

        cents_mag:  int 0–50   (magnitude)
        cents_sign: int 0=flat, 1=sharp
        """
        direction = 1 if cents_sign == 1 else -1
        offset    = direction * cents_mag * _MAX_OFF // 50

        if offset != self._last_offset:
            self._ball.x      = self._ball_x0 + offset
            self._last_offset = offset
