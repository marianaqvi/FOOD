# firmware/power.py
# Hard limits enforced on the device. Runs on MicroPython and CPython (no f-strings,
# no typing). These are conservative SOFTWARE limits, not measured electrical limits.
# tests/test_hwscripts.py asserts these agree with shared/limits.json.

HABITAT_W = 64
HABITAT_H = 32
ALLOWED_ORIGINS = (0, 64)  # chained 128 x 32 only; single-panel mode always uses 0

MAX_LIT_PIXELS = 281  # distinct lit habitat pixels in the supplied library

# Software RGB scale in permille (100 = 0.10). Hard-clamped in firmware; never raised remotely.
# HARD_MAX_PERMILLE is the ceiling for the animation player. It was 100 for the first hardware
# runs and was raised to 200 on 2026-11-26 at the owner's request (the sheep were too dim to read
# comfortably), a 2x step with NO current measurement behind it. Raise further only in small
# steps, recorded in docs/test-log.md. DEFAULT_PERMILLE is the scale the sparse proof stages use.
# RUN_PERMILLE is the scale the animation clips run at.
HARD_MAX_PERMILLE = 200
DEFAULT_PERMILLE = 100
RUN_PERMILLE = 200

# Largest value any channel may take after scaling, derived so it cannot drift.
MAX_CHANNEL = (255 * HARD_MAX_PERMILLE + 500) // 1000  # 51


# Aggregate per-frame budget: sum over distinct lit pixels of (r*WR + g*WG + b*WB) after scaling.
# UNCALIBRATED: weights are 1 (no measured per-channel current yet) and the budget is simply
# MAX_LIT_PIXELS * 3 * MAX_CHANNEL, so with the limits above it cannot trip. It exists so a
# measured, stricter value can be dropped in later; the stricter of all limits always wins.
CHANNEL_WEIGHTS = (1, 1, 1)
FRAME_BUDGET = MAX_LIT_PIXELS * 3 * MAX_CHANNEL  # 42993


def rgb_cost(rgb):
    return rgb[0] * CHANNEL_WEIGHTS[0] + rgb[1] * CHANNEL_WEIGHTS[1] + rgb[2] * CHANNEL_WEIGHTS[2]


def clamp_permille(p):
    p = int(p)
    if p < 0:
        return 0
    if p > HARD_MAX_PERMILLE:
        return HARD_MAX_PERMILLE
    return p


def scale_channel(c, permille):
    return (int(c) * clamp_permille(permille) + 500) // 1000


def scale_rgb(rgb, permille=DEFAULT_PERMILLE):
    return (
        scale_channel(rgb[0], permille),
        scale_channel(rgb[1], permille),
        scale_channel(rgb[2], permille),
    )


def parse_hex(s):
    if not isinstance(s, str) or len(s) != 7 or s[0] != "#":
        raise ValueError("colour must be #RRGGBB")
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
