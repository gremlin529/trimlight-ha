"""Trimlight controller LAN protocol (no Home Assistant code here).

Reverse-engineered by msjarrett:
https://github.com/msjarrett/trimlight/blob/main/protocol/protocol.md

TCP port 8189. Requests are 0x5A, type, payload length (2 bytes, big-endian),
payload, 0xA5. Replies are 0x5A, fields, 0xA5, with no type byte, so the
asker has to know what it asked. Commands that change things get no reply.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time

PORT = 8189
START, END = 0x5A, 0xA5

SYNC_DETAIL = 0x02
CHECK_PATTERN = 0x03
DELETE_PATTERN = 0x04
UPDATE_PATTERN = 0x05
CREATE_PATTERN = 0x06
CHECK_PRESET = 0x0A
CHECK_DEVICE = 0x0C
SET_MODE = 0x0D
CUSTOM_PREVIEW = 0x13
SOLID_COLOR = 0x14
PATTERN_DETAIL = 0x16
SCHEDULE_DETAIL = 0x17

MODE_TIMER = 0  # the controller follows its own schedules
MODE_MANUAL = 1

CATEGORY_PRESET = 1  # one of the 180 built-in effects; `effect` is its number
CATEGORY_CUSTOM = 2

EFFECTS = [
    "Static", "Chase Forward", "Chase Backward", "Chase Middle to Out", "Chase Out to Middle",
    "Strobe", "Fade", "Comet Forward", "Comet Backward", "Wave Forward", "Wave Backward", "Solid Fade",
]


class TrimlightError(Exception):
    """The controller couldn't be reached or answered oddly."""


@dataclass
class DeviceInfo:
    name: str
    mode: int
    ic: int
    rgb_order: int
    pixels: int


@dataclass
class Pattern:
    id: int
    name: str
    category: int
    effect: int
    speed: int
    brightness: int
    dot_counts: bytes  # 7 bytes
    dot_colors: bytes  # 21 bytes, R G B for each of the 7


@dataclass
class DailySchedule:
    slot: int  # 1 or 2
    enabled: bool
    pattern_id: int
    repetition: int  # 0 today only, 1 every day, 2 weekdays, 3 weekends
    start: time
    end: time


@dataclass
class Schedule:
    id: int
    pattern_id: int
    start_month: int
    start_day: int
    end_month: int
    end_day: int
    start: time
    end: time


@dataclass
class Detail:
    pattern_ids: list[int] = field(default_factory=list)
    schedule_ids: list[int] = field(default_factory=list)
    daily: list[DailySchedule] = field(default_factory=list)


def frame(kind: int, payload: bytes = b"") -> bytes:
    return bytes([START, kind, len(payload) >> 8, len(payload) & 0xFF]) + payload + bytes([END])


NAME_LENGTH = 25


def pattern_payload(p: Pattern) -> bytes:
    """A saved pattern as Create/Update Pattern send it, the same 58 bytes
    Pattern Detail returns."""
    name = p.name.encode("ascii")[:NAME_LENGTH].ljust(NAME_LENGTH, b"\x00")
    out = (bytes([p.id]) + name + bytes([p.category, p.effect, p.speed, p.brightness])
           + bytes(p.dot_counts).ljust(7, b"\x00")[:7] + bytes(p.dot_colors).ljust(21, b"\x00")[:21])
    assert len(out) == 58
    return out


def _name(raw: bytes) -> str:
    out = bytearray()
    for b in raw:
        if b in (0x00, 0xFF):
            break
        out.append(b)
    return out.decode("ascii", "replace").strip()


def _time(h: int, m: int) -> time:
    return time(min(h, 23), min(m, 59))


def _check_reply(host: str, b: bytes, wanted_id: int) -> None:
    """A detail reply must be for the ID asked for and end where it should.
    With the app connected too, the controller sometimes answers with another
    request's reply; reading on would misparse everything after it."""
    if b[0] != START or b[-1] != END or b[1] != wanted_id:
        raise TrimlightError(f"{host}: reply for the wrong request ({b[:6].hex()}...)")


