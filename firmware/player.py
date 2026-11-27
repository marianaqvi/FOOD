# firmware/player.py
# Cooperative, non-blocking animation player. MicroPython and CPython compatible.
#
#   - Streams ONE 770-byte frame at a time from /assets/<id>.bin into a reused buffer; the whole
#     library (480,480 bytes) is never loaded. At most one file is open, and it is closed when a
#     reaction ends, on stop(), and on any error.
#   - tick() never sleeps and never touches the network: call it often (every few ms). It draws
#     only when the next frame is due, using wrap-safe tick arithmetic.
#   - Idle loops forever. A manual reaction plays `cycles` times (or loops while `hold` is set, up to
#     MAX_HOLD_MS) and then returns to idle by itself.
#   - Speed is clamped to 0.5x..1.0x (permille 500..1000); cycles to 1..MAX_CYCLES.
#   - If the manifest or idle file is bad, the built-in fallback (first idle frame, byte for byte)
#     is shown, never a crash and never a partial or garbage frame. A bad non-idle reaction is just
#     refused.
#   - Opening the display (exactly once per boot) is the caller's job.

import json

import fallback
import power
import renderer as _r

RECORD_SIZE = _r.RECORD_SIZE
SPEED_MIN = 500
SPEED_MAX = 1000
MAX_CYCLES = 20
MAX_HOLD_MS = 10 * 60 * 1000
MAX_FRAME_MS = 2000
FALLBACK_REDRAW_MS = 1000
IDLE = "idle"

try:
    import time as _time
except ImportError:  # pragma: no cover
    _time = None


class Clock:
    """Wrap-safe millisecond clock. On MicroPython (no now_fn) it uses time.ticks_*; otherwise
    it does the same arithmetic itself on a counter that wraps at `period`."""

    def __init__(self, now_fn=None, period=1 << 30):
        self._native = now_fn is None and hasattr(_time, "ticks_ms")
        if self._native:
            return
        self._now = now_fn or (lambda: int(_time.monotonic() * 1000))
        self._period = period
        self._half = period >> 1

    def ms(self):
        return _time.ticks_ms() if self._native else self._now() % self._period

    def diff(self, a, b):
        """a - b as a signed value, correct across a wrap."""
        if self._native:
            return _time.ticks_diff(a, b)
        d = (a - b) % self._period
        return d - self._period if d >= self._half else d

    def add(self, a, d):
        return _time.ticks_add(a, d) if self._native else (a + d) % self._period


def _crc32_file(opener, path):
    """CRC32 of a file in small chunks, or None if this firmware has no binascii.crc32."""
    import binascii

    if not hasattr(binascii, "crc32"):
        return None
    crc = 0
    buf = bytearray(512)
    fh = opener(path, "rb")
    try:
        while True:
            n = fh.readinto(buf)
            if not n:
                break
            crc = binascii.crc32(memoryview(buf)[:n], crc)
    finally:
        fh.close()
    return crc & 0xFFFFFFFF


