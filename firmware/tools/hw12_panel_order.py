# firmware/tools/hw12_panel_order.py
# STAGE 3: both panels chained (official DISPLAY_INTERSTATE75_128X32). Four sparse pixels
# say which physical panel is the first half (x 0-63) and which is the second (x 64-127),
# and whether either panel is flipped.
#
#   first half  (x 0-63):   a VERTICAL pair near its top-left corner:   (2,2) and (2,4)
#   second half (x 64-127): a HORIZONTAL pair near its top-left corner: (66,2) and (68,2)
#
# Upright and unmirrored, each pair sits in that panel's top-left corner. Then choose the
# habitat origin: 0 if the sheep should live on the panel showing the vertical pair,
# 64 if on the panel showing the horizontal pair. Record the result in docs/test-log.md.
# Same confirmation gate as hw10. Scale 0.10.

I_HAVE_CHECKED_POWER_AND_WIRING = False

SECONDS = 15

import time

import hwtest_common as hw
import power


def main(sleep=time.sleep):
    if I_HAVE_CHECKED_POWER_AND_WIRING is not True:
        return hw.refuse("set I_HAVE_CHECKED_POWER_AND_WIRING = True only after the wiring checklist is done")
    pixels, seconds = hw.stage_pixels(3)
    i75, gfx = hw.open_display("chained")
    print("bounds:", gfx.get_bounds())
    print("Expect 4 dim pixels total for", seconds, "seconds. Record, for EACH physical panel:")
    print("  which pair it shows (vertical = first half, horizontal = second half)")
    print("  which corner the pair is in (top-left means upright and unmirrored)")
    print("  that nothing else on either panel lights")
    hw.show(i75, gfx, pixels, seconds, sleep)
    print("done, both panels blanked")
    return True


if __name__ == "__main__":
    main()
