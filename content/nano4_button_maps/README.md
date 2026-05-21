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

Buttons with `"dynamic": true` may also carry a `"function"` string key naming
the `leds.json` function they control (e.g. `"function": "REC_PLY"`). When
present, the firmware binds the LED function at `init()` time without waiting
for a SysEx assignment message. This eliminates the ~1-second boot delay before
the first LED press feedback.

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
