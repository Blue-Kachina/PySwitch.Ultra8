##############################################################################
#
# Ultra8 NANO4 — Waveform Renderer (Unit B.2b)
#
# Draws a scrolling sine waveform into a 240×30 displayio.Bitmap.
# No floats at draw time — all math uses the pre-baked integer sine table.
#
# Usage:
#   from pyswitch.clients.ultra8.waveform import draw_waveform, clear_waveform
#
#   draw_waveform(WAVEFORM_BITMAP, phase, color_index)
#   clear_waveform(WAVEFORM_BITMAP)
#
# The Bitmap and its Palette/TileGrid are defined in display.py and added to
# the displayio splash group there. This module only writes pixel data.
#
##############################################################################

# ── Integer sine table ────────────────────────────────────────────────────────
#
# 256 entries, values 0–254. Interpretation: signed_val = entry - 127.
# Generated from: int(127 + sin(i / 256 * 2π) * 127) for i in range(256).
# Stored as bytes — 256 bytes of RAM, no float math at draw time.

_SINE_TABLE = bytes([
    127, 130, 133, 136, 139, 142, 145, 148, 151, 154, 157, 160, 163, 166, 169, 172,
    175, 178, 181, 184, 186, 189, 192, 194, 197, 200, 202, 205, 207, 209, 212, 214,
    216, 218, 221, 223, 225, 227, 229, 230, 232, 234, 235, 237, 239, 240, 241, 243,
    244, 245, 246, 247, 248, 249, 250, 250, 251, 252, 252, 253, 253, 253, 253, 253,
    254, 253, 253, 253, 253, 253, 252, 252, 251, 250, 250, 249, 248, 247, 246, 245,
    244, 243, 241, 240, 239, 237, 235, 234, 232, 230, 229, 227, 225, 223, 221, 218,
    216, 214, 212, 209, 207, 205, 202, 200, 197, 194, 192, 189, 186, 184, 181, 178,
    175, 172, 169, 166, 163, 160, 157, 154, 151, 148, 145, 142, 139, 136, 133, 130,
    127, 123, 120, 117, 114, 111, 108, 105, 102,  99,  96,  93,  90,  87,  84,  81,
     78,  75,  72,  69,  67,  64,  61,  59,  56,  53,  51,  48,  46,  44,  41,  39,
     37,  35,  32,  30,  28,  26,  24,  23,  21,  19,  18,  16,  14,  13,  12,  10,
      9,   8,   7,   6,   5,   4,   3,   3,   2,   1,   1,   0,   0,   0,   0,   0,
      0,   0,   0,   0,   0,   0,   1,   1,   2,   3,   3,   4,   5,   6,   7,   8,
      9,  10,  12,  13,  14,  16,  18,  19,  21,  23,  24,  26,  28,  30,  32,  35,
     37,  39,  41,  44,  46,  48,  51,  53,  56,  59,  61,  64,  67,  69,  72,  75,
     78,  81,  84,  87,  90,  93,  96,  99, 102, 105, 108, 111, 114, 117, 120, 123,
])

# ── Canvas constants ──────────────────────────────────────────────────────────

_W    = 240    # bitmap width  (must match WAVEFORM_BITMAP in display.py)
_H    = 30     # bitmap height
_MID  = 15    # vertical center
_AMP  = 12    # peak amplitude in pixels (leaves 3px margin top and bottom)


def draw_waveform(bitmap, phase, color_index):
    """Draw one scrolling sine frame into the waveform Bitmap.

    Args:
        bitmap:      displayio.Bitmap — the WAVEFORM_BITMAP from display.py
        phase:       int 0–127 — current loop playback position (dead-reckoned)
        color_index: int — palette index for the waveform color (1=playing, 2=overdub)

    Draws a 3-pixel-thick sine curve. Uses bitmap.fill(0) to clear (one fast
    C call), then writes ~720 pixels for the curve. ~10× faster than filling
    all 7200 pixels individually.

    NOTE: As of this writing, displayio.Bitmap runtime writes do not propagate
    to the ST7789 display in this firmware build. This function is correct and
    ready to use once the display update path is resolved. See
    docs/animation_brainstorming.md §Bitmap Display Investigation.
    """
    bitmap.fill(0)
    scroll = phase * 2
    x = 0
    while x < _W:
        angle = (x * 256 // _W + scroll) & 0xFF
        s     = _SINE_TABLE[angle] - 127
        y_mid = _MID - s * _AMP // 127
        for y in (y_mid - 1, y_mid, y_mid + 1):
            if 0 <= y < _H:
                bitmap[x, y] = color_index
        x += 1


def clear_waveform(bitmap):
    """Fill the entire waveform Bitmap with palette index 0 (background)."""
    bitmap.fill(0)
