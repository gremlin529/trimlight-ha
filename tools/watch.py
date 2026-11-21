"""Watches Trimlight controllers' saved patterns and schedules, and prints
what changes (added, removed or edited), with every field and the raw colour
bytes. For working out the protocol while editing in the Trimlight app.
Read-only.

    python3 tools/watch.py 192.168.0.114 192.168.0.142 [--every 15]
"""

import argparse
import asyncio
import importlib.util
import pathlib
import sys
import time

spec = importlib.util.spec_from_file_location(
    "protocol", pathlib.Path(__file__).parent.parent / "custom_components/trimlight/protocol.py"
)
p = importlib.util.module_from_spec(spec)
sys.modules["protocol"] = p
spec.loader.exec_module(p)


def describe(x: p.Pattern) -> str:
    colours = " ".join(x.dot_colors[i * 3:i * 3 + 3].hex() for i in range(7))
    return (f"id {x.id} '{x.name}' category {x.category} effect {x.effect} speed {x.speed} "
            f"brightness {x.brightness} counts {list(x.dot_counts)} colours {colours}")


async def snapshot(host: str):
    t = p.Trimlight(host)
    detail = await t.detail()
    patterns = {x.id: x for x in await t.patterns(detail.pattern_ids)}
    schedules = {s.id: s for s in await t.schedules(detail.schedule_ids)}
    return patterns, schedules, detail.daily


def diff(host, label, old, new, fmt):
    for k in sorted(new.keys() - old.keys()):
        print(f"{host} {label} ADDED: {fmt(new[k])}", flush=True)
    for k in sorted(old.keys() - new.keys()):
        print(f"{host} {label} REMOVED: {fmt(old[k])}", flush=True)
    for k in sorted(old.keys() & new.keys()):
        if old[k] != new[k]:
            print(f"{host} {label} CHANGED:\n  was {fmt(old[k])}\n  now {fmt(new[k])}", flush=True)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="+")
    ap.add_argument("--every", type=float, default=15)
    args = ap.parse_args()
    last = {}
    while True:
        for host in args.hosts:
            try:
                snap = await snapshot(host)
            except Exception as e:  # the app may hold the connection; try next round
                print(f"{time.strftime('%H:%M:%S')} {host} unreachable ({e!r})", flush=True)
                continue
            if host not in last:
                print(f"{time.strftime('%H:%M:%S')} {host}: watching {len(snap[0])} patterns, "
                      f"{len(snap[1])} schedules", flush=True)
            else:
                old = last[host]
                print(f"--- {time.strftime('%H:%M:%S')}", flush=True) if old != snap else None
                diff(host, "pattern", old[0], snap[0], describe)
                diff(host, "schedule", old[1], snap[1], repr)
                if old[2] != snap[2]:
                    print(f"{host} daily CHANGED:\n  was {old[2]}\n  now {snap[2]}", flush=True)
            last[host] = snap
        await asyncio.sleep(args.every)


asyncio.run(main())
