"""A host-side stand-in for the Pimoroni `interstate75` module, for testing the hardware scripts.

It models the one behaviour that matters for safety: clear() fills the whole buffer with the
CURRENT pen, exactly like picographics, so a script that clears with a colour pen is caught.
It does not model electricity, timing or the real HUB75 driver. It proves nothing about hardware.
"""
import types

SIZES = {
    "DISPLAY_INTERSTATE75_64X32": (64, 32),
    "DISPLAY_INTERSTATE75_128X32": (128, 32),
}
BLACK = (0, 0, 0)


class FakeDisplay:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.pen = BLACK
        self.fill = BLACK
        self.px = {}

    def create_pen(self, r, g, b):
        return (r, g, b)

    def set_pen(self, pen):
        self.pen = pen

    def clear(self):
        self.fill = self.pen
        self.px = {}

    def pixel(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:  # the real driver clips silently
            self.px[(x, y)] = self.pen

    def get_bounds(self):
        return (self.w, self.h)


class Snapshot:
    def __init__(self, display):
        self.w, self.h = display.w, display.h
        self.fill = display.fill
        self.px = dict(display.px)

    def lit(self):
        """Non-black pixels as {(x, y): rgb}. A non-black fill lights every pixel."""
        if self.fill != BLACK:
            out = {(x, y): self.fill for x in range(self.w) for y in range(self.h)}
        else:
            out = {}
        for k, v in self.px.items():
            if v != BLACK:
                out[k] = v
            else:
                out.pop(k, None)
        return out


def make_module(update_needs_arg=False, reject_kwargs=False):
    """Return (module, instances) where instances collects every Interstate75 constructed."""
    mod = types.ModuleType("interstate75")
    instances = []
    for name in SIZES:
        setattr(mod, name, name)
    mod.SWITCH_A = 0
    mod.SWITCH_B = 1

    class Interstate75:
        interstate75w = True
        PANEL_GENERIC = 0
        PANEL_FM6126A = 1

        def __init__(self, display, panel_type=0, stb_invert=False, color_order=0):
            if reject_kwargs and (panel_type != 0 or stb_invert):
                raise TypeError("unsupported option on this fake firmware")
            self.init_kwargs = {}
            if panel_type != 0:
                self.init_kwargs["panel_type"] = panel_type
            if stb_invert:
                self.init_kwargs["stb_invert"] = True
            w, h = SIZES[display]
            self.display = FakeDisplay(w, h)
            self.snapshots = []
            self.buttons = {0: False, 1: False}  # tests press buttons by setting these
            self.led = (0, 0, 0)
            self.update_needs_arg = update_needs_arg
            instances.append(self)

        def switch_pressed(self, n):
            return self.buttons[n]

        def set_led(self, r, g, b):
            self.led = (r, g, b)

        def update(self, graphics=None):
            if self.update_needs_arg and graphics is None:
                raise TypeError("function takes 2 positional arguments but 1 were given")
            self.snapshots.append(Snapshot(self.display))

    mod.Interstate75 = Interstate75
    return mod, instances
