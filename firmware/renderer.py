# firmware/renderer.py
# Composes one packed frame record into the hardware buffer. MicroPython and CPython compatible.
#
# Contract (CLAUDE.md "Physical display contract"):
#   - the habitat is 64 x 32 in LOCAL coordinates; every habitat pixel is clipped to 0..63 / 0..31
#     before the origin is added;
#   - mode "single": hardware buffer is 64 x 32, origin 0 (isolated single-panel test mode);
#     mode "chained": 128 x 32, origin 0 or 64, the other half is never drawn and stays black;
#   - the WHOLE buffer is cleared with a black pen before composing, and update() runs once per frame;
#   - colours are scaled with power.scale_rgb, which hard-clamps the scale at power.HARD_MAX_PERMILLE;
#   - a frame with more than power.MAX_LIT_PIXELS distinct lit pixels, or above the aggregate frame
#     budget, is replaced by a black frame (never drawn partly);
#   - layers A, B, effects: later layers overwrite earlier ones at shared pixels. This is done by
#     giving each pixel to the LAST layer that lights it, so the result equals drawing in order.
# A frame record is 770 bytes: u16le duration, then three 256-byte masks (32 rows x 8 bytes,
# row-major, MSB-first). See scripts/pack_assets.py.

import power

HABITAT_W = 64
HABITAT_H = 32
MASK_BYTES = 256
RECORD_SIZE = 2 + 3 * MASK_BYTES  # 770
OFF_A = 2
OFF_B = 2 + MASK_BYTES
OFF_FX = 2 + 2 * MASK_BYTES

_POP = bytearray(256)
for _i in range(1, 256):
    _POP[_i] = _POP[_i >> 1] + (_i & 1)


class Renderer:
    def __init__(self, i75, gfx, mode="single", origin=0, permille=power.DEFAULT_PERMILLE,
                 colours=("#F0F5F1", "#F0F5F1", "#F0F5F1")):
        w, h = gfx.get_bounds()
        if mode == "single":
            if origin != 0:
                raise ValueError("single-panel mode requires origin 0")
            if (w, h) != (HABITAT_W, HABITAT_H):
                raise ValueError("single-panel mode needs a 64 x 32 display, got %d x %d" % (w, h))
        elif mode == "chained":
            if origin not in power.ALLOWED_ORIGINS:
                raise ValueError("origin must be 0 or 64")
            if (w, h) != (2 * HABITAT_W, HABITAT_H):
                raise ValueError("chained mode needs a 128 x 32 display, got %d x %d" % (w, h))
        else:
            raise ValueError("mode must be 'single' or 'chained'")
        self.i75, self.gfx = i75, gfx
        self.mode, self.origin = mode, origin
        self.blackout = False
        self.frame_budget = power.FRAME_BUDGET
        self.last_lit = 0
        self.last_cost = 0
        self.rejected = 0
        self._black = gfx.create_pen(0, 0, 0)
        self._own = bytearray(3 * MASK_BYTES)  # per-layer pixels this layer actually shows
        self.set_colours(colours, permille)

    def set_colours(self, colours, permille=power.DEFAULT_PERMILLE):
        """colours: three '#RRGGBB' strings (sheep A, sheep B, effects). Scaled and clamped here."""
        if len(colours) != 3:
            raise ValueError("need three colours")
        self.permille = power.clamp_permille(permille)
        rgbs = [power.scale_rgb(power.parse_hex(c), self.permille) for c in colours]
        self.rgbs = rgbs
        self._pens = [self.gfx.create_pen(c[0], c[1], c[2]) for c in rgbs]
        self._costs = [power.rgb_cost(c) for c in rgbs]

    def set_blackout(self, on):
        self.blackout = bool(on)

    def _update(self):
        try:
            self.i75.update()
        except TypeError:  # some firmware wants update(graphics)
            self.i75.update(self.gfx)

    def blank(self):
        self.gfx.set_pen(self._black)
        self.gfx.clear()
        self._update()

    def draw(self, rec):
        """Compose one frame record and update the panel once. Returns the number of lit pixels
        drawn (0 for blackout or a rejected frame)."""
        gfx = self.gfx
        gfx.set_pen(self._black)
        gfx.clear()  # the whole hardware buffer, including any reserved half
        self.last_lit = 0
        self.last_cost = 0
        if self.blackout or len(rec) != RECORD_SIZE:
            self._update()
            return 0
        own = self._own
        na = nb = nf = 0
        for i in range(MASK_BYTES):
            fx = rec[OFF_FX + i]
            b = rec[OFF_B + i]
            a = rec[OFF_A + i]
            own_b = b & ~fx & 0xFF
            own_a = a & ~(b | fx) & 0xFF
            own[i] = own_a
            own[MASK_BYTES + i] = own_b
            own[2 * MASK_BYTES + i] = fx
            na += _POP[own_a]
            nb += _POP[own_b]
            nf += _POP[fx]
        lit = na + nb + nf
        cost = na * self._costs[0] + nb * self._costs[1] + nf * self._costs[2]
        if lit > power.MAX_LIT_PIXELS or cost > self.frame_budget:
            self.rejected += 1
            self._update()  # black frame
            return 0
        origin = self.origin
        for layer in range(3):
            if (na, nb, nf)[layer] == 0:
                continue
            gfx.set_pen(self._pens[layer])
            base = layer * MASK_BYTES
            for i in range(MASK_BYTES):
                v = own[base + i]
                if v:
                    y = i >> 3
                    x0 = origin + ((i & 7) << 3)
                    for bit in range(8):
                        if v & (0x80 >> bit):
                            gfx.pixel(x0 + bit, y)
        self.last_lit = lit
        self.last_cost = cost
        self._update()
        return lit
