##############################################################################
#
# Ultra8 PySwitch — Per-lane JSON button mapping reader (QoL Phase 4 Unit 4.1)
#
# Reads per-lane JSON button mapping files from nano4_button_maps/ and
# provides accessors for the rest of the firmware.
#
# File locations (relative to CIRCUITPY root):
#   nano4_button_maps/lane_1.json  …  nano4_button_maps/lane_8.json
#   nano4_button_maps/leds.json
#   nano4_button_maps/default_lane.txt
#
# Public API:
#
#   load_default_lane() -> int
#       Read the active lane number (1-indexed, 1–8) from
#       nano4_button_maps/default_lane.txt.
#       Fallback: if the file is missing, empty, or out-of-range, scan
#       nano4_button_maps/ for the lowest-numbered lane_<n>.json and use
#       that lane.  Hard fallback to 1 if no lane files exist.
#       All fallbacks are logged to the serial console.
#
#   load_lane_config(lane_number) -> dict | None
#       Read and parse the JSON config for lane N (1-indexed).
#       Returns None on file-not-found or JSON error; logs to serial.
#
#   get_gesture(config, button, gesture) -> dict
#       Resolve the full action dict for (button, gesture) by merging
#       global-level defaults.  Returns {} if absent.
#       Keys in result: type, index, channel, value,
#                       label, color, led_brightness, dynamic
#
#   load_dynamic_leds() -> dict
#       Read and parse leds.json.  Returns nested dict:
#           {function_name: {"default": str, "states": {state_name: {"color": str, "brightness": float, "label": str|None}}}}
#       Cached after first load.  Returns {} on error; logs to serial.
#
#   get_led_default(dynamic_leds, function_name) -> str | None
#       Return the "default" state name for a function, or None if absent.
#
#   resolve_color(name) -> color tuple
#       Convert a color-name string (e.g. "RED") to a Colors tuple.
#       Falls back to Colors.WHITE for unknown names.
#
##############################################################################

import json

# Path prefix — relative to CIRCUITPY root (/nano4_button_maps/ on device)
_BUTTON_MAP_PATH = "nano4_button_maps"

# Module-level cache for dynamic_leds — loaded at most once per boot
_dynamic_leds_cache  = None
_dynamic_leds_loaded = False


# ── Default lane loader ────────────────────────────────────────────────────────

def load_default_lane():
    """Read the device's default lane number from default_lane.txt (1-indexed).

    Format: a single line containing one integer in the range 1–8.

    Fallback chain (each step is logged to the serial console):
      1. File missing or unreadable → scan nano4_button_maps/ for the
         lowest-numbered lane_<n>.json and use that N.
      2. File present but content is empty, non-integer, or out of range →
         same scan fallback.
      3. No lane_<n>.json files found → hard fallback: lane 1.

    Returns an int in the range 1–8.
    """
    path = "{}/default_lane.txt".format(_BUTTON_MAP_PATH)
    raw = None

    try:
        with open(path) as fh:
            raw = fh.read().strip()
    except OSError as exc:
        print("lane_config: cannot open", path, ":", exc)

    if raw is not None:
        try:
            lane = int(raw)
            if 1 <= lane <= 8:
                return lane
            print("lane_config: default_lane.txt value out of range:", lane)
        except (ValueError, TypeError):
            print("lane_config: default_lane.txt is not a valid integer:", repr(raw))

    # Fallback: scan for the lowest-numbered lane JSON
    return _fallback_lane()


def _fallback_lane():
    """Scan nano4_button_maps/ for lane_<n>.json files, return lowest n found.

    Hard-falls back to lane 1 if no lane files are present.
    """
    import os
    lowest = None
    try:
        entries = os.listdir(_BUTTON_MAP_PATH)
        for name in entries:
            if name.startswith("lane_") and name.endswith(".json"):
                try:
                    n = int(name[5:-5])   # strip "lane_" prefix and ".json" suffix
                    if 1 <= n <= 8:
                        if lowest is None or n < lowest:
                            lowest = n
                except ValueError:
                    pass
    except OSError as exc:
        print("lane_config: cannot list", _BUTTON_MAP_PATH, ":", exc)

    if lowest is not None:
        print("lane_config: using fallback lane", lowest, "from scan")
        return lowest

    print("lane_config: no lane files found; defaulting to lane 1")
    return 1


# ── Config loading ─────────────────────────────────────────────────────────────

def load_lane_config(lane_number):
    """Load and parse the JSON button mapping for the given lane (1-indexed).

    Returns a dict on success.  On file-not-found or JSON parse error, logs
    a message to the serial console and returns None.  Callers treat None as
    "use safe defaults; do not crash".
    """
    path = "{}/lane_{}.json".format(_BUTTON_MAP_PATH, lane_number)
    try:
        with open(path) as fh:
            return json.load(fh)
    except OSError as exc:
        print("lane_config: cannot open", path, ":", exc)
        return None
    except ValueError as exc:
        print("lane_config: JSON parse error in", path, ":", exc)
        return None


