##############################################################################
#
# Ultra8 PySwitch — Bidirectional protocol — SysEx parser.
#
# Unit 3.6: Full v0.1 SysEx state snapshot parser
# Unit 6.4: Extended to handle v0.1 assignment messages (msg_type 0x02)
#
#   Routes incoming SysEx by msg_type byte (data[1]):
#     0x01 — state snapshot  → _receive_snapshot(); updates self.snapshot
#     0x02 — assignment msg  → _receive_assign();   updates assignments.py
#
#   Both message types share manufacturer_id (0x7D) and protocol_id (0x55).
#   An unknown msg_type is recognised as ours but silently ignored so old
#   firmware gracefully discards future message types.
#
# State snapshot validation rules (docs/protocol_sysex_v0_1.md):
#   1. manufacturer_id  == bytes([0x7D])
#   2. data[0]          == 0x55            (protocol ID)
#   3. data[1]          == 0x01            (msg_type: state snapshot)
#   4. len(data)        == 30              (total packet 33 bytes)
#   5. (data[6 + N*3] & 0x07) == N  for N in 0–7 (lane_info bits 2:0 sanity)
#   6. seq != last accepted snapshot seq   (duplicate suppression)
#
# Assignment message validation rules (docs/protocol_assignment_metadata_v0_1.md):
#   1. manufacturer_id  == bytes([0x7D])
#   2. data[0]          == 0x55            (protocol ID)
#   3. data[1]          == 0x02            (msg_type: assignment)
#   4. len(data)        == 23              (total packet 26 bytes, 6 controls)
#   5. seq != last accepted assignment seq (duplicate suppression)
#   6. data[4]          == 6               (num_controls; must be 6)
#   Any failure → silently discard; last accepted state is retained.
#
##############################################################################

from adafruit_midi.system_exclusive import SystemExclusive
from ...misc import get_current_millis
from . import assignments

# ── v0.1 protocol constants ────────────────────────────────────────────────
_MANUFACTURER_ID    = bytes([0x7D])   # MIDI non-commercial / educational
_PROTOCOL_ID        = 0x55            # Ultra8 NANO4 protocol identifier
_MSG_TYPE_SNAPSHOT  = 0x01            # State snapshot (Unit 3.6)
_MSG_TYPE_ASSIGN    = 0x02            # Assignment message (Unit 6.4)

# Expected data lengths (= total packet bytes − 3 framing bytes: F0 mfr F7)
_SNAPSHOT_DATA_LEN  = 30              # 33-byte packet
_ASSIGN_DATA_LEN    = 23              # 26-byte packet (6 controls)

_NUM_LANES          = 8

# Lane state enum — matches Ultra8 encoder and protocol spec
STATE_STOPPED     = 0
STATE_PLAYING     = 1
STATE_RECORDING   = 2    # first-pass record (g_firstrec > 0)
STATE_OVERDUBBING = 3    # overdub on existing loop


# ── Data classes ───────────────────────────────────────────────────────────

class _LaneBlock:
    """Parsed lane data from one 3-byte lane block.

    lane_info byte layout (byte +0 of each block):
      bits 2:0  lane_index      — sanity check, must equal block position N
      bits 4:3  undo_redo_state — 0=none, 1=undo available, 2=redo available
      bits 6:5  reserved

    lane_flags byte layout (byte +1 of each block):
      bits 1:0  state           — lane state enum (0=stopped 1=playing 2=recording 3=overdubbing)
      bit  2    dirty           — 1 = lane has recorded audio
      bit  3    selected        — 1 = this is the selected lane
      bits 5:4  reserved (monmode removed)
      bit  6    reverse         — 1 = loop is currently playing in reverse (rev_active)
      bit  7    always 0 (7-bit MIDI safety)
    """

    __slots__ = ("lane_index", "state", "dirty", "selected",
                 "reverse", "undo_redo_state", "loop_phase")

    def __init__(self, lane_info, flags, loop_phase):
        self.lane_index      = lane_info & 0x07
        self.undo_redo_state = (lane_info >> 3) & 0x03   # 0=none 1=undo 2=redo
        self.state           =  flags           & 0x03
        self.dirty           = (flags >> 2)     & 0x01
        self.selected        = (flags >> 3)     & 0x01
        self.reverse         = (flags >> 6)     & 0x01   # rev_active: 0=forward 1=reversed
        self.loop_phase      = loop_phase

    def __repr__(self):
        return (
            "_LaneBlock(lane={} state={} dirty={} sel={} rev={} undo_redo={} phase={})".format(
                self.lane_index, self.state, self.dirty,
                self.selected, self.reverse, self.undo_redo_state, self.loop_phase
            )
        )


