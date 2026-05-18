##############################################################################
#
# Ultra8 NANO4 — MIDI communication configuration.
#
# Routing: USB MIDI + DIN MIDI / TRS active simultaneously.
#   - USB: bench/development — direct connection to host computer.
#   - DIN (GP16/GP17): live use through the MOTU MIDI Express XT.
#   - Both interfaces receive into the application and transmit from it.
#     No cross-forwarding between USB and DIN — each carries its own traffic.
#
# in_channel = None  → accept MIDI on all inbound channels.
#   Ultra8 broadcasts SysEx snapshots; accepting all channels ensures the
#   device receives them regardless of the source channel.
#
# IMPORTANT — live DIN wiring through the MOTU MIDI Express XT:
#   Use TWO separate MOTU ports, one for each direction.
#
#   NANO4 DIN OUT  →  MOTU Port A (IN)   →  computer  (button CCs to Ultra8)
#   computer       →  MOTU Port B (OUT)  →  NANO4 DIN IN  (SysEx from Ultra8)
#
#   Do NOT loop NANO4 DIN OUT and DIN IN through the same MOTU port.
#   The MOTU hardware echoes DIN In back to the same port's DIN Out, so any
#   CC the NANO4 sends would arrive at its own DIN In mid-SysEx and cause
#   adafruit_midi to abort SysEx assembly (per the MIDI spec).  Using
#   separate ports eliminates the echo entirely.
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

_protocol = Ultra8Protocol()

Communication = {
    "protocol": _protocol,

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
