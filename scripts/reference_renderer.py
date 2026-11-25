"""CPU reference renderer for the sheep habitat.

This is the executable specification for both the browser canvas and the
MicroPython firmware: they must produce the same pixels as ``compose``.
It models the *hardware buffer*: 128x32 in chained mode or 64x32 in single
panel test mode. The habitat is 64x32 and is placed at ``origin``; every other
hardware pixel stays black.

All colour maths is integer-only so firmware can match it exactly:
    scaled = (channel * scale_permille + 500) // 1000
which equals JavaScript's Math.round(channel * scale) for the supported range.
"""
import json
import os

HABITAT_W, HABITAT_H = 64, 32
ROW_BYTES = HABITAT_W // 8

_LIMITS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared", "limits.json")
with open(_LIMITS_PATH, "r", encoding="utf-8") as _fh:
    LIMITS = json.load(_fh)

HARD_MAX_PERMILLE = LIMITS["rgb_scale"]["hard_max_permille"]
CHAINED = "chained"
SINGLE = "single"
BLACK = (0, 0, 0)


def pixel_set(mask, x, y):
    return bool(mask[y * ROW_BYTES + (x >> 3)] & (0x80 >> (x & 7)))


def lit_set(mask):
    """Set of (x, y) lit in one 256-byte mask."""
    return {(x, y) for y in range(HABITAT_H) for x in range(HABITAT_W) if pixel_set(mask, x, y)}


def unique_lit_count(a, b, fx):
    """Distinct lit pixels across the three layers (what the preview should show)."""
    return len(lit_set(a) | lit_set(b) | lit_set(fx))


def parse_hex(colour):
    if not (isinstance(colour, str) and len(colour) == 7 and colour[0] == "#"):
        raise ValueError("colour must be #RRGGBB: %r" % (colour,))
    v = int(colour[1:], 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def clamp_scale(permille):
    """Hard clamp applied before any scaling. Never raised remotely."""
    return max(0, min(int(permille), HARD_MAX_PERMILLE))


def scale_colour(rgb, permille):
    p = clamp_scale(permille)
    return tuple((c * p + 500) // 1000 for c in rgb)


def hardware_size(mode):
    if mode == CHAINED:
        return LIMITS["chained_display"]["width"], LIMITS["chained_display"]["height"]
    if mode == SINGLE:
        return HABITAT_W, HABITAT_H
    raise ValueError("unknown mode %r" % (mode,))


def compose(masks, colours, scale_permille, origin=0, mode=CHAINED, blackout=False):
    """Render one frame into a hardware buffer.

    masks    -- (sheep_a, sheep_b, effects), each 256 bytes
    colours  -- three '#RRGGBB' strings in the same order
    returns  -- list of rows; each row is a list of (r, g, b) tuples
    """
    hw_w, hw_h = hardware_size(mode)
    if mode == SINGLE and origin != 0:
        raise ValueError("single-panel mode requires origin 0")
    if mode == CHAINED and origin not in LIMITS["allowed_habitat_origins"]:
        raise ValueError("origin must be 0 or 64")
    buf = [[BLACK] * hw_w for _ in range(hw_h)]  # whole buffer cleared first
    if blackout:
        return buf
    rgbs = [scale_colour(parse_hex(c), scale_permille) for c in colours]
    for mask, rgb in zip(masks, rgbs):  # A, then B, then effects; later overwrites
        for y in range(HABITAT_H):
            for x in range(HABITAT_W):  # clip: local 64x32 only
                if mask[y * ROW_BYTES + (x >> 3)] & (0x80 >> (x & 7)):
                    buf[y][origin + x] = rgb
    return buf


def lit_columns(buf):
    """Set of hardware x columns containing any non-black pixel."""
    return {x for row in buf for x, px in enumerate(row) if px != BLACK}
