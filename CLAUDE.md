# Trimlight for Home Assistant: project notes

A custom Home Assistant integration (domain `trimlight`) that controls Trimlight permanent LED controllers over the LAN, with no cloud. It was built in the `HomePendant` repository (as `trimlight-ha/`) and moved here, with its history, on 2026-11-25 so it can be published through HACS.

Private, machine-specific details (Home Assistant host, SSH, controller addresses, working rules) are in `CLAUDE.local.md`, which is git-ignored. Read it too if it exists.

## Layout

- `custom_components/trimlight/`
  - `protocol.py`: the LAN protocol, with no Home Assistant code. It can be tested on its own and could become a PyPI library.
  - `coordinator.py`: `TrimlightCoordinator`, one per controller. It polls, caches patterns and schedules, and does the pattern edits.
  - `light.py`: `TrimlightLight` (a controller) and `TrimlightGroupLight` (a group), the entity services, and off timers.
  - `groups.py`: group helpers and pattern sync. It was named `group.py` until that clashed with Home Assistant's own `group` platform; don't rename it back.
  - `config_flow.py`: the menu (a controller or a group), subnet discovery, and the group options flow.
  - `const.py`, `services.yaml`, `strings.json`, `translations/en.json`, `manifest.json`.
- `blueprints/automation/trimlight/holiday_effect.yaml`: a pattern around a holiday, a date or a range of dates, every year.
- `tools/check.py`, `tools/watch.py`: developer scripts that talk to a controller directly. `watch.py` polls patterns to spot changes made in the Trimlight app.

## The protocol (what we've learned)

The base protocol is from msjarrett's reverse engineering: https://github.com/msjarrett/trimlight/blob/main/protocol/protocol.md

- TCP port 8189. A request is `0x5A, type, length (2 bytes, big-endian), payload, 0xA5`.
- Replies are `0x5A … 0xA5` with **no type byte**, so the code has to know what it asked. A reply can be one meant for an earlier request. `_check_reply` validates replies against the expected ID, and the coordinator rides out up to `MAX_MISSED_POLLS` (3) bad or missing polls before marking the light unavailable.
- Commands that change things get no reply.
- There is no discovery protocol. `discover()` probes port 8189 across the subnet of each of Home Assistant's own IPv4 adapters, as the Trimlight app does.
- **Pattern editing.** We worked these commands out by watching the Trimlight app's traffic; they aren't in msjarrett's document:
  - `0x04` deletes a pattern, `0x05` updates one, `0x06` creates one.
  - The payload is 58 bytes: id, a 25-byte name, category, mode/effect, speed, brightness, dots per colour and up to 7 colours (R, G, B).
  - Effect names are listed in `EFFECTS`; 9 is Wave Forward.
  - Built-in (preset) colour-wheel patterns can only have their name, speed and brightness changed.
- **There is no real "off".** A controller is either in manual mode (showing a pattern or colour) or in timer mode (following the schedules set in the Trimlight app). The light's `turn_off` sets timer mode, which hands the controller back to its schedules. Outside a schedule's hours the lights are dark; while a schedule is running they show its pattern. An earlier "Run schedule" switch was removed for this reason.
- Polling while the Trimlight app is connected can disrupt the app (it seems to allow one client at a time). Keep polling gentle: `POLL_INTERVAL` is 60 s, with patterns and schedules re-read every `LIBRARY_INTERVAL` (10 min).

## Design decisions

- **Groups** are a config entry of type `group` with member config entry IDs (`CONF_MEMBERS`). A group light controls all its members.
  - Its effects are the patterns every member has, matched by name, ignoring case.
  - **It keeps the members' patterns in sync.** A pattern one member has and another doesn't is copied over. This runs at Home Assistant start (`async_at_started`), every 60 s (`async_track_time_interval`; state-change events don't fire when a poll changes nothing, so a listener isn't enough), and just before the group turns on. `trimlight.sync_patterns` runs it on demand.
  - Patterns with the same name but different settings are left alone.
  - Deleting a pattern in the app only removes it from that controller, so the group copies it back. `trimlight.delete_pattern` on the group deletes it from all members.
- **Off timers** (`turn_off_in`, `turn_off_at`, `cancel_off_timer`) are kept by the light entity, show as its `off_at` attribute, and survive restarts (`RestoreEntity`). A timer that came due while Home Assistant was down runs when it's back.
- Pattern services take colours as names or hex codes and dots per colour as a list. Fields that are left out keep their current values (`PatternEdit`, `edited()`).

## Conventions

- **Blueprints hide inputs that don't apply** to the current choices, using `visible:` (field, operator, value). Every hidden input needs a `default`, and the logic must not depend on a hidden input's value. Don't add a toggle that hides fields existing automations already rely on. This is a standing preference for every blueprint.
- READMEs and UI strings use plain language aimed at the person using it, not developer jargon.
- After copying a blueprint into Home Assistant, call `automation.reload`; Home Assistant caches blueprints until then.

## Status and next steps (making it publishable)

Done:
- Moved to its own repository with `custom_components/trimlight/` at the top level, as HACS needs.
- `.gitignore`.

To do, roughly in order:
1. `hacs.json` at the top of the repository (name, minimum Home Assistant version).
2. `manifest.json`:
   - `documentation` should point at this repository (it still points at msjarrett's protocol notes).
   - Add `issue_tracker`, and `codeowners: ["@gremlin529"]`.
   - Keep `version` in step with GitHub releases.
3. A LICENSE file (MIT is likely), plus credit to msjarrett in the README.
4. **Stable identity.** The config entry's unique ID is currently the controller's IP address (`config_flow.py`, `async_set_unique_id(host)`), so a new DHCP address looks like a new device.
   - Switch to the MAC address, or another ID the controller reports, and update the host when it changes. DHCP discovery is optional.
   - **Existing entries must migrate without breaking entity IDs or automations.**
5. Make the blueprint generic:
   - The pattern drop-down lists one household's own patterns. Keep only the patterns the controllers ship with, and keep `custom_value: true`.
   - Add `source_url` for one-click import.
   - Check `min_version` (it's set to 2026.11.0, a guess).
6. Handle unknown hardware and firmware gracefully, and list the tested hardware in the README.
7. `diagnostics.py` (config entry diagnostics) for bug reports.
8. GitHub Actions: hassfest, HACS validation, and pytest with `pytest-homeassistant-custom-component` (protocol parsing and config flow).
9. A brand icon in `home-assistant/brands`, needed for the HACS default store.
10. A user-facing README: HACS install (custom repository button), manual install, setup, limitations, the blueprint.
11. `tools/`: replace the example IP addresses in the docstrings with generic ones, or move the scripts to `scripts/`.
12. GitHub releases (v0.1.0…), then a pull request to `hacs/default` if wanted.

Into Home Assistant itself (a separate, bigger step): `protocol.py` would become a PyPI library, the code would need near-complete tests and Home Assistant's quality-scale review, and the groups feature would probably be questioned, since Home Assistant has light groups.
