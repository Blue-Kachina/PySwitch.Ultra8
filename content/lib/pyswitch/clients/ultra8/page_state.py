##############################################################################
#
# Ultra8 NANO4 — Runtime page/lane state.
#
# Holds the device's *current* page (1–8) as a mutable module-level
# variable, initialised from DEFAULT_PAGE on first import.
#
# All code that needs the active MIDI channel or lane index should read
# from this module at runtime rather than from ultra8_config directly, so
# that button-driven page navigation takes effect immediately without a
# firmware restart.
#
# API:
#   page_state.get()        → int  current page (1–8)
#   page_state.increment()  →      advance one page, clamped at 8
#   page_state.decrement()  →      go back one page, clamped at 1
#
##############################################################################

_MIN_PAGE = 1
_MAX_PAGE = 8

try:
    from ultra8_config import DEFAULT_PAGE as _boot_page
    if not (_MIN_PAGE <= _boot_page <= _MAX_PAGE):
        _boot_page = _MIN_PAGE
except (ImportError, AttributeError):
    _boot_page = _MIN_PAGE

_current_page = _boot_page


def get():
    """Return the current page (1–8)."""
    return _current_page


def increment():
    """Advance to the next page, clamped at 8."""
    global _current_page
    if _current_page < _MAX_PAGE:
        _current_page += 1


def decrement():
    """Go back to the previous page, clamped at 1."""
    global _current_page
    if _current_page > _MIN_PAGE:
        _current_page -= 1
