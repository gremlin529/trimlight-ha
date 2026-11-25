# Trimlight for Home Assistant

A custom Home Assistant integration that controls [Trimlight](https://trimlight.com) permanent mounted LED lights over your local network, with no cloud account and no app. It uses the controllers' own LAN protocol (TCP port 8189), as reverse-engineered in [msjarrett/trimlight](https://github.com/msjarrett/trimlight/blob/main/protocol/protocol.md).

**What are Trimlight lights?** Permanent LED strip lights mounted under eaves and rooflines, controlled by a local LAN device (the controller). They're often used for seasonal or holiday displays.

## What you get

Each controller becomes a device with:

- **A light**:
  - Turning it on, and off. **Off hands the controller back to its schedules** (the ones set in the Trimlight app), since that's the controllers' only off: outside a schedule's hours they're dark, and while one is running the light shows that pattern and stays on.
  - Your saved patterns from the Trimlight app as its **effects** (Christmas, Halloween, warm white...).
  - **Brightness**.
  - A **solid colour**.
  - Turning it on with nothing chosen shows whatever the schedule would show, or the first pattern.
  - Choosing a pattern or colour switches the controller to manual, as the app does, until it's turned off.
- **Pattern editing**, as actions on the light (Developer tools → Actions, or in scripts and automations):
  - `trimlight.save_pattern`: changes the saved pattern with that name, or creates it if there isn't one. Settings: effect (Static, Chase Forward, Wave Forward...), speed and brightness (0–100), colours (1–7, in order, as names like `red` or codes like `#ff0078`) and dots per colour (e.g. `[2, 1, 1]`). Settings you leave out stay as they are.
  - `trimlight.rename_pattern`, `trimlight.delete_pattern`.
  - `trimlight.copy_pattern`: copies a pattern from another Trimlight light, over any pattern of the same name.
  - `trimlight.preview_pattern`: shows a pattern without saving it, to try settings out first.
  - The light's `pattern` attribute shows the current pattern's settings in the same terms, so it's easy to start from what's there.
  - Built-in colour wheel patterns can only have their name, speed and brightness changed.
- **Off timers**, as actions on the light:
  - `trimlight.turn_off_in` (minutes) and `trimlight.turn_off_at` (a time of day; the next time it comes round). Both mean back to the schedule.
  - `trimlight.cancel_off_timer`.
  - A pending timer shows as the light's `off_at` attribute and survives Home Assistant restarting. If it came due while Home Assistant was down, the light turns off when it's back.

## Groups

Controllers in the same space (front and back of the house, say) can be put in a **group**, which is one light that controls them all together. Add one with **Add integration → Trimlight → A group of controllers** (offered once there are two controllers), give it a name and pick the controllers; change them later with **Configure**.

- **It keeps the controllers' patterns the same.** Any pattern one controller has and another doesn't (matched by name, ignoring case) is copied to the others. This happens when the group starts, within about a minute of a pattern being made in the Trimlight app (each controller is read every minute), and just before the group is turned on. `trimlight.sync_patterns` does it on demand. Where two controllers have a pattern with the same name but different settings, each keeps its own. Deleting a pattern in the app only removes it from that controller, so the group puts it back; use `trimlight.delete_pattern` on the group to delete it from all of them.
- Its effects are the patterns every controller in it has. Picking one shows it on all of them.
- On, off (back to their schedules), brightness and colour go to all of them.
- It has its own off timers, and the pattern actions work on it too: saving a pattern on a group saves it on every controller, which is also how to give them all the same patterns.

## Blueprint: a pattern around a date or holiday

`blueprints/automation/trimlight/holiday_effect.yaml` shows a pattern each evening around a date or a holiday, and turns the lights off again afterwards (back to their own schedules). It repeats every year. To use it, copy it to `config/blueprints/automation/trimlight/` and create an automation from it under **Settings → Automations → Blueprints**.

- **Around:** a holiday or a date (only the month and day count), each with days before and after; or **a range of dates** (from and until, both included, repeating every year, and able to cross New Year, e.g. 15 Dec to 5 Jan).
- **Holidays:** New Year's Day and Eve, Valentine's, St. Patrick's, Easter, Mother's and Father's Day, Memorial Day, Canada Day, Independence Day, Labor Day, Thanksgiving (US and Canada), Halloween, Veterans/Remembrance Day and Christmas. Easter and the "nth weekday" holidays are worked out for each year. Diwali and Lunar New Year follow the moon, so they come from a table that runs to 2030.
- **Days before and after:** how many days either side of the holiday or date it runs. A window can cross New Year.
- **On:** at a time, or at sunset or sunrise with an offset (e.g. -00:15 for 15 minutes before sunset). **Off:** the same choices. An off the next morning (at sunrise, or at a time earlier than the on time) counts with the evening before.
- **Pattern:** pick from the list of the trim lights' patterns (as of when the blueprint was written), or type the name of a newer one.

The integration also keeps each controller's clock right (it's set every minute, as the app does on connecting), since the controller's schedules run on it.

## Limitations

