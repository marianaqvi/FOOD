# firmware/hwtest_common.py
# Shared helpers for the hardware proof scripts in firmware/tools/.
# Deliberately tiny and strict: at most MAX_TEST_PIXELS lit pixels, every channel
# at or below PROOF_MAX_CHANNEL, bounded duration, and the panel is always blanked
# afterwards (even on error or when you press Stop in Thonny).

import power

MAX_TEST_PIXELS = 8
MAX_SECONDS = 30
# Fixed ceiling for the sparse proof stages (stages 1 to 3). It deliberately does NOT follow
# power.HARD_MAX_PERMILLE, so raising the player's cap never loosens these tests.
PROOF_MAX_CHANNEL = 26

# One-off VISIBILITY diagnostic (stage 4), added 2026-11-25 at the owner's explicit request
# after stage 1 (channel value 24 of 255) could not be seen on the real panel. It is the ONLY
# thing allowed above PROOF_MAX_CHANNEL, and it is separately bounded: at most 4 pixels, each
# channel at most 96, total of all channel values at most 1200 (a 2 x 2 block at 96 is 1152),
# at most 8 s. It does NOT change power.HARD_MAX_PERMILLE, which still governs the player.
DIAG_MAX_PIXELS = 4
DIAG_MAX_CHANNEL = 96
DIAG_MAX_SUM = 1200
DIAG_MAX_SECONDS = 8


def stage_pixels(stage):
    """The one definition of each sparse stage test, shared by firmware/tools/hw1x scripts and
    the on-board stage runner so they cannot drift. Returns (pixels, seconds). Colours are
    already scaled by power.scale_rgb. Stage 3 needs the chained 128 x 32 display."""
    white = power.scale_rgb((0xF0, 0xF5, 0xF1))
    if stage == 1:  # one pixel near the middle of the first panel
        return [(32, 16, white)], 10
    if stage == 2:  # colour order, left to right: red, green, blue
        return [
            (16, 16, power.scale_rgb((255, 0, 0))),
            (32, 16, power.scale_rgb((0, 255, 0))),
            (48, 16, power.scale_rgb((0, 0, 255))),
        ], 10
    if stage == 3:  # panel order: vertical pair on first half, horizontal pair on second
        return [(2, 2, white), (2, 4, white), (66, 2, white), (68, 2, white)], 15
    if stage == 4:  # visibility diagnostic: 2 x 2 block, above the normal clamp, see DIAG_* above
        return [
            (31, 15, (96, 96, 96)), (32, 15, (96, 96, 96)),
            (31, 16, (96, 96, 96)), (32, 16, (96, 96, 96)),
        ], 8
    raise ValueError("stage must be 1, 2, 3 or 4")


def stage_is_diagnostic(stage):
    return stage == 4


def refuse(message):
    print("REFUSED:", message)
    return False


# Display variants. A panel SETUP (1..4) is how the HUB75 driver is configured; a MODE is how
# many panels the display is sized for. A single panel must use 'single' (64 x 32), otherwise
# the driver clocks 128 pixels per row into a 64-pixel panel and the picture is wrong
# (a 2026-11-25 stage 4 run on one panel in chained mode showed stray dots and a green edge).
# Variants 1-4 are single-panel, 5-8 are the same four setups chained for two panels.
# Setup 1 is exactly the official default (no extra arguments); the others use the documented
# Interstate75(display, panel_type=..., stb_invert=...) options from pimoroni-pico.
SETUPS = {
    1: "generic",
    2: "FM6126A panel init",
    3: "generic, inverted strobe",
    4: "FM6126A panel init, inverted strobe",
}
NUM_VARIANTS = 8
VARIANTS = {}
for _v in range(1, NUM_VARIANTS + 1):
    VARIANTS[_v] = ("single 64x32, " if _v <= 4 else "chained 128x32, ") + SETUPS[(_v - 1) % 4 + 1]


def variant_parts(variant):
    """Variant 1..8 -> ('single' | 'chained', setup 1..4)."""
    if variant not in VARIANTS:
        raise ValueError("variant must be 1 to 8")
    return ("single" if variant <= 4 else "chained"), (variant - 1) % 4 + 1


def open_display(mode, setup=1):
    """mode 'single' -> official DISPLAY_INTERSTATE75_64X32; 'chained' -> ..._128X32.
    setup: see SETUPS (1 = official default). Opens exactly one Interstate75 (a second one
    hangs the board)."""
    import interstate75

    if mode == "single":
        name = "DISPLAY_INTERSTATE75_64X32"
    elif mode == "chained":
        name = "DISPLAY_INTERSTATE75_128X32"
    else:
        raise ValueError("mode must be 'single' or 'chained'")
    if setup not in SETUPS:
        raise ValueError("setup must be 1, 2, 3 or 4")
    kwargs = {}
    if setup in (2, 4):
        try:
            kwargs["panel_type"] = interstate75.Interstate75.PANEL_FM6126A
        except AttributeError:
            raise ValueError("this firmware has no PANEL_FM6126A")
    if setup in (3, 4):
        kwargs["stb_invert"] = True
    const = getattr(interstate75, name)
    i75 = interstate75.Interstate75(display=const, **kwargs)
    return i75, i75.display


def update(i75, gfx):
    """Official docs call board.update(); some older firmware wants update(graphics)."""
    try:
        i75.update()
    except TypeError:
        i75.update(gfx)


def _black(gfx):
    gfx.set_pen(gfx.create_pen(0, 0, 0))
    gfx.clear()


def blank(i75, gfx):
    _black(gfx)
    update(i75, gfx)


def show(i75, gfx, pixels, seconds, sleep, diagnostic=False):
    """Light the given sparse pixels for a bounded time, then blank.

    pixels: list of (x, y, (r, g, b)). Normally the colour must ALREADY be scaled by
    power.scale_rgb (every channel <= PROOF_MAX_CHANNEL, at most MAX_TEST_PIXELS pixels).
    diagnostic=True switches to the separate, stricter-in-count DIAG_* limits above and is
    used only by stage 4. The whole buffer is cleared to black first; one update.
    """
    if diagnostic:
        max_pixels, max_channel, max_seconds = DIAG_MAX_PIXELS, DIAG_MAX_CHANNEL, DIAG_MAX_SECONDS
    else:
        max_pixels, max_channel, max_seconds = MAX_TEST_PIXELS, PROOF_MAX_CHANNEL, MAX_SECONDS
    if len(pixels) > max_pixels:
        raise ValueError("too many pixels for a sparse test: %d" % len(pixels))
    if seconds > max_seconds:
        seconds = max_seconds
    width, height = gfx.get_bounds()
    total = 0
    for x, y, rgb in pixels:
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("pixel outside display: %d,%d" % (x, y))
        for c in rgb:
            if c < 0 or c > max_channel:
                raise ValueError("channel %d exceeds limit %d" % (c, max_channel))
            total += c
    if diagnostic and total > DIAG_MAX_SUM:
        raise ValueError("diagnostic total %d exceeds %d" % (total, DIAG_MAX_SUM))
    try:
        _black(gfx)
        for x, y, rgb in pixels:
            gfx.set_pen(gfx.create_pen(rgb[0], rgb[1], rgb[2]))
            gfx.pixel(x, y)
        update(i75, gfx)
        sleep(seconds)
    finally:
        blank(i75, gfx)
