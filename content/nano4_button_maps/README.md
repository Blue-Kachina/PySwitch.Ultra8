# nano4_button_maps/

This directory contains per-lane button configuration files and the LED state
definition file for the NANO4 firmware.

## Files

| File | Purpose |
|---|---|
| `lane_N.json` | Button config for lane N (1–8). Four buttons, all gestures. |
| `leds.json` | LED state definitions for all dynamic button functions. |
| `default_lane.txt` | Single integer (1–8) — which lane this device boots to. |

## lane_N.json Format

Each file is a JSON object conforming to the shape defined in
`docs/json_button_mapping_shape.md`. That document is the authoritative field
reference.

### The `function` key

Every button that drives a dynamic LED carries a `"function"` string at the
button level, naming the `leds.json` function it controls
(e.g. `"function": "REC_PLY"`). The firmware binds this function at `init()`
time, so the button shows its default state color immediately on boot — there is
no delay waiting for a SysEx assignment message.

`color`, `led_brightness`, and `dynamic` keys do not appear on function buttons.
All color and brightness information for function-bound buttons is defined
exclusively in `leds.json` states. These three fields are only valid on
non-function buttons (buttons with no `"function"` key) and are not used in the
current deployed configuration.

### The `default` state in `leds.json`

Each function entry in `leds.json` has a `"default"` key naming the LED state
the firmware should show at cold boot, before any SysEx snapshot has arrived
from Ultra8. It must match one of the state names defined in that function's
`"states"` dict.

For example, `"REC_PLY"` defaults to `"empty"` (the lane contains no audio),
and `"UNDO_REDO"` defaults to `"unavailable"` (nothing to undo). This means
all four buttons light up in their correct idle colors the moment the NANO4
boots, with no waiting for Ultra8 to respond.

When Ultra8 starts sending snapshots, `reconcile_snapshot()` runs on each
accepted snapshot and corrects any button whose predicted state diverges from
the authoritative Ultra8 state, typically within one heartbeat period (~1 s).

## leds.json

Defines LED colors, brightness levels, and corner labels for every named state
of every dynamic button function. Structure:

```json
{
  "functions": {
    "FUNCTION_NAME": {
      "description": "...",
      "default": "state_name",
      "states": {
        "state_name": { "color": "COLOR_NAME", "brightness": 0.0–1.0, "label": "TEXT or null" },
        ...
      }
    }
  }
}
```

The `"default"` key names the state the firmware should display at boot, before
any SysEx snapshot has arrived from Ultra8. It must be one of the state names
defined in that function's `"states"` dict.

## Per-Device Default Lane

`default_lane.txt` contains a single integer (1–8) specifying which Ultra8 lane
this physical device controls. It is the only file that differs between units.
See `docs/deploy_multiple_nano4.md` for the full multi-device deployment guide.

## Deployment

All files in this directory are deployed to the NANO4 alongside the rest of
`PySwitch/content/`. The firmware reads `lane_N.json`, `leds.json`, and
`default_lane.txt` at boot.