class _Snapshot:
    """Fully parsed v0.1 SysEx state snapshot."""

    __slots__ = ("seq", "any_active", "chan_selected", "lanes")

    def __init__(self, seq, global_flags, chan_selected, lanes):
        self.seq           = seq
        self.any_active    = global_flags & 0x01
        self.chan_selected = chan_selected   # 0–7, or 0x7F = no selection
        self.lanes         = lanes          # list of 8 _LaneBlock


# ── Protocol class ─────────────────────────────────────────────────────────

class Ultra8Protocol:
    """
    Ultra8 bidirectional protocol — v0.1 SysEx parser.

    Required interface for BidirectionalClient:
      init(midi, client)        – called once on startup
      receive(midi_message)     – called for unhandled incoming messages
      update()                  – called periodically
      is_bidirectional(mapping) – True if a mapping should skip polling
      feedback_value(mapping)   – True if a set() should echo back to listeners

    Public state (read by lane_state.py):
      self.snapshot          – last valid _Snapshot, or None
      self.last_feedback_ms  – get_current_millis() timestamp of last accepted
                               state snapshot, or None if none received yet
    """

    def __init__(self):
        self.debug             = False       # set externally by BidirectionalClient
        self.snapshot          = None        # last valid _Snapshot
        self.last_feedback_ms  = None        # ms timestamp of last accepted snapshot
        self._last_seq         = None        # seq of last accepted state snapshot
        self._last_assign_seq  = None        # seq of last accepted assignment message

    # ── BidirectionalClient interface ──────────────────────────────────────

    def init(self, midi, client):
        self._midi   = midi
        self._client = client

        # No listener registrations — incoming SysEx flows to receive() automatically.
        # Incoming SysEx is not claimed by any ClientParameterMapping, so it
        # falls through to receive() automatically.

    def receive(self, midi_message):
        """Route an incoming SysEx packet to the appropriate handler.

        Returns True if the message was recognised as an Ultra8 SysEx packet
        (valid, duplicate, or unknown msg_type within our protocol namespace),
        False for unrelated SysEx.
        """
        if not isinstance(midi_message, SystemExclusive):
            return False

        # ── Validation: manufacturer ID ───────────────────────────────────
        if midi_message.manufacturer_id != _MANUFACTURER_ID:
            return False

        data = midi_message.data

        # ── Validation: minimum length + protocol ID ──────────────────────
        if len(data) < 2 or data[0] != _PROTOCOL_ID:
            return False

        # ── Route by message type ─────────────────────────────────────────
        msg_type = data[1]

        if msg_type == _MSG_TYPE_SNAPSHOT:
            return self._receive_snapshot(data)

        if msg_type == _MSG_TYPE_ASSIGN:
            return self._receive_assign(data)

        # Unknown msg_type: recognised as ours (don't pass to other handlers)
        # but silently ignored (forward-compatibility with future message types).
        if self.debug:
            print("U8 proto: unknown msg_type", hex(msg_type), "— ignored")
        return True

    def update(self):
        """Periodic protocol maintenance — nothing needed in v0.1."""
        pass

    def is_bidirectional(self, mapping):
        return False

    def feedback_value(self, mapping):
        return False

    # ── Private: state snapshot parser ────────────────────────────────────

    def _receive_snapshot(self, data):
        """Parse and store a v0.1 state snapshot (msg_type 0x01)."""

        # ── Length check ──────────────────────────────────────────────────
        if len(data) != _SNAPSHOT_DATA_LEN:
            if self.debug:
                print("U8 proto [snap]: bad length", len(data),
                      "(expected", _SNAPSHOT_DATA_LEN, ")")
            return False

        # ── Sequence number ───────────────────────────────────────────────
        seq = data[2] | (data[3] << 7)

        # ── Duplicate suppression ─────────────────────────────────────────
        if seq == self._last_seq:
            if self.debug:
                print("U8 proto [snap]: duplicate seq", seq, "— discarded")
            return True

        # ── Lane-index sanity for all 8 blocks ────────────────────────────
        # bits 4:3 of each lane_info byte carry undo_redo_state — mask to low 3 bits
        for n in range(_NUM_LANES):
            if (data[6 + n * 3] & 0x07) != n:
                if self.debug:
                    print("U8 proto [snap]: lane_index mismatch at block", n,
                          "got", data[6 + n * 3] & 0x07)
                return False

        # ── Extract global fields ─────────────────────────────────────────
        global_flags  = data[4]
        chan_selected  = data[5]

        # ── Parse lane blocks ─────────────────────────────────────────────
        lanes = []
        for n in range(_NUM_LANES):
            base = 6 + n * 3
            lanes.append(_LaneBlock(
                lane_info  = data[base],       # bits 2:0 = index, bits 4:3 = undo_redo_state
                flags      = data[base + 1],
                loop_phase = data[base + 2],
            ))

        # ── Accept snapshot ───────────────────────────────────────────────
        self.snapshot         = _Snapshot(seq, global_flags, chan_selected, lanes)
        self._last_seq        = seq
        self.last_feedback_ms = get_current_millis()

        if self.debug:
            print("U8 proto [snap]: accepted seq={} any_active={} chan_sel={}".format(
                seq,
                self.snapshot.any_active,
                chan_selected if chan_selected != 0x7F else "none",
            ))

        # Push authoritative state to all registered lane action callbacks.
        # Lazy import avoids circular dependency; page_state gives the active lane.
        try:
            from .actions.lane_action import reconcile_snapshot
            from . import page_state
            lane_index = page_state.get() - 1
            reconcile_snapshot(self.snapshot, lane_index)
        except Exception as exc:
            if self.debug:
                print("U8 proto [snap]: reconcile error:", exc)

        return True

    # ── Private: assignment message parser ────────────────────────────────

    def _receive_assign(self, data):
        """Parse a v0.1 assignment message (msg_type 0x02) and update
        the shared assignments store.
        """

        # ── Length check ──────────────────────────────────────────────────
        if len(data) != _ASSIGN_DATA_LEN:
            if self.debug:
                print("U8 proto [assign]: bad length", len(data),
                      "(expected", _ASSIGN_DATA_LEN, ")")
            return False

        # ── Sequence number ───────────────────────────────────────────────
        seq = data[2] | (data[3] << 7)

        # ── Duplicate suppression ─────────────────────────────────────────
        if seq == self._last_assign_seq:
            if self.debug:
                print("U8 proto [assign]: duplicate seq", seq, "— discarded")
            return True

        # ── num_controls validation ───────────────────────────────────────
        num_controls = data[4]
        if num_controls != 6:
            if self.debug:
                print("U8 proto [assign]: unexpected num_controls", num_controls)
            return False

        # ── Parse control blocks ──────────────────────────────────────────
        # Each block is 3 bytes: [control_id, msg_type_byte, msg_number]
        for i in range(num_controls):
            base       = 5 + i * 3
            control_id = data[base]
            msg_type   = data[base + 1]
            msg_number = data[base + 2]
            assignments.update(control_id, msg_type, msg_number)

        # ── Accept ────────────────────────────────────────────────────────
        self._last_assign_seq = seq

        if self.debug:
            print("U8 proto [assign]: accepted seq={} controls={}".format(
                seq, num_controls
            ))

        return True