class Trimlight:
    """One controller. Each call opens its own short connection; calls are
    serialised, since the controller is a small device."""

    def __init__(self, host: str, port: int = PORT, timeout: float = 4.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()

    async def _session(self, work):
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), self.timeout
                )
            except (OSError, asyncio.TimeoutError) as err:
                raise TrimlightError(f"can't connect to {self.host}: {err}") from err
            try:
                return await work(reader, writer)
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
                raise TrimlightError(f"{self.host}: {err}") from err
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _read(self, reader, n: int) -> bytes:
        return await asyncio.wait_for(reader.readexactly(n), self.timeout)

    # ------------------------------------------------------------ queries

    async def device_info(self, now: datetime | None = None) -> DeviceInfo:
        """Check Device: the app sends this on connecting. It also sets the
        controller's clock, which its schedules run on."""
        now = now or datetime.now()
        verify = bytes(random.choice([b for b in range(1, 255) if b not in (START, END)]) for _ in range(3))
        payload = verify + bytes([now.year % 100, now.month, now.day, now.isoweekday(),
                                  now.hour, now.minute, now.second])

        async def work(reader, writer):
            writer.write(frame(CHECK_DEVICE, payload))
            await writer.drain()
            head = await self._read(reader, 4)  # start, verification, mode, name length
            if head[0] != START:
                raise TrimlightError(f"{self.host}: unexpected reply {head.hex()}")
            n = min(head[3], 32)
            rest = await self._read(reader, n + 7)  # name, ic, order, pixels(2), 2 unknown, end
            return DeviceInfo(
                name=_name(rest[:n]) or "Trimlight",
                mode=head[2],
                ic=rest[n],
                rgb_order=rest[n + 1],
                pixels=(rest[n + 2] << 8) | rest[n + 3],
            )

        return await self._session(work)

    async def detail(self) -> Detail:
        async def work(reader, writer):
            writer.write(frame(SYNC_DETAIL))
            await writer.drain()
            head = await self._read(reader, 2)
            if head[0] != START:
                raise TrimlightError(f"{self.host}: unexpected reply {head.hex()}")
            pattern_ids = list(await self._read(reader, head[1]))
            count = (await self._read(reader, 1))[0]
            schedule_ids = list(await self._read(reader, count))
            daily_raw = await self._read(reader, 15)  # 2 x 7, end
            if daily_raw[14] != END:
                raise TrimlightError(f"{self.host}: garbled detail reply")
            daily = []
            for slot in range(2):
                d = daily_raw[slot * 7: slot * 7 + 7]
                daily.append(DailySchedule(slot + 1, d[0] == 1, d[1], d[2], _time(d[3], d[4]), _time(d[5], d[6])))
            return Detail(pattern_ids, schedule_ids, daily)

        return await self._session(work)

    async def patterns(self, ids: list[int]) -> list[Pattern]:
        async def work(reader, writer):
            out = []
            for pid in ids:
                writer.write(frame(PATTERN_DETAIL, bytes([pid])))
                await writer.drain()
                b = await self._read(reader, 60)
                if b[0] == START and b[2:60] == b"\xff" * 58:
                    continue  # no such pattern
                _check_reply(self.host, b, pid)
                out.append(Pattern(b[1], _name(b[2:27]), b[27], b[28], b[29], b[30], bytes(b[31:38]), bytes(b[38:59])))
            return out

        return await self._session(work)

    async def schedules(self, ids: list[int]) -> list[Schedule]:
        async def work(reader, writer):
            out = []
            for sid in ids:
                writer.write(frame(SCHEDULE_DETAIL, bytes([sid])))
                await writer.drain()
                b = await self._read(reader, 12)
                if b[0] == START and b[1] == 0xFF:
                    # No such schedule: the reply is 60 bytes of 0xff.
                    await self._read(reader, 48)
                    continue
                _check_reply(self.host, b, sid)
                out.append(Schedule(b[1], b[2], b[3], b[4], b[5], b[6], _time(b[7], b[8]), _time(b[9], b[10])))
            return out

        return await self._session(work)

    # ------------------------------------------------------------ commands

    async def _send(self, *frames: bytes) -> None:
        async def work(reader, writer):
            for f in frames:
                writer.write(f)
                await writer.drain()
                await asyncio.sleep(0.05)  # no replies; give each a moment

        await self._session(work)

    async def set_mode(self, mode: int) -> None:
        await self._send(frame(SET_MODE, bytes([mode])))

    async def play_pattern(self, pattern: Pattern, brightness: int | None = None) -> None:
        """Shows a saved pattern (manual mode). With a brightness other than
        the pattern's own, it's shown as a preview at that brightness."""
        frames = [frame(SET_MODE, bytes([MODE_MANUAL])), frame(CHECK_PATTERN, bytes([pattern.id]))]
        if brightness is not None and brightness != pattern.brightness:
            frames.append(self._preview(pattern, brightness))
        await self._send(*frames)

    async def set_brightness(self, pattern: Pattern, brightness: int) -> None:
        await self._send(frame(SET_MODE, bytes([MODE_MANUAL])), self._preview(pattern, brightness))

    @staticmethod
    def _preview(pattern: Pattern, brightness: int) -> bytes:
        brightness = max(1, min(255, brightness))
        if pattern.category == CATEGORY_PRESET:
            return frame(CHECK_PRESET, bytes([pattern.effect, pattern.speed, brightness]))
        return frame(CUSTOM_PREVIEW, bytes([pattern.effect, pattern.speed, brightness])
                     + pattern.dot_counts + pattern.dot_colors)

    async def preview(self, pattern: Pattern) -> None:
        """Shows a pattern without saving it (manual mode)."""
        await self._send(frame(SET_MODE, bytes([MODE_MANUAL])), self._preview(pattern, pattern.brightness))

    # The library. Tried live: a created pattern reads back exactly, and the
    # colours are R, G, B (not R, B, G as the protocol notes say).

    async def create_pattern(self, pattern: Pattern) -> None:
        """Saves a new pattern under pattern.id, which must be free."""
        await self._send(frame(CREATE_PATTERN, pattern_payload(pattern)))

    async def update_pattern(self, pattern: Pattern) -> None:
        """Overwrites the saved pattern with pattern.id."""
        await self._send(frame(UPDATE_PATTERN, pattern_payload(pattern)))

    async def delete_pattern(self, pattern_id: int) -> None:
        await self._send(frame(DELETE_PATTERN, bytes([pattern_id])))

    async def solid_color(self, r: int, g: int, b: int) -> None:
        await self._send(frame(SET_MODE, bytes([MODE_MANUAL])), frame(SOLID_COLOR, bytes([r, g, b])))

    async def turn_off(self) -> None:
        """The controllers' only off: back to their own schedules (timer
        mode), which leaves them dark outside a schedule's hours."""
        await self.set_mode(MODE_TIMER)


