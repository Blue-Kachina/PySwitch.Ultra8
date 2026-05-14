##############################################################################
#
# Ultra8 PySwitch — Bidirectional protocol — SysEx snapshot parser.
#
# Unit 3.6: Full v0.1 SysEx parser
#
#   Parses, validates, and stores v0.1 full-state SysEx snapshots emitted
#   by Ultra8.  Replaces the Unit 1.3 CC 80 receive test stub.
#
#   The parsed snapshot is stored as self.snapshot (_Snapshot instance).
#   self.last_feedback_ms is updated on every accepted packet so that
#   lane_state.py stale detection can read it in Unit 3.7.
#
# Validation rules (see docs/protocol_sysex_v0_1.md §Firmware Parsing Rules):
#   1. manufacturer_id  == bytes([0x7D])
#   2. data[0]          == 0x55            (protocol ID)
#   3. data[1]          == 0x01            (version — reject others)
#   4. len(data)        == 30              (total packet length = 33 bytes)
#   5. data[6 + N*3]    == N  for N in 0–7 (lane_index sanity)
#   6. seq != last accepted seq            (duplicate suppression)
#   Any failure → silently discard; last valid snapshot is retained.
#
# Unit 3.7 will connect self.snapshot to lane_state.py rendering.
#
##############################################################################

from adafruit_midi.system_exclusive import SystemExclusive
from ...misc import get_current_millis

# ── v0.1 protocol constants ────────────────────────────────────────────────
_MANUFACTURER_ID  = bytes([0x7D])   # MIDI non-commercial / educational
_PROTOCOL_ID      = 0x55            # Ultra8 NANO4 protocol identifier
_PROTOCOL_VERSION = 0x01            # v0.1
_PACKET_DATA_LEN  = 30              # len(data) after manufacturer_id byte;
                                    #   full packet = 1(F0) + 1(mfr) + 30(data) + 1(F7) = 33
_NUM_LANES        = 8

# Lane state enum — matches Ultra8 encoder and protocol spec
STATE_STOPPED    = 0
STATE_PLAYING    = 1
STATE_RECORDING  = 2    # first-pass record (g_firstrec > 0)
STATE_OVERDUBBING = 3   # overdub on existing loop


# ── Data classes ───────────────────────────────────────────────────────────

class _LaneBlock:
    """Parsed lane data from one 3-byte lane block."""

    __slots__ = ("lane_index", "state", "dirty", "selected",
                 "monmode", "reverse", "loop_phase")

    def __init__(self, lane_index, flags, loop_phase):
        self.lane_index = lane_index
        self.state      =  flags        & 0x03
        self.dirty      = (flags >> 2)  & 0x01
        self.selected   = (flags >> 3)  & 0x01
        self.monmode    = (flags >> 4)  & 0x03
        self.reverse    = (flags >> 6)  & 0x01
        self.loop_phase = loop_phase

    def __repr__(self):
        return (
            "_LaneBlock(lane={} state={} dirty={} sel={} mon={} rev={} phase={})".format(
                self.lane_index, self.state, self.dirty,
                self.selected, self.monmode, self.reverse, self.loop_phase
            )
        )


class _Snapshot:
    """Fully parsed v0.1 SysEx snapshot."""

    __slots__ = ("seq", "any_active", "chan_selected", "lanes")

    def __init__(self, seq, global_flags, chan_selected, lanes):
        self.seq           = seq
        self.any_active    = global_flags & 0x01
        self.chan_selected = chan_selected   # 0–7, or 0x7F = no selection
        self.lanes         = lanes          # list of 8 _LaneBlock


# ── Protocol class ─────────────────────────────────────────────────────────

class Ultra8Protocol:
    """
    Ultra8 bidirectional protocol — v0.1 SysEx snapshot parser.

    Required interface for BidirectionalClient:
      init(midi, client)        – called once on startup
      receive(midi_message)     – called for unhandled incoming messages
      update()                  – called periodically
      is_bidirectional(mapping) – True if a mapping should skip polling
      feedback_value(mapping)   – True if a set() should echo back to listeners

    Public state (read by lane_state.py in Unit 3.7):
      self.snapshot          – last valid _Snapshot, or None
      self.last_feedback_ms  – get_current_millis() timestamp of last accepted
                               packet, or None if no packet received yet
    """

    def __init__(self):
        self.debug            = False        # set externally by BidirectionalClient
        self.snapshot         = None         # last valid _Snapshot
        self.last_feedback_ms = None         # ms timestamp of last accepted snapshot
        self._last_seq        = None         # seq of last accepted snapshot

    # ── BidirectionalClient interface ──────────────────────────────────────

    def init(self, midi, client):
        self._midi   = midi
        self._client = client

        # No listener registrations — incoming SysEx flows to receive() automatically.
        # Incoming SysEx is not claimed by any ClientParameterMapping, so it
        # falls through to receive() automatically.

    def receive(self, midi_message):
        """Parse an incoming v0.1 SysEx snapshot.

        Returns True if the message was recognised as an Ultra8 SysEx packet
        (valid or duplicate), False for anything else.  Malformed packets
        are silently discarded without updating self.snapshot.
        """
        if not isinstance(midi_message, SystemExclusive):
            return False

        # ── Validation step 1: manufacturer ID ───────────────────────────
        if midi_message.manufacturer_id != _MANUFACTURER_ID:
            return False

        data = midi_message.data

        # ── Validation step 2: data length (30 bytes → 33-byte packet) ───
        if len(data) != _PACKET_DATA_LEN:
            if self.debug:
                print("U8 proto: bad length", len(data), "(expected", _PACKET_DATA_LEN, ")")
            return False

        # ── Validation step 3: protocol ID ───────────────────────────────
        if data[0] != _PROTOCOL_ID:
            return False

        # ── Validation step 4: protocol version ──────────────────────────
        if data[1] != _PROTOCOL_VERSION:
            if self.debug:
                print("U8 proto: unsupported version", data[1])
            return False

        # ── Sequence number ───────────────────────────────────────────────
        seq = data[2] | (data[3] << 7)

        # ── Duplicate suppression ─────────────────────────────────────────
        if seq == self._last_seq:
            if self.debug:
                print("U8 proto: duplicate seq", seq, "— discarded")
            return True   # Recognised as ours but not stored.

        # ── Validation step 5: lane_index sanity for all 8 blocks ────────
        for n in range(_NUM_LANES):
            if data[6 + n * 3] != n:
                if self.debug:
                    print("U8 proto: lane_index mismatch at block", n,
                          "got", data[6 + n * 3])
                return False

        # ── Extract global fields ─────────────────────────────────────────
        global_flags  = data[4]
        chan_selected  = data[5]

        # ── Parse lane blocks ─────────────────────────────────────────────
        lanes = []
        for n in range(_NUM_LANES):
            base = 6 + n * 3
            lanes.append(_LaneBlock(
                lane_index = data[base],
                flags      = data[base + 1],
                loop_phase = data[base + 2],
            ))

        # ── Accept snapshot ───────────────────────────────────────────────
        self.snapshot         = _Snapshot(seq, global_flags, chan_selected, lanes)
        self._last_seq        = seq
        self.last_feedback_ms = get_current_millis()

        if self.debug:
            print("U8 proto: accepted seq={} any_active={} chan_sel={}".format(
                seq,
                self.snapshot.any_active,
                chan_selected if chan_selected != 0x7F else "none",
            ))

        return True

    def update(self):
        """Periodic protocol maintenance — nothing needed in v0.1."""
        pass

    def is_bidirectional(self, mapping):
        return False

    def feedback_value(self, mapping):
        return False
