##############################################################################
#
# Ultra8 NANO4 — MIDI communication configuration.
#
# Routing: USB MIDI + DIN MIDI / TRS active simultaneously.
#   - USB: for monitoring / development on a host computer.
#   - DIN (GP16/GP17): for live use through the MOTU MIDI Express XT.
#   - Both interfaces receive into the application and transmit from it.
#     No cross-forwarding between USB and DIN — each carries its own traffic.
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
from pyswitch.hardware.devices.pa_midicaptain import PA_MIDICAPTAIN_USB_MIDI, PA_MIDICAPTAIN_DIN_MIDI
from pyswitch.clients.ultra8.protocol import Ultra8Protocol

_USB_MIDI = PA_MIDICAPTAIN_USB_MIDI(
    in_channel  = None,   # Accept all channels (SysEx snapshots arrive on any channel)
    out_channel = 0,      # 0-indexed: channel 1
)

_DIN_MIDI = PA_MIDICAPTAIN_DIN_MIDI(
    in_channel  = None,   # Accept all channels
    out_channel = 0,      # 0-indexed: channel 1
)

Communication = {
    # Ultra8Protocol handles incoming MIDI (test CC for Unit 1.3, SysEx snapshots in Milestone 3).
    "protocol": Ultra8Protocol(),

    "midi": {
        "routings": [
            # USB: receive into application, send from application
            MidiRouting(source = _USB_MIDI,              target = MidiRouting.APPLICATION),
            MidiRouting(source = MidiRouting.APPLICATION, target = _USB_MIDI),

            # DIN: receive into application, send from application
            MidiRouting(source = _DIN_MIDI,              target = MidiRouting.APPLICATION),
            MidiRouting(source = MidiRouting.APPLICATION, target = _DIN_MIDI),
        ]
    },
}
