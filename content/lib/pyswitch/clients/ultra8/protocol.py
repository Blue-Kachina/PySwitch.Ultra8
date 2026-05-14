##############################################################################
#
# Ultra8 PySwitch — Bidirectional protocol stub.
#
# Current scope (Unit 1.3):
#   Proves the NANO4 can receive MIDI by listening for a test CC and
#   updating the centre status display when it arrives.
#
# Future scope (Milestone 3):
#   receive() will parse v0.1 SysEx snapshots and route lane state to
#   callbacks that drive LED and screen updates.
#
# ── Test procedure (Unit 1.3) ─────────────────────────────────────────────
#
#   1. Deploy updated firmware to NANO4.
#   2. Open Reaper (or any MIDI tool) and route its MIDI output to the
#      NANO4 USB MIDI port.
#   3. Send  CC 80, any value, on any channel.
#   4. The centre status line on the NANO4 screen should change from
#      "Waiting for snapshot..." to "RX OK  val=<value>".
#
##############################################################################

from adafruit_midi.control_change import ControlChange
from pyswitch.controller.client import ClientParameterMapping
from pyswitch.colors import Colors

# CC number used for the incoming receive test (arbitrary; not used by Ultra8).
# Replace with the SysEx handler in Milestone 3.
_TEST_CC = 80


class Ultra8Protocol:
    """
    Minimal bidirectional protocol stub for the Ultra8 client.

    Required interface for BidirectionalClient:
      init(midi, client)       – called once on startup
      receive(midi_message)    – called for unhandled incoming messages
      update()                 – called periodically
      is_bidirectional(mapping)– True if a mapping should skip polling
      feedback_value(mapping)  – True if a set() should echo back to listeners
    """

    def __init__(self):
        self.debug = False          # Set externally by BidirectionalClient
        self._status_label = None

    # ── BidirectionalClient interface ─────────────────────────────────────

    def init(self, midi, client):
        self._midi   = midi
        self._client = client

        # Late import: display.py is loaded after communication.py, so this
        # import is safe here (called from BidirectionalClient.__init__ which
        # runs after all config modules are imported by process.py).
        try:
            from display import DISPLAY_STATUS
            self._status_label = DISPLAY_STATUS
        except ImportError:
            pass  # Running in a test harness without a display — safe to skip

        # Register a permanent listener for the test CC.
        # ClientParameterMapping with response-only and no request means the
        # ClientRequest never times out, so it fires on every matching message.
        mapping = ClientParameterMapping.get(
            name     = "Ultra8RxTest",
            response = ControlChange(_TEST_CC, 0),
        )
        client.register(mapping, self)

    def receive(self, midi_message):
        """Called for any incoming message not already parsed by Client.
        SysEx snapshot parsing will live here in Milestone 3."""
        return False

    def update(self):
        """Periodic protocol maintenance — nothing needed yet."""
        pass

    def is_bidirectional(self, mapping):
        return False

    def feedback_value(self, mapping):
        return False

    # ── ClientRequestListener interface ──────────────────────────────────

    def parameter_changed(self, mapping):
        """Called when the test CC is received."""
        if self._status_label:
            self._status_label.text_color = Colors.LIGHT_GREEN
            self._status_label.text = "RX OK  val=" + str(mapping.value)

    def request_terminated(self, mapping):
        pass
