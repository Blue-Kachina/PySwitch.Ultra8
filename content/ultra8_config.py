##############################################################################
#
# Per-device deployment configuration for Ultra8 NANO4 firmware.
#
# This is the ONLY file that should differ between physical NANO4 units.
# All other firmware files are identical across devices.
#
# To configure a device:
#   - Set DEFAULT_CHANNEL to the Ultra8 lane this device controls.
#   - Lane 1 → MIDI channel 1, Lane 2 → MIDI channel 2, etc.
#   - Valid range: 1–8.
#
# Example assignments:
#   Device A (left player)   → DEFAULT_CHANNEL = 1
#   Device B (centre player) → DEFAULT_CHANNEL = 3
#   Device C (right player)  → DEFAULT_CHANNEL = 5
#
##############################################################################

DEFAULT_CHANNEL = 1   # Device A: controls Ultra8 Lane 1

# How long (milliseconds) to wait without receiving any feedback CC before
# reverting the ButtonA LED and status bar to the "waiting" state.
# 5 seconds is conservative — reduce if the rig sends snapshots more often.
FEEDBACK_TIMEOUT_MS = 5000