class Player:
    def __init__(self, rend, assets_dir="/assets", clock=None, log=print, opener=open, stat=None):
        self.rend = rend
        self.dir = assets_dir.rstrip("/")
        self.clock = clock or Clock()
        self.log = log
        self.opener = opener
        if stat is None:
            import os
            stat = os.stat
        self.stat = stat
        self.rec = bytearray(RECORD_SIZE)
        self.frames = {}  # reaction id -> frame count, only for files that passed validation
        self.labels = {}
        self.asset_version = None
        self.fault = None  # None, or a short reason: fallback frame is shown instead
        self.bad = {}  # reaction id -> why it is unavailable
        self.fh = None
        self.cur = None  # reaction id currently playing
        self.frame = 0
        self.cycle = 0
        self.cycles = 1
        self.hold = False
        self.hold_start = None
        self.speed = SPEED_MAX
        self.next_due = None
        self.drawn = 0

    # ---- loading and validation -------------------------------------------------------------
    def load(self, verify_crc=False):
        """Read and validate the manifest and file sizes (and CRC32 if asked). Never raises:
        on any problem sets self.fault (idle unusable) or self.bad[id] (that reaction unusable)."""
        self.frames, self.bad, self.fault = {}, {}, None
        try:
            with self.opener(self.dir + "/manifest.json", "r") as fh:
                man = json.load(fh)
            if man.get("format_version") != 1 or man.get("record_size") != RECORD_SIZE:
                raise ValueError("unsupported manifest")
            self.asset_version = man.get("asset_version")
            for r in man["reactions"]:
                rid = r["id"]
                name = r["file"]
                if name != rid + ".bin" or "/" in rid or ".." in rid:
                    self.bad[rid] = "unexpected file name"
                    continue
                n = int(r["frames"])
                try:
                    size = self.stat(self.dir + "/" + name)[6]
                except OSError:
                    self.bad[rid] = "file missing"
                    continue
                if n < 1 or size != n * RECORD_SIZE or n * RECORD_SIZE != int(r["bytes"]):
                    self.bad[rid] = "wrong size"
                    continue
                if verify_crc:
                    crc = _crc32_file(self.opener, self.dir + "/" + name)
                    if crc is not None and crc != int(r["crc32"]):
                        self.bad[rid] = "checksum mismatch"
                        continue
                self.frames[rid] = n
                self.labels[rid] = r.get("label", rid)
            man = None
        except Exception as e:  # corrupt JSON, missing manifest, bad fields ...
            self._set_fault("manifest: %r" % (e,))
            return False
        for rid, why in self.bad.items():
            self.log("player: %s unavailable (%s)" % (rid, why))
        if IDLE not in self.frames:
            self._set_fault("idle unavailable (%s)" % self.bad.get(IDLE, "not in manifest"))
            return False
        return True

    def _set_fault(self, why):
        self._close()
        self.fault = why
        self.cur = None
        self.next_due = None
        self.log("player: FALLBACK idle frame, " + why)

    # ---- control ----------------------------------------------------------------------------
    def available(self):
        return sorted(self.frames)

    def play(self, reaction, speed_permille=SPEED_MAX, cycles=1, hold=False):
        """Start a reaction now. Returns False (and changes nothing) if it is unknown or unusable."""
        if self.fault is not None or reaction not in self.frames:
            return False
        speed = max(SPEED_MIN, min(int(speed_permille), SPEED_MAX))
        cycles = max(1, min(int(cycles), MAX_CYCLES))
        self._start(reaction, speed, cycles, bool(hold))
        return True

    def stop(self):
        """Back to idle immediately. Takes priority over everything."""
        if self.fault is None:
            self._start(IDLE, SPEED_MAX, 1, True)

    def set_blackout(self, on):
        self.rend.set_blackout(on)
        self.next_due = None  # redraw on the next tick (black, or the current frame again)

    def status(self):
        return {
            "reaction": self.cur if self.fault is None else "fallback",
            "frame": self.frame,
            "fault": self.fault,
            "blackout": self.rend.blackout,
            "rejected_frames": self.rend.rejected,
            "asset_version": self.asset_version,
        }

    def close(self):
        self._close()

    # ---- internals --------------------------------------------------------------------------
    def _close(self):
        fh, self.fh = self.fh, None
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass

    def _start(self, reaction, speed, cycles, hold):
        self._close()
        try:
            self.fh = self.opener(self.dir + "/" + reaction + ".bin", "rb")
        except Exception as e:
            self.bad[reaction] = "open failed"
            self.frames.pop(reaction, None)
            if reaction == IDLE:
                self._set_fault("idle open failed: %r" % (e,))
            elif IDLE in self.frames:
                self._start(IDLE, SPEED_MAX, 1, True)
            return
        self.cur = reaction
        self.frame = 0
        self.cycle = 0
        self.cycles = cycles
        self.hold = hold
        self.hold_start = self.clock.ms()
        self.speed = speed
        self.next_due = None  # draw the first frame on the next tick

    def _next_frame(self):
        """Read the next record into self.rec, handling end-of-reaction. Returns False on error."""
        for _ in range(2):
            n = self.fh.readinto(self.rec)
            if n == RECORD_SIZE:
                return True
            if n:  # short read: truncated or corrupt
                return False
            # end of file: next cycle, or back to idle
            self.cycle += 1
            reaction = self.cur
            expired = self.hold and self.clock.diff(self.clock.ms(), self.hold_start) >= MAX_HOLD_MS
            if reaction == IDLE or (self.hold and not expired) or self.cycle < self.cycles:
                self.fh.seek(0)
                self.frame = 0
            else:
                self._start(IDLE, SPEED_MAX, 1, True)
                if self.fault is not None or self.fh is None:
                    return False
        return False

    def tick(self):
        """Advance at most one frame if one is due. Never blocks. Returns True if a frame was drawn."""
        now = self.clock.ms()
        if self.next_due is not None and self.clock.diff(now, self.next_due) < 0:
            return False
        if self.fault is not None:
            self.rend.draw(fallback.RECORD)
            self.next_due = self.clock.add(now, FALLBACK_REDRAW_MS)
            self.drawn += 1
            return True
        if self.fh is None:
            self._start(IDLE, SPEED_MAX, 1, True)
            if self.fault is not None:
                return self.tick()
        try:
            if not self._next_frame():
                raise ValueError("truncated or unreadable frame in %s" % self.cur)
            dur = self.rec[0] | (self.rec[1] << 8)
            if dur < 1 or dur > MAX_FRAME_MS:
                raise ValueError("bad frame duration %d in %s" % (dur, self.cur))
        except Exception as e:
            self.log("player: error %r, dropping %s" % (e, self.cur))
            bad = self.cur
            self._close()
            if bad == IDLE or bad is None:
                self._set_fault("idle unreadable")
            else:
                self.bad[bad] = "unreadable"
                self.frames.pop(bad, None)
                self._start(IDLE, SPEED_MAX, 1, True)
            self.next_due = None
            return self.tick() if self.fault is not None else False
        self.rend.draw(self.rec)
        self.frame += 1
        self.drawn += 1
        scaled = dur * 1000 // self.speed
        base = self.next_due
        if base is None or self.clock.diff(now, base) >= scaled:
            base = now  # first frame, or we fell behind: resync instead of bursting
        self.next_due = self.clock.add(base, scaled)
        return True
