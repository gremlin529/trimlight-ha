"""Reads a Trimlight controller with the integration's protocol code, without
Home Assistant. Read-only, apart from Check Device setting the controller's
clock to now (the Trimlight app does the same on every connection).

    python3 tools/check.py 192.168.0.114 [more hosts]
    python3 tools/check.py --discover 192.168.0.50   # your own IP
"""

import asyncio
import importlib.util
import pathlib
import sys
from datetime import datetime

spec = importlib.util.spec_from_file_location(
    "protocol", pathlib.Path(__file__).parent.parent / "custom_components/trimlight/protocol.py"
)
p = importlib.util.module_from_spec(spec)
sys.modules["protocol"] = p
spec.loader.exec_module(p)


async def show(host: str) -> None:
    t = p.Trimlight(host)
    info = await t.device_info()
    print(f"{host}: '{info.name}', mode {'timer' if info.mode == p.MODE_TIMER else 'manual'}, "
          f"{info.pixels} pixels, IC {info.ic}, order {info.rgb_order}")
    detail = await t.detail()
    patterns = await t.patterns(detail.pattern_ids)
    schedules = await t.schedules(detail.schedule_ids)
    print(f"  {len(patterns)} patterns, {len(schedules)} dated schedules")
    for d in detail.daily:
        print(f"  daily {d.slot}: {'on' if d.enabled else 'off'} pattern {d.pattern_id} "
              f"{d.start:%H:%M}-{d.end:%H:%M} rep {d.repetition}")
    names = {x.id: x.name for x in patterns}
    for s in schedules:
        print(f"  schedule {s.id}: {names.get(s.pattern_id, s.pattern_id)} "
              f"{s.start_month}/{s.start_day}-{s.end_month}/{s.end_day} {s.start:%H:%M}-{s.end:%H:%M}")
    now = datetime.now()
    pid = p.scheduled_pattern(now, detail, schedules)
    print(f"  schedules say at {now:%m/%d %H:%M}: {names.get(pid, 'off') if pid else 'off'}")


async def main(args: list[str]) -> None:
    if args and args[0] == "--discover":
        print("found:", await p.discover(args[1]))
        return
    for host in args:
        await show(host)


asyncio.run(main(sys.argv[1:]))