- **The app and Home Assistant at once**: while the Trimlight app is connected, the controller drops or muddles other connections. The integration keeps its last reading through a few failed polls and throws away replies that don't match what it asked for, so the light doesn't flicker unavailable or show garbage.
- **No status feedback**: the controllers never say what they're showing. In manual mode the light shows what Home Assistant last sent; changes made in the Trimlight app won't show up. In schedule mode it works out what the schedules are showing from the schedules themselves.
- **No true off**: the controllers have no off command, only their schedules. To keep them dark, there must be no schedule covering now.
- **One controller model tested**: the protocol was reverse-engineered on Select Plus. Other models may work but haven't been tested; report issues if yours differs.
- **Identified by IP address** (for now): give each controller a fixed address (a DHCP reservation in your router) so it keeps the same one. Future versions will use MAC address for stability.

## Installing

### Quick Start (Most Users)

1. **Via HACS** (recommended):
   - Open HACS → Integrations
   - Add this repository as a custom repository: `https://github.com/gremlin529/trimlight-ha`
   - Search for **Trimlight** and click Install
   - Restart Home Assistant

2. **Or Manual**:
   - Copy `custom_components/trimlight` to `config/custom_components/` on your Home Assistant instance
   - Restart Home Assistant

3. **Add a controller**:
   - Settings → Devices & services → **Add integration** → search **Trimlight**
   - The integration scans your network for controllers (~10 seconds)
   - Pick a controller from the list, or enter its IP address manually if not found
   - Repeat for each controller

4. **Optional—Group controllers together**:
   - Settings → Devices & services → **Add integration** → **Trimlight** → **A group of controllers**
   - Give it a name and select which controllers to include
   - Groups keep all members' patterns in sync and control them together

### Manual Setup (Advanced)

If auto-discovery doesn't find your controller:
- Find your controller's IP address (Trimlight app → Settings, or check your router's DHCP list)
- Ensure it's on the same network as Home Assistant
- When adding the integration, enter the IP manually

### Setup Requirements

- **Home Assistant 2026.11.0** or later
- **Local network access** to your Trimlight controller (TCP port 8189)
- **Fixed IP address** (or DHCP reservation) for each controller to keep them stable across restarts
- Trimlight controller with LAN protocol support (tested on Select Plus)

## Discovery & Auto-Detection

The integration automatically discovers Trimlight controllers on your network by:
- Scanning your Home Assistant's network subnets on port 8189 (the same method the Trimlight app uses)
- Presenting any found controllers to you during setup

This requires both devices to be on the same local network; if discovery doesn't find your controller, manually enter its IP address instead.

## Updating

- **HACS**: integrations with new versions show an update button
- **Manual**: copy the folder over again and restart Home Assistant

## Troubleshooting

### Controller not found during discovery
- Check that the controller is powered on and connected to your network
- Verify it's on the same network as Home Assistant (not a guest/isolated VLAN)
- Try entering the IP address manually in the integration setup form
- Use `tools/check.py` to verify the controller responds on its IP

### Light shows unavailable
- Check the controller is reachable: `ping <controller-ip>`
- Verify Home Assistant can reach TCP port 8189 on the controller
- If the Trimlight app is connected, it may be blocking the integration; disconnect the app
- Restart the integration: Settings → Devices & services → Trimlight → Reload

### Patterns not syncing in a group
- Ensure all controllers in the group have network connectivity
- Trigger a manual sync: Call `trimlight.sync_patterns` on the group light
- Check the group's `pattern` attribute for details

## Credits

- **Protocol reverse-engineering**: [@msjarrett](https://github.com/msjarrett)
- **Integration**: [@gremlin529](https://github.com/gremlin529)

## License

MIT License. See [LICENSE](/LICENSE) for details.

---

## For Developers

### Protocol Testing

The `tools/check.py` script talks to a controller directly (without Home Assistant):

```bash
python3 tools/check.py 192.168.1.100
python3 tools/check.py --discover 192.168.1.5
```

This is useful for:
- Verifying a controller is reachable
- Checking its current mode, patterns, and schedules
- Debugging protocol issues
- Testing changes to `protocol.py` in isolation

The `tools/watch.py` script monitors a controller for pattern changes made in the Trimlight app:

```bash
python3 tools/watch.py 192.168.1.100
```

### Code Structure

- **`protocol.py`**: LAN protocol implementation (no Home Assistant dependencies). Can be tested independently.
- **`coordinator.py`**: `TrimlightCoordinator` handles polling, caching, and pattern edits for one controller.
- **`light.py`**: `TrimlightLight` and `TrimlightGroupLight` entity implementations, service actions, and off timers.
- **`groups.py`**: Group helpers and pattern synchronization across controllers.
- **`config_flow.py`**: Setup flow, discovery, and group options.
- **`__init__.py`**: Integration initialization and coordinator setup.

### Contributing

Found a bug or want to add a feature? Please open an issue or pull request on [GitHub](https://github.com/gremlin529/trimlight-ha/issues).

**Testing hardware/firmware**: please report what controller model and firmware version you're using if you encounter issues.

`tools/check.py` uses the same protocol code to read a controller: its name, mode, patterns and schedules, and what the schedules say should be on now.

```sh
python3 tools/check.py 192.168.0.114 192.168.0.142
python3 tools/check.py --discover <your computer's IP>
```

It only reads, apart from setting the controller's clock to now.
