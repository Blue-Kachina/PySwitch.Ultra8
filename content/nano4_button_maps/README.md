# nano4_button_maps/

This directory contains per-lane button configuration files for the NANO4 firmware.

## File Naming

Files are named `lane_N.json` where N is the lane number (1–8). Each file configures the four NANO4 buttons for that lane.

- `lane_1.json` — button config for lane 1 (Ultra8 lane 1)
- `lane_2.json` — button config for lane 2
- ...
- `lane_8.json` — button config for lane 8

## Format

Each file is a JSON object conforming to the shape defined in `docs/json_button_mapping_shape.md`. That document is the authoritative field reference.

## Per-Device Default Lane

`default_lane.txt` will specify which lane this physical device boots to.


## Deployment

These files are deployed to the NANO4 alongside the rest of `PySwitch/content/`. As of Phase 4 of the QoL roadmap, the firmware reads these files at boot to configure its button actions dynamically. Until Phase 4 is complete, these files are not read by the firmware and exist as the canonical definition of the intended configuration only.
