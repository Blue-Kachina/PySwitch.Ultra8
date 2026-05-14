##############################################################################
#
# Ultra8 NANO4 — MIDI communication configuration.
#
# Routing: USB MIDI (bidirectional).
#   - Suitable for bench testing with a software MIDI monitor on a computer.
#   - For live use through the MOTU MIDI Express XT, swap PA_MIDICAPTAIN_USB_MIDI
#     for PA_MIDICAPTAIN_DIN_MIDI (TRS/5-pin via UART on GP16/GP17).
#
# in_channel = None  → accept MIDI on all inbound channels.
#   Ultra8 will eventually broadcast SysEx snapshots; accepting all channels
#   ensures the device receives them regardless of the source channel.
#
# No bidirectional protocol is set here. Ultra8 snapshot parsing is handled
# entirely inside the Ultra8 client actions/callbacks (to be added in
# Milestone 3). Until then the device sends button CCs and receives nothing.
#
##############################################################################

from pyswitch.controller.midi import MidiRouting
from pyswitch.hardware.devices.pa_midicaptain import PA_MIDICAPTAIN_USB_MIDI
from pyswitch.clients.ultra8.protocol import Ultra8Protocol

# USB MIDI — connect to a computer for testing.
# For MOTU routing, replace with:
#   from pyswitch.hardware.devices.pa_midicaptain import PA_MIDICAPTAIN_DIN_MIDI
#   _MIDI = PA_MIDICAPTAIN_DIN_MIDI(in_channel=None, out_channel=0)
_MIDI = PA_MIDICAPTAIN_USB_MIDI(
    in_channel  = None,   # Accept all channels (SysEx snapshots arrive on any channel)
    out_channel = 0,      # 0-indexed: channel 1 (raw CC bytes in inputs.py encode the lane channel directly)
)

Communication = {
    # Ultra8Protocol handles incoming MIDI (test CC for Unit 1.3, SysEx snapshots in Milestone 3).
    "protocol": Ultra8Protocol(),

    "midi": {
        "routings": [
            # Receive MIDI from USB into the application
            MidiRouting(
                source = _MIDI,
                target = MidiRouting.APPLICATION,
            ),
            # Send MIDI from the application out over USB
            MidiRouting(
                source = MidiRouting.APPLICATION,
                target = _MIDI,
            ),
        ]
    },
}
