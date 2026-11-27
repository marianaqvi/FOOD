# firmware/tools/hw11_colour_order.py
# STAGE 2: three sparse single-colour pixels on ONE panel to check RGB channel order.
# Expected, left to right: red, green, blue. Record what you actually see.
# Same confirmation gate as hw10. Scale 0.10, each channel <= 26 of 255.

I_HAVE_CHECKED_POWER_AND_WIRING = False

MODE = "single"
SECONDS = 10

import time

import hwtest_common as hw
import power


def main(sleep=time.sleep):
    if I_HAVE_CHECKED_POWER_AND_WIRING is not True:
        return hw.refuse("set I_HAVE_CHECKED_POWER_AND_WIRING = True only after the wiring checklist is done")
    pixels, seconds = hw.stage_pixels(2)
    i75, gfx = hw.open_display(MODE)
    print("Expect three dim pixels left to right: RED, GREEN, BLUE for", seconds, "seconds.")
    print("Write down the colours you actually see, left to right.")
    hw.show(i75, gfx, pixels, seconds, sleep)
    print("done, panel blanked")
    return True


if __name__ == "__main__":
    main()
