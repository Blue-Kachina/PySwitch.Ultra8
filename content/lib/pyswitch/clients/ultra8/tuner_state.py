##############################################################################
#
# Ultra8 PySwitch — Tuner state machine.
#
# Tuner Ph1: New module.
#
# Shared module-level state machine for the tuner overlay.  Consumed by:
#   tuner_action.py  — reads state to drive the center display and LED
#   protocol.py      — calls receive_update() when a 0x04 tuner SysEx arrives
#   lane_action.py   — checks is_active() before sending normal lane CCs
#
# ── State enum ───────────────────────────────────────────────────────────────
#
#   NORMAL          No tuner overlay.  Lane CCs work normally.
#
#   TUNER_PENDING   CC26 value=127 sent; waiting for first tuner SysEx from
#                   Ultra8.  If no SysEx arrives within NO_DATA_TIMEOUT_MS the
#                   state automatically transitions to TUNER_NO_DATA.
#
#   TUNER_ACTIVE    Tuner SysEx is arriving.  Display shows pitch data.
#                   Transitions back to TUNER_PENDING if data stops for
#                   NO_DATA_TIMEOUT_MS.
#
#   TUNER_NO_DATA   No tuner data for NO_DATA_TIMEOUT_MS.  Sends CC26=0 to
#                   exit tuner mode, then waits for confirmation.  If no
#                   snapshot arrives within EXIT_TIMEOUT_MS, goes to NORMAL.
#
#   NORMAL_PENDING  CC26 value=0 sent; waiting for Ultra8 snapshot to confirm
#                   tuner_enabled=0.  Falls back to NORMAL on EXIT_TIMEOUT_MS.
#
# ── Non-blocking timeouts ────────────────────────────────────────────────────
#
#   All timeouts are checked in tuner_action.update_displays() each loop
#   cycle via get_current_millis() — no sleep or blocking of any kind.
#
##############################################################################

from ...misc import get_current_millis

# ── State constants ───────────────────────────────────────────────────────────

NORMAL         = "NORMAL"
TUNER_PENDING  = "TUNER_PENDING"
TUNER_ACTIVE   = "TUNER_ACTIVE"
TUNER_NO_DATA  = "TUNER_NO_DATA"
NORMAL_PENDING = "NORMAL_PENDING"

# Timeout durations (milliseconds)
NO_DATA_TIMEOUT_MS = 30_000   # 30s without tuner SysEx → TUNER_NO_DATA
EXIT_TIMEOUT_MS    =  5_000   # 5s waiting for exit confirmation → force NORMAL

# ── Module-level state ────────────────────────────────────────────────────────

_state            = NORMAL
_state_entered_ms = None    # get_current_millis() when current state was entered

# Last received tuner data (updated by receive_update(); None if never received)
last_note         = None    # int 0–11 (C=0 … B=11)
last_octave       = None    # int (actual octave, e.g. 1 for E1)
last_cents_mag    = None    # int 0–50
last_cents_sign   = None    # int 0=flat, 1=sharp
last_confidence   = None    # int 0–127
last_signal_level = None    # int 0–127
last_stable       = None    # int 0 or 1


# ── Public helpers ────────────────────────────────────────────────────────────

def get_state():
    """Return the current state constant string."""
    return _state


def is_active():
    """True when the tuner overlay is visible (TUNER_PENDING / TUNER_ACTIVE /
    TUNER_NO_DATA / NORMAL_PENDING).  lane_action.push() checks this to
    intercept button presses and send CC26=0 instead of the normal lane CC.
    """
    return _state != NORMAL


def enter():
    """Transition to TUNER_PENDING.  Called by tuner_action when CC26=127 is sent."""
    global _state, _state_entered_ms
    _state            = TUNER_PENDING
    _state_entered_ms = get_current_millis()


def exit_to_normal():
    """Transition to NORMAL_PENDING.  Called when CC26=0 is sent (user request
    or automatic no-data timeout).  Caller is responsible for actually sending
    CC26=0 before calling this.
    """
    global _state, _state_entered_ms
    _state            = NORMAL_PENDING
    _state_entered_ms = get_current_millis()


def force_normal():
    """Immediately drop to NORMAL without going through NORMAL_PENDING.
    Used when a snapshot confirms tuner_enabled=0 (future Phase 4 hook),
    or when EXIT_TIMEOUT_MS expires in NORMAL_PENDING.
    """
    global _state, _state_entered_ms
    _state            = NORMAL
    _state_entered_ms = None


def receive_update(active, note, octave, cents_mag, cents_sign,
                   confidence, signal_level, stable):
    """Called by protocol._receive_tuner() when a 0x04 SysEx arrives.

    If active == 0: the JSFX side confirmed tuner exit — transition to NORMAL.
    If active == 1: store the pitch data and advance state machine toward
                    TUNER_ACTIVE.
    """
    global _state, _state_entered_ms
    global last_note, last_octave, last_cents_mag, last_cents_sign
    global last_confidence, last_signal_level, last_stable

    if active == 0:
        # Ultra8 confirmed tuner off — drop to NORMAL immediately
        force_normal()
        return

    # Store the latest pitch data regardless of current state
    last_note         = note
    last_octave       = octave
    last_cents_mag    = cents_mag
    last_cents_sign   = cents_sign
    last_confidence   = confidence
    last_signal_level = signal_level
    last_stable       = stable

    # Advance state: any active packet moves us into / keeps us in TUNER_ACTIVE
    if _state in (TUNER_PENDING, TUNER_ACTIVE, TUNER_NO_DATA):
        _state            = TUNER_ACTIVE
        _state_entered_ms = get_current_millis()


def check_timeouts(send_cc26_off_fn):
    """Check non-blocking timeouts.  Called every loop cycle from
    tuner_action.update_displays().

    send_cc26_off_fn — zero-argument callable that sends CC26 value=0 on the
                       current lane channel (provided by tuner_action so that
                       tuner_state has no direct MIDI dependency).
    """
    global _state, _state_entered_ms

    if _state_entered_ms is None:
        return

    now     = get_current_millis()
    elapsed = now - _state_entered_ms

    if _state in (TUNER_PENDING, TUNER_ACTIVE):
        if elapsed >= NO_DATA_TIMEOUT_MS:
            # 30s without data — send CC26=0 and move to NORMAL_PENDING
            send_cc26_off_fn()
            exit_to_normal()

    elif _state == NORMAL_PENDING:
        if elapsed >= EXIT_TIMEOUT_MS:
            # 5s without confirmation — give up and force NORMAL
            force_normal()
