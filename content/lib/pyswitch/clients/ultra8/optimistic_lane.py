##############################################################################
#
# Ultra8 PySwitch — Shared optimistic lane state.
#
# When a button is pressed, its callback writes a predicted lane block here
# before the real SysEx snapshot confirms the change.  Every lane action
# callback on the same lane reads this prediction first, giving instant,
# consistent LED feedback across all buttons simultaneously.
#
# Prediction format per lane:
#   (state, dirty, reverse, undo_redo_state, seq_at_press)
#
# The prediction is cleared by any callback the moment it sees a real
# snapshot with a seq that differs from seq_at_press.
#
# Thread safety: CircuitPython is single-threaded; a plain dict is fine.
#
##############################################################################

# Maps lane_index (int, 0-based) → (state, dirty, reverse, undo_redo_state, seq_at_press)
_store = {}


def set(lane, state, dirty, reverse, undo_redo_state, seq):
    """Record a predicted lane block after a button press."""
    _store[lane] = (state, dirty, reverse, undo_redo_state, seq)


def get(lane):
    """Return the pending prediction tuple for this lane, or None."""
    return _store.get(lane)


def clear(lane):
    """Discard any pending prediction for this lane."""
    _store.pop(lane, None)
