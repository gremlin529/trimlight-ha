# Trimlight for Home Assistant

A custom integration that controls [Trimlight](https://trimlight.com) permanent LED lights over your local network, with no cloud account and no app. It uses the controllers' own LAN protocol (TCP port 8189), as reverse-engineered in [msjarrett/trimlight](https://github.com/msjarrett/trimlight/blob/main/protocol/protocol.md).

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

- Its effects are the patterns every controller in it has, matched by name ignoring case. Picking one shows it on all of them.
- On, off (back to their schedules), brightness and colour go to all of them.
- It has its own off timers, and the pattern actions work on it too: saving a pattern on a group saves it on every controller, which is also how to give them all the same patterns.

The integration also keeps each controller's clock right (it's set every minute, as the app does on connecting), since the controller's schedules run on it.

## Limitations

- **The app and Home Assistant at once**: while the Trimlight app is connected, the controller drops or muddles other connections. The integration keeps its last reading through a few failed polls and throws away replies that don't match what it asked for, so the light doesn't flicker unavailable or show garbage.
- **No status feedback**: the controllers never say what they're showing. In manual mode the light shows what Home Assistant last sent; changes made in the Trimlight app won't show up. In schedule mode it works out what the schedules are showing from the schedules themselves.
- **No true off**: the controllers have no off command, only their schedules. To keep them dark, there must be no schedule covering now.
- **One controller model**: the protocol was worked out on one model (Select Plus), so some commands may differ on others.
- **Identified by IP address**: give each controller a fixed address (a DHCP reservation in your router) so it keeps the same one.

## Installing

1. **Copy the files:** copy the `custom_components/trimlight` folder into Home Assistant's `config/custom_components/` folder, so you end up with `config/custom_components/trimlight/manifest.json`. Any of these works:
   - **Samba share add-on:** connect to `smb://homeassistant.local/config` from Finder (Go → Connect to Server) and drag the folder in.
   - **Studio Code Server or File editor add-on:** create the folder and upload the files.
   - **SSH add-on:** `scp -r custom_components/trimlight root@homeassistant.local:/config/custom_components/`
2. **Restart Home Assistant:** Settings → System → Restart.
3. **Add it:** Settings → Devices & services → **Add integration** → search **Trimlight**. It searches the network for controllers (about 10 seconds) and lists the ones it finds; pick one, or type an IP address. Repeat for each controller.
4. **Optional, group:** add Trimlight again and choose **A group of controllers** to control several together.
5. **Optional, area:** put the devices in an area, e.g. Outside.

To update, copy the folder over again and restart.

## Checking a controller without Home Assistant

`tools/check.py` uses the same protocol code to read a controller: its name, mode, patterns and schedules, and what the schedules say should be on now.

```sh
python3 tools/check.py 192.168.0.114 192.168.0.142
python3 tools/check.py --discover <your computer's IP>
```

It only reads, apart from setting the controller's clock to now.