# ── Dynamic LED loader ─────────────────────────────────────────────────────────

def load_dynamic_leds():
    """Load and parse leds.json.

    Returns a nested dict keyed by function name → {"default": str, "states": {...}}.
    The "states" sub-dict maps state_name → {"color": str, "brightness": float, "label": str|None}.
    Uses a module-level cache so the file is read at most once per boot.
    Returns {} on error; logs to serial.

    Example result structure:
        {
            "REC_PLY": {
                "default": "empty",
                "states": {
                    "recording": {"color": "RED",          "brightness": 0.5, "label": "PLAY"},
                    "empty":     {"color": "RED",          "brightness": 0.05, "label": "REC"},
                    ...
                }
            },
            ...
        }

    Callers look up state entries as:
        dynamic_leds[function_name]["states"][state_name]
    """
    global _dynamic_leds_cache, _dynamic_leds_loaded
    if _dynamic_leds_loaded:
        return _dynamic_leds_cache if _dynamic_leds_cache is not None else {}

    path = "{}/leds.json".format(_BUTTON_MAP_PATH)
    # Set flag first so repeated calls never retry a missing file
    _dynamic_leds_loaded = True
    try:
        with open(path) as fh:
            data = json.load(fh)
            raw = data.get("functions", {})
            # Preserve the full per-function dict (includes "default" and "states")
            _dynamic_leds_cache = {
                fn_name: {
                    "default": fn_data.get("default"),
                    "states":  fn_data.get("states", {}),
                }
                for fn_name, fn_data in raw.items()
            }
    except OSError as exc:
        print("lane_config: cannot open", path, ":", exc)
        _dynamic_leds_cache = {}
    except ValueError as exc:
        print("lane_config: JSON parse error in", path, ":", exc)
        _dynamic_leds_cache = {}

    return _dynamic_leds_cache if _dynamic_leds_cache is not None else {}


def get_led_default(dynamic_leds, function_name):
    """Return the default state name for a function, or None if absent.

    Args:
        dynamic_leds:  the dict returned by load_dynamic_leds()
        function_name: e.g. "REC_PLY"

    Returns:
        A string naming the boot state (e.g. "empty"), or None if the
        function is missing or has no "default" key.
    """
    fn_data = dynamic_leds.get(function_name)
    if fn_data is None:
        return None
    return fn_data.get("default")


# ── Gesture resolver ───────────────────────────────────────────────────────────

def get_gesture(config, button, gesture):
    """Return the fully-resolved action dict for (button, gesture).

    Merges global-level defaults so callers always receive a complete dict.

    Channel precedence:
        gesture-level channel > button-level channel > global.channel > None

    Returned keys:
        type           — "cc", "note", "pc", or "internal"
        index          — int (CC/note/PC number) or str ("next_lane", "prev_lane")
        channel        — int or None (None = derive from page_state at press time)
        value          — int (MIDI value to send; default 127)
        label          — str or None (button-level label field)
        color          — str  (color name; default "WHITE")
        led_brightness — float (0.0–1.0; default 0.15)
        dynamic        — bool (True = drive LED from leds.json)
        function       — str or None (leds.json function name for this button,
                          e.g. "REC_PLY"; None for buttons without a function key)

    Returns {} if config is None or the button / gesture is not present.
    """
    if config is None:
        return {}

    global_cfg  = config.get("global",  {})
    button_cfg  = config.get("buttons", {}).get(button, {})
    gesture_cfg = button_cfg.get(gesture, {})

    if not gesture_cfg:
        return {}

    # Channel: three-level precedence as defined in the JSON spec
    channel = gesture_cfg.get(
        "channel",
        button_cfg.get("channel", global_cfg.get("channel", None))
    )

    return {
        "type":           gesture_cfg.get("type",  "cc"),
        "index":          gesture_cfg.get("index", None),
        "channel":        channel,
        "value":          gesture_cfg.get("value", global_cfg.get("value", 127)),
        "label":          button_cfg.get("label",  None),
        "color":          button_cfg.get("color",  "WHITE"),
        "led_brightness": button_cfg.get("led_brightness", 0.15),
        "dynamic":        button_cfg.get("dynamic", False),
        "function":       button_cfg.get("function", None),
    }


# ── Color helper ───────────────────────────────────────────────────────────────

def resolve_color(name):
    """Convert a color-name string (e.g. "RED") to a Colors tuple.

    Performs a getattr lookup on pyswitch.colors.Colors.
    Falls back to Colors.WHITE for unknown or None names.
    """
    from pyswitch.colors import Colors
    if name is None:
        return Colors.WHITE
    return getattr(Colors, name, Colors.WHITE)
