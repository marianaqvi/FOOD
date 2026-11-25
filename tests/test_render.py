import unittest

import _paths  # noqa: F401
import pack_assets as pa
import reference_renderer as rr

HARD = rr.HARD_MAX_PERMILLE


def mask_with(*pixels):
    m = bytearray(256)
    for x, y in pixels:
        m[y * 8 + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(m)


EMPTY = bytes(256)


class ColourMaths(unittest.TestCase):
    def test_default_scale_golden(self):
        # Math.round(240*.1)=24, round(245*.1)=25 (24.5 rounds up), round(241*.1)=24
        self.assertEqual(rr.scale_colour((0xF0, 0xF5, 0xF1), 100), (24, 25, 24))
        self.assertEqual(rr.scale_colour((0xFF, 0xB3, 0x4F), 100), (26, 18, 8))

    def test_scale_is_hard_clamped(self):
        self.assertEqual(rr.scale_colour((255, 255, 255), 1000), rr.scale_colour((255, 255, 255), HARD))
        self.assertEqual(rr.clamp_scale(5000), HARD)
        self.assertEqual(rr.clamp_scale(-5), 0)

    def test_hex_validation(self):
        for bad in ("F0F5F1", "#FFF", "#GGGGGG", "", None):
            with self.assertRaises(ValueError):
                rr.parse_hex(bad)


class PanelOrigins(unittest.TestCase):
    PIX = [(0, 0), (63, 31), (10, 1)]

    def test_origin_0(self):
        buf = rr.compose((mask_with(*self.PIX), EMPTY, EMPTY), ["#FFFFFF"] * 3, HARD, origin=0)
        self.assertEqual((len(buf), len(buf[0])), (32, 128))
        self.assertEqual(rr.lit_columns(buf), {0, 63, 10})
        self.assertNotEqual(buf[0][0], rr.BLACK)
        self.assertNotEqual(buf[31][63], rr.BLACK)

    def test_origin_64(self):
        buf = rr.compose((mask_with(*self.PIX), EMPTY, EMPTY), ["#FFFFFF"] * 3, HARD, origin=64)
        self.assertEqual(rr.lit_columns(buf), {64, 127, 74})
        self.assertTrue(all(px == rr.BLACK for row in buf for px in row[:64]))

    def test_single_panel_mode(self):
        buf = rr.compose((mask_with(*self.PIX), EMPTY, EMPTY), ["#FFFFFF"] * 3, HARD, origin=0, mode=rr.SINGLE)
        self.assertEqual((len(buf), len(buf[0])), (32, 64))
        self.assertEqual(rr.lit_columns(buf), {0, 63, 10})
        with self.assertRaises(ValueError):
            rr.compose((EMPTY,) * 3, ["#FFFFFF"] * 3, HARD, origin=64, mode=rr.SINGLE)

    def test_bad_origin_rejected(self):
        for o in (1, 32, 63, 65, 128, -1):
            with self.assertRaises(ValueError):
                rr.compose((EMPTY,) * 3, ["#FFFFFF"] * 3, HARD, origin=o)

    def test_blackout_is_entirely_black(self):
        m = mask_with(*self.PIX)
        for origin in (0, 64):
            buf = rr.compose((m, m, m), ["#FFFFFF"] * 3, HARD, origin=origin, blackout=True)
            self.assertEqual(rr.lit_columns(buf), set())


class LayerOrderAndColour(unittest.TestCase):
    COL = ["#F0F5F1", "#FFB34F", "#75CAFF"]

    def test_later_layers_overwrite(self):
        a = mask_with((5, 5), (6, 6), (7, 7))
        b = mask_with((6, 6), (7, 7))
        fx = mask_with((7, 7))
        buf = rr.compose((a, b, fx), self.COL, HARD, origin=0)
        ca, cb, cf = (rr.scale_colour(rr.parse_hex(c), HARD) for c in self.COL)
        self.assertEqual(buf[5][5], ca)
        self.assertEqual(buf[6][6], cb)  # B over A
        self.assertEqual(buf[7][7], cf)  # effects over B over A

    def test_unique_lit_count_counts_overlap_once(self):
        a = mask_with((1, 1), (2, 2))
        b = mask_with((2, 2), (3, 3))
        self.assertEqual(rr.unique_lit_count(a, b, mask_with((3, 3), (4, 4))), 4)

    def test_independent_colours(self):
        buf = rr.compose((mask_with((0, 0)), mask_with((1, 0)), mask_with((2, 0))), self.COL, HARD, origin=64)
        self.assertEqual({buf[0][64], buf[0][65], buf[0][66]}, {rr.scale_colour(rr.parse_hex(c), HARD) for c in self.COL})


class WholeLibrary(unittest.TestCase):
    """Run every one of the 624 frames through both origins."""

    @classmethod
    def setUpClass(cls):
        cls.reactions, _ = pa.load_and_validate(pa.DEFAULT_SRC)

    def test_no_leak_into_reserved_half_and_coverage_cap(self):
        n = 0
        for r in self.reactions:
            for dur, a, b, fx in r["frames"]:
                lit = rr.unique_lit_count(a, b, fx)
                self.assertLessEqual(lit, 281)
                for origin, reserved in ((0, range(64, 128)), (64, range(0, 64))):
                    buf = rr.compose((a, b, fx), ["#FFFFFF"] * 3, HARD, origin=origin)
                    cols = rr.lit_columns(buf)
                    self.assertFalse(cols & set(reserved), "%s leaks into reserved panel" % r["id"])
                    lit_px = sum(1 for row in buf for px in row if px != rr.BLACK)
                    self.assertEqual(lit_px, lit, r["id"])
                n += 1
        self.assertEqual(n, 624)

    def test_idle_first_frame_golden(self):
        # Locked values from the canonical source; a change here means the sprite changed.
        _, a, b, fx = self.reactions[0]["frames"][0]
        self.assertEqual(self.reactions[0]["id"], "idle")
        self.assertEqual((len(rr.lit_set(a)), len(rr.lit_set(b)), len(rr.lit_set(fx))), GOLDEN_IDLE0)
        for m in (a, b):
            xs = [x for x, _ in rr.lit_set(m)]
            ys = [y for _, y in rr.lit_set(m)]
            self.assertEqual((max(xs) - min(xs) + 1, max(ys) - min(ys) + 1), GOLDEN_SHEEP_BBOX)


# Measured once from the canonical source (idle frame 0): 96 + 96 sheep pixels, no effects.
GOLDEN_IDLE0 = (96, 96, 0)
GOLDEN_SHEEP_BBOX = (17, 16)  # width, height of the original sheep outline


if __name__ == "__main__":
    unittest.main()