# ------------------------------------------------------------------ schedules

def _in_window(now: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end  # across midnight


def _in_dates(today: date, s: Schedule) -> bool:
    key = (today.month, today.day)
    start, end = (s.start_month, s.start_day), (s.end_month, s.end_day)
    if start <= end:
        return start <= key <= end
    return key >= start or key <= end  # across new year


def scheduled_pattern(now: datetime, detail: Detail, schedules: list[Schedule]) -> int | None:
    """Which pattern the controller's schedules show at `now`, if any. Dated
    schedules come before the daily ones. A window that runs past midnight
    belongs to the day it started."""
    for s in schedules:
        if not _in_window(now.time(), s.start, s.end):
            continue
        day = now.date()
        if s.start > s.end and now.time() < s.end:
            day = date.fromordinal(day.toordinal() - 1)
        if _in_dates(day, s):
            return s.pattern_id
    for d in detail.daily:
        if not d.enabled or not _in_window(now.time(), d.start, d.end):
            continue
        day = now
        if d.start > d.end and now.time() < d.end:
            day = datetime.fromordinal(now.toordinal() - 1)
        weekday = day.isoweekday()
        if d.repetition == 2 and weekday > 5:
            continue
        if d.repetition == 3 and weekday <= 5:
            continue
        return d.pattern_id
    return None


# ------------------------------------------------------------------ discovery

async def _probe(host: str, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, PORT), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def discover(own_ip: str, timeout: float = 1.0, concurrency: int = 32) -> list[str]:
    """Finds controllers on own_ip's /24 the way the app does: tries port
    8189 everywhere, then keeps the ones that answer a Sync Detail."""
    net = ipaddress.ip_network(f"{own_ip}/24", strict=False)
    hosts = [str(h) for h in net.hosts() if str(h) != own_ip]
    sem = asyncio.Semaphore(concurrency)

    async def one(h: str) -> str | None:
        async with sem:
            return h if await _probe(h, timeout) else None

    open_hosts = [h for h in await asyncio.gather(*(one(h) for h in hosts)) if h]
    found = []
    for h in open_hosts:
        try:
            await Trimlight(h, timeout=2.0).detail()
            found.append(h)
        except TrimlightError:
            pass
    return sorted(found, key=lambda h: ipaddress.ip_address(h))
