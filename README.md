# Trimlight for Home Assistant

A custom integration that controls [Trimlight](https://trimlight.com) permanent LED lights over your local network, with no cloud account and no app. It uses the controllers' own LAN protocol (TCP port 8189), as reverse-engineered in [msjarrett/trimlight](https://github.com/msjarrett/trimlight/blob/main/protocol/protocol.md).

## What you get

Each controller becomes a device with:

- **A light**:
  - Turning it on or off.
  - Your saved patterns from the Trimlight app as its **effects** (Christmas, Halloween, warm white...).
  - **Brightness**.
  - A **solid colour**.
  - Turning it on with nothing chosen shows whatever the schedule would show, or the first pattern.
- **Run schedule** (a switch):
  - On hands the controller back to the schedules set in the Trimlight app (the controller's "timer" mode).
  - Off keeps it on whatever you last chose ("manual" mode).
  - Choosing a pattern, colour or off from Home Assistant switches it to manual, as the app does.
- **Off timers**, as actions on the light:
  - `trimlight.turn_off_in` (minutes) and `trimlight.turn_off_at` (a time of day; the next time it comes round).
  - `trimlight.cancel_off_timer`.
  - A pending timer shows as the light's `off_at` attribute and survives Home Assistant restarting. If it came due while Home Assistant was down, the light turns off when it's back.

The integration also keeps each controller's clock right (it's set every minute, as the app does on connecting), since the controller's schedules run on it.

## Limitations

- **No status feedback**: the controllers never say what they're showing. In manual mode the light shows what Home Assistant last sent; changes made in the Trimlight app won't show up. In schedule mode it works out what the schedules are showing from the schedules themselves.
- **Off is all black**: the protocol has no off command that anyone has found, so off sets every pixel to black.
- **One controller model**: the protocol was worked out on one model (Select Plus), so some commands may differ on others.
- **Identified by IP address**: give each controller a fixed address (a DHCP reservation in your router) so it keeps the same one.

## Installing

1. **Copy the files:** copy the `custom_components/trimlight` folder into Home Assistant's `config/custom_components/` folder, so you end up with `config/custom_components/trimlight/manifest.json`. Any of these works:
   - **Samba share add-on:** connect to `smb://homeassistant.local/config` from Finder (Go → Connect to Server) and drag the folder in.
   - **Studio Code Server or File editor add-on:** create the folder and upload the files.
   - **SSH add-on:** `scp -r custom_components/trimlight root@homeassistant.local:/config/custom_components/`
2. **Restart Home Assistant:** Settings → System → Restart.
3. **Add it:** Settings → Devices & services → **Add integration** → search **Trimlight**. It searches the network for controllers (about 10 seconds) and lists the ones it finds; pick one, or type an IP address. Repeat for each controller.
4. **Optional, area:** put the devices in an area, e.g. Outside.

To update, copy the folder over again and restart.

## Checking a controller without Home Assistant

`tools/check.py` uses the same protocol code to read a controller: its name, mode, patterns and schedules, and what the schedules say should be on now.

```sh
python3 tools/check.py 192.168.0.114 192.168.0.142
python3 tools/check.py --discover <your computer's IP>
```

It only reads, apart from setting the controller's clock to now.
