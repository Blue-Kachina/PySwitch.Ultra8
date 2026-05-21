##############################################################################
#
# Ultra8 PySwitch — Shared assignment store.
#
# Unit 6.4: populated by protocol.py when it receives a v0.1 assignment
# message (msg_type 0x02).  Exposes get_label(control_id) so that
# ULTRA8_LABELED_BUTTON and ULTRA8_LANE_STATE can read dynamic corner-label
# text each display cycle without re-implementing the store logic.
#
# Design notes:
#   - Module-level singleton dict (_store) — CircuitPython has no threading so
#     a plain dict is safe.
#   - Before the first assignment message arrives, get_label() returns the
#     static function name so corner labels are always readable.
#   - If a control is explicitly set to OFF (msg_type 0), get_label() returns
#     "---" so the user can see that Ultra8 has disabled that function.
#   - Unknown control IDs (>4) are stored but label falls back to "???".
#
##############################################################################

# ── Control ID → human-readable function name ─────────────────────────────
# Names match the control-ID enum in docs/protocol_assignment_metadata_v0_1.md
# Used by get_label() for corner display text (legacy / ULTRA8_LABELED_BUTTON).
_NAMES = {
    0: "REC",
    1: "PLAY",
    2: "CLR",
    3: "MON",
    4: "UNDO",
    5: "REV",
}

# ── Control ID → internal function name ────────────────────────────────────
# Keys match function names in dynamic_leds.json.
# Used by ULTRA8_LANE_ACTION for LED lookup.
_FUNCTION_NAMES = {
    0: "REC_PLY",
    1: "PLY_STP",
    2: "CLR",
    3: "MON",
    4: "UNDO_REDO",
    5: "REV",
}

# ── Internal function name → display label ─────────────────────────────────
# Human-readable text shown in button corner labels (tier-3 resolution).
_DISPLAY_LABELS = {
    "REC_PLY":   "REC/PLY",
    "PLY_STP":   "PLY/STP",
    "CLR":       "CLR",
    "MON":       "MON",
    "UNDO_REDO": "UNDO",
    "REV":       "REV",
}

# Fallback shown before the first assignment message is received.
_LABEL_UNKNOWN = "???"

# Shown when Ultra8 has explicitly set an assignment to OFF / disabled.
_LABEL_OFF = "---"

# MIDI message type enum — matches protocol spec §Message Type Enum.
MSG_TYPE_OFF  = 0
MSG_TYPE_NOTE = 1
MSG_TYPE_CC   = 2
MSG_TYPE_PC   = 3

# ── Internal store ─────────────────────────────────────────────────────────
# Maps control_id (int) → (msg_type, msg_number) tuple.
# Empty until the first valid assignment message is accepted by protocol.py.
_store = {}


def update(control_id, msg_type, msg_number):
    """Record the current assignment for one control.

    control_id  — int, 0–127.  Values 0–4 map to the five common-mode
                  controls; higher values are stored but labels fall back
                  to _LABEL_UNKNOWN (forward-compatibility).
    msg_type    — int, 0–3 (OFF / NOTE / CC / PC per protocol enum).
    msg_number  — int, 0–127.
    """
    _store[control_id] = (msg_type & 0x7F, msg_number & 0x7F)


def get_function_name(control_id):
    """Return the internal function name (e.g. "REC_PLY") for the given
    control ID.  Used for dynamic_leds.json key lookup.

    Returns None for unknown control IDs.
    """
    return _FUNCTION_NAMES.get(control_id)


def get_function_by_cc(msg_number):
    """Reverse-lookup: find the function name assigned to a given CC number.

    Searches the assignment store for a control with msg_type=CC and the
    given msg_number.  Returns the internal function name (e.g. "REC_PLY")
    if found, or None if the store is empty or no control is mapped to
    that CC number.

    Used by ULTRA8_LANE_ACTION to discover which Ultra8 function is
    currently bound to a button's CC, enabling dynamic LED resolution
    without a pre-declared control_id.
    """
    for control_id, (stored_type, number) in _store.items():
        if stored_type == MSG_TYPE_CC and number == msg_number:
            return _FUNCTION_NAMES.get(control_id)
    return None


def get_display_label(function_name):
    """Return the human-readable corner-label string for an internal
    function name (e.g. "REC_PLY" → "REC/PLY").

    Returns the function_name unchanged if it is not in the table
    (forward-compatibility with future function names).
    """
    return _DISPLAY_LABELS.get(function_name, function_name)


def get_label(control_id):
    """Return a corner-label string for the given control ID.

    Before the first assignment message:      static function name
                                              (e.g. "PLY/STP")
    After assignment message, type != OFF:    static function name
    After assignment message, type == OFF:    "---"
    Unknown control_id (not in _NAMES):       "???"
    """
    entry = _store.get(control_id)
    if entry is None:
        # No assignment message received yet — static fallback so the label
        # is always readable on first boot.
        return _NAMES.get(control_id, _LABEL_UNKNOWN)
    msg_type, _ = entry
    if msg_type == MSG_TYPE_OFF:
        return _LABEL_OFF
    return _NAMES.get(control_id, _LABEL_UNKNOWN)
