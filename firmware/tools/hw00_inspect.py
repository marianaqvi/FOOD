# firmware/tools/hw00_inspect.py
# STAGE 0: run with the board ALONE on USB from the Mac (no panels connected).
# Prints what the board is, how much flash/RAM is free, and whether the official
# Interstate 75 module and display sizes exist. Lights nothing: it only sends black frames.
# Copy firmware/power.py and firmware/hwtest_common.py to the board first.

import gc
import os
import sys
import time

OPEN_DISPLAY = True  # constructs the official display and sends black frames only
MODE = "chained"     # "chained" (128 x 32) or "single" (64 x 32); run once per mode, reset between
BLANK_UPDATES = 20   # to time update() with an all-black buffer


def _try(fn, default=None):
    try:
        return fn()
    except Exception as e:  # report, never crash the inspection
        return default if default is not None else "unavailable (%s)" % e


def _ticks():
    return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)


def _diff(a, b):
    return time.ticks_diff(a, b) if hasattr(time, "ticks_diff") else a - b


def main():
    print("=== FOOD sheep: board inspection ===")
    print("implementation:", sys.implementation)
    print("version:", sys.version)
    print("uname:", _try(lambda: os.uname()))
    try:
        import machine
        print("cpu MHz:", machine.freq() // 1000000)
    except Exception as e:
        print("cpu MHz: unavailable (%s)" % e)

    gc.collect()
    if hasattr(gc, "mem_free"):
        print("RAM free / allocated bytes:", gc.mem_free(), "/", gc.mem_alloc())
    st = _try(lambda: os.statvfs("/"))
    if isinstance(st, tuple) or hasattr(st, "__getitem__"):
        block = st[0]
        print("flash block size:", block, " total bytes:", block * st[2], " free bytes:", block * st[3])
        print("needed for packed assets: 480480 bytes plus headroom")
    else:
        print("flash: ", st)

    print("files in /:")
    for name in _try(lambda: sorted(os.listdir("/")), []):
        size = _try(lambda: os.stat("/" + name)[6], -1)
        print("  ", name, size)

    try:
        import interstate75
    except Exception as e:
        print("import interstate75: FAILED (%s)" % e)
        print("=> this firmware may not be the Pimoroni build. Do NOT flash anything yet; report this output.")
        return
    print("import interstate75: ok")
    consts = [n for n in dir(interstate75) if n.startswith("DISPLAY_INTERSTATE75")]
    print("display constants:", consts)
    for need in ("DISPLAY_INTERSTATE75_128X32", "DISPLAY_INTERSTATE75_64X32"):
        print(need, "present" if need in consts else "MISSING")

    if not OPEN_DISPLAY:
        return
    import hwtest_common as hw

    # ONE display per run. Observed 2026-11-25 on this board (MicroPython 1.25.0-preview,
    # RP2350): constructing a second Interstate75 in the same session hung the board until
    # it was reset. So run this script once per mode and reset the board in between.
    mode = MODE
    try:
        i75, gfx = hw.open_display(mode)
    except Exception as e:
        print(mode, "open FAILED:", e)
        return
    print(mode, "bounds:", gfx.get_bounds(), " interstate75w flag:", getattr(i75, "interstate75w", "n/a"))
    t0 = _ticks()
    for _ in range(BLANK_UPDATES):
        hw.blank(i75, gfx)
    dt = _diff(_ticks(), t0)
    print(mode, "black update() avg ms:", dt / BLANK_UPDATES)
    hw.blank(i75, gfx)
    print("=== done: nothing was lit ===")


if __name__ == "__main__":
    main()
