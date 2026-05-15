##############################################################################
#
# Ultra8 NANO4 — ULTRA8_PAGE_NAV action.
#
# Assign to an actionsHold entry to navigate between lanes/pages at runtime.
# On activation:
#   1. Calls page_state.increment() or page_state.decrement()
#   2. Calls appl.reset_actions() so the framework refreshes all displays
#
# The centre "Lane N" label is updated by lane_state.py on the very next
# update_displays() cycle — no extra wiring required here.
#
# LEDs and the corner display label are intentionally left to the co-assigned
# short-press action (use_leds defaults to False, display defaults to None).
#
# Usage in inputs.py:
#
#   from pyswitch.clients.ultra8.actions.page_nav import ULTRA8_PAGE_NAV
#
#   # Switch 2 long → page up
#   "actionsHold": [
#       ULTRA8_PAGE_NAV(direction=+1, use_leds=False, display=None),
#   ],
#
#   # Switch B long → page down
#   "actionsHold": [
#       ULTRA8_PAGE_NAV(direction=-1, use_leds=False, display=None),
#   ],
#
##############################################################################

from ....controller.callbacks import Callback
from ....controller.actions import Action


def ULTRA8_PAGE_NAV(
    direction,                # +1 = increment page, -1 = decrement page
    display         = None,   # DisplayLabel for corner label (normally None)
    use_leds        = False,  # LEDs owned by short-press action on the same button
    id              = None,
    enable_callback = None,
):
    """Hold action: increment or decrement the current page. No MIDI sent."""
    return Action({
        "callback":       _PageNavCallback(direction=direction),
        "display":        display,
        "useSwitchLeds":  use_leds,
        "id":             id,
        "enableCallback": enable_callback,
    })


class _PageNavCallback(Callback):

    def __init__(self, direction):
        super().__init__()
        self.__direction  = direction
        self.__page_state = None

    def init(self, appl, listener=None):
        self.__appl = appl
        try:
            from pyswitch.clients.ultra8 import page_state
            self.__page_state = page_state
        except ImportError:
            pass   # running without the Ultra8 client (tests, emulator)

    def push(self):
        if self.__page_state is None:
            return
        if self.__direction > 0:
            self.__page_state.increment()
        else:
            self.__page_state.decrement()
        self.__appl.reset_actions()

    def update_displays(self):
        pass   # LEDs and label are owned by the co-assigned short-press action
