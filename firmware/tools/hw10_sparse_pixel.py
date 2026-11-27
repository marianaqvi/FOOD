# firmware/tools/hw10_sparse_pixel.py
# STAGE 1: ONE pixel, ONE panel, software scale 0.10, for a few seconds, then black.
#
# This script refuses to run until you edit the line below to True. Only do that after
# you have read docs/hardware-proof.md, checked polarity with the supply UNPLUGGED, and
# confirmed the power arrangement. Never hot-plug the ribbon or the power leads.
# A scale of 0.10 is a conservative software default, NOT a measured electrical limit.

I_HAVE_CHECKED_POWER_AND_WIRING = False

MODE = "single"   # official DISPLAY_INTERSTATE75_64X32, one panel connected
SECONDS = 10

import time

import hwtest_common as hw
import power


def main(sleep=time.sleep):
    if I_HAVE_CHECKED_POWER_AND_WIRING is not True:
        return hw.refuse("set I_HAVE_CHECKED_POWER_AND_WIRING = True only after the wiring checklist is done")
    pixels, seconds = hw.stage_pixels(1)  # one pixel at (32, 16), colour (24, 25, 24)
    i75, gfx = hw.open_display(MODE)
    print("bounds:", gfx.get_bounds(), "pixel:", pixels)
    print("Expect exactly ONE dim white LED, near the middle of the panel, for", seconds, "seconds.")
    print("If you see more than one lit LED, any smell, heat or flicker: unplug power at the wall now.")
    hw.show(i75, gfx, pixels, seconds, sleep)
    print("done, panel blanked")
    return True


if __name__ == "__main__":
    main()
