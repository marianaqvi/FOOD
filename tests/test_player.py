"""Host tests for firmware/renderer.py and firmware/player.py against a fake display.

These prove the software logic only: pixel parity with the CPU reference renderer, safety limits,
scheduling, error handling. They model no electricity and no real HUB75 timing.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

import _paths  # noqa: F401
import fake_board
import reference_renderer as rr

REPO = _paths.REPO
FW = os.path.join(REPO, "firmware")
if FW not in sys.path:
    sys.path.insert(0, FW)

import fallback  # noqa: E402
import player as player_mod  # noqa: E402
import power  # noqa: E402
import renderer as renderer_mod  # noqa: E402

ASSETS = os.path.join(FW, "assets")
RECORD = 770
COLOURS = ("#F0F5F1", "#FFB34F", "#75CAFF")  # distinct per layer so overwrite order is visible
BLACK = (0, 0, 0)


def make_i75(mode):
    fake, _ = fake_board.make_module()
    name = "DISPLAY_INTERSTATE75_64X32" if mode == "single" else "DISPLAY_INTERSTATE75_128X32"
    return fake.Interstate75(display=name)


def make_renderer(mode="single", origin=0, permille=power.DEFAULT_PERMILLE, colours=COLOURS):
    i75 = make_i75(mode)
    return renderer_mod.Renderer(i75, i75.display, mode, origin, permille, colours), i75


def records(reaction_id):
    with open(os.path.join(ASSETS, reaction_id + ".bin"), "rb") as fh:
        data = fh.read()
    assert len(data) % RECORD == 0
    return [data[i:i + RECORD] for i in range(0, len(data), RECORD)]


def reference_lit(rec, mode, origin, permille=power.DEFAULT_PERMILLE, colours=COLOURS):
    masks = (rec[2:258], rec[258:514], rec[514:770])
    buf = rr.compose(masks, colours, permille, origin=origin, mode=mode)
    return {(x, y): px for y, row in enumerate(buf) for x, px in enumerate(row) if px != BLACK}


def assert_snapshots_safe(tc, i75):
    for s in i75.snapshots:
        tc.assertEqual(s.fill, BLACK, "buffer must be cleared with a black pen")
        lit = s.lit()
        tc.assertLessEqual(len(lit), power.MAX_LIT_PIXELS)
        for rgb in lit.values():
            tc.assertLessEqual(max(rgb), power.MAX_CHANNEL)


class RendererParity(unittest.TestCase):
    def check_all_frames(self, mode, origin, permille=power.DEFAULT_PERMILLE):
        with open(os.path.join(ASSETS, "manifest.json")) as fh:
            ids = [r["id"] for r in json.load(fh)["reactions"]]
        self.assertEqual(len(ids), 18)
        rend, i75 = make_renderer(mode, origin, permille)
        n = 0
        for rid in ids:
            for rec in records(rid):
                lit = rend.draw(rec)
                snap = i75.snapshots[-1]
                want = reference_lit(rec, mode, origin, permille)
                self.assertEqual(snap.lit(), want, "%s frame %d" % (rid, n))
                self.assertEqual(lit, len(want))
                if mode == "chained":
                    cols = {x for x, _ in snap.lit()}
                    reserved = range(64, 128) if origin == 0 else range(0, 64)
                    self.assertFalse(cols & set(reserved), "reserved half must stay black")
                n += 1
        self.assertEqual(n, 624)
        self.assertEqual(len(i75.snapshots), 624, "exactly one update per frame")
        assert_snapshots_safe(self, i75)

    def test_all_624_frames_single_panel(self):
        self.check_all_frames("single", 0)

    def test_all_624_frames_single_panel_at_run_scale(self):
        self.check_all_frames("single", 0, power.RUN_PERMILLE)

    def test_all_624_frames_chained_origin_0(self):
        self.check_all_frames("chained", 0)

    def test_all_624_frames_chained_origin_64(self):
        self.check_all_frames("chained", 64)

    def test_layer_overwrite_order_a_then_b_then_effects(self):
        rend, i75 = make_renderer("single")
        rec = bytearray(RECORD)
        rec[0] = 150
        rec[2] |= 0x80  # A at (0,0)
        rec[2 + 1] |= 0x80  # A at (8,0)
        rec[258] |= 0x80 | 0x40  # B at (0,0) and (1,0)
        rec[514] |= 0x80 | 0x20  # effects at (0,0) and (2,0)
        rend.draw(bytes(rec))
        lit = i75.snapshots[-1].lit()
        a, b, fx = rend.rgbs
        self.assertEqual(lit[(0, 0)], fx)  # all three: effects wins
        self.assertEqual(lit[(1, 0)], b)
        self.assertEqual(lit[(2, 0)], fx)
        self.assertEqual(lit[(8, 0)], a)
        self.assertEqual(len(lit), 4)

    def test_scale_is_hard_clamped_even_if_asked_for_more(self):
        rend, i75 = make_renderer("single", permille=1000)
        self.assertEqual(rend.permille, power.HARD_MAX_PERMILLE)
        rend.draw(records("idle")[0])
        for rgb in i75.snapshots[-1].lit().values():
            self.assertLessEqual(max(rgb), power.MAX_CHANNEL)
        self.assertLessEqual(power.RUN_PERMILLE, power.HARD_MAX_PERMILLE)

    def test_constructor_rejects_bad_geometry(self):
        i75 = make_i75("single")
        with self.assertRaises(ValueError):
            renderer_mod.Renderer(i75, i75.display, "single", 64)
        with self.assertRaises(ValueError):
            renderer_mod.Renderer(i75, i75.display, "chained", 0)  # 64-wide display
        i75c = make_i75("chained")
        with self.assertRaises(ValueError):
            renderer_mod.Renderer(i75c, i75c.display, "chained", 32)
        with self.assertRaises(ValueError):
            renderer_mod.Renderer(i75c, i75c.display, "single", 0)  # 128-wide display
        with self.assertRaises(ValueError):
            renderer_mod.Renderer(i75c, i75c.display, "weird", 0)


class SharedLimits(unittest.TestCase):
    def test_player_constants_agree_with_shared_limits(self):
        lim = rr.LIMITS
        self.assertEqual(player_mod.SPEED_MIN, int(lim["speed"]["min"] * 1000))
        self.assertEqual(player_mod.SPEED_MAX, int(lim["speed"]["max"] * 1000))
        self.assertEqual(player_mod.MAX_CYCLES, lim["cycles"]["max"])
        self.assertEqual(player_mod.MAX_HOLD_MS, lim["hold_max_seconds"] * 1000)
        self.assertEqual(lim["cycles"]["min"], 1)


class RendererLimits(unittest.TestCase):
    def test_frame_over_281_distinct_pixels_is_replaced_by_black(self):
        rend, i75 = make_renderer("single")
        rec = bytearray(RECORD)
        rec[0] = 150
        for i in range(37):  # 296 pixels in sheep A
            rec[2 + i] = 0xFF
        self.assertEqual(rend.draw(bytes(rec)), 0)
        self.assertEqual(i75.snapshots[-1].lit(), {})
        self.assertEqual(rend.rejected, 1)

    def test_exactly_281_pixels_is_allowed(self):
        rend, i75 = make_renderer("single")
        rec = bytearray(RECORD)
        for i in range(35):  # 280 pixels
            rec[2 + i] = 0xFF
        rec[2 + 35] = 0x80  # 281st
        self.assertEqual(rend.draw(bytes(rec)), 281)

    def test_overlapping_layers_count_distinct_pixels_once(self):
        rend, i75 = make_renderer("single")
        rec = bytearray(RECORD)
        for i in range(35):
            rec[2 + i] = 0xFF
            rec[258 + i] = 0xFF  # same 280 pixels again in B
        rec[514] = 0xFF  # inside the same region
        self.assertEqual(rend.draw(bytes(rec)), 280)

    def test_frame_budget_blanks_the_frame(self):
        rend, i75 = make_renderer("single")
        rend.frame_budget = 10
        self.assertEqual(rend.draw(records("idle")[0]), 0)
        self.assertEqual(i75.snapshots[-1].lit(), {})
        self.assertEqual(rend.rejected, 1)

    def test_default_budget_equals_product_of_other_limits(self):
        self.assertEqual(power.FRAME_BUDGET, power.MAX_LIT_PIXELS * 3 * power.MAX_CHANNEL)

    def test_blackout_draws_black_every_time(self):
        rend, i75 = make_renderer("chained", 64)
        rend.set_blackout(True)
        for rec in records("birthday"):
            rend.draw(rec)
        self.assertTrue(all(s.lit() == {} for s in i75.snapshots))
        rend.set_blackout(False)
        rend.draw(records("birthday")[5])
        self.assertTrue(i75.snapshots[-1].lit())

    def test_short_record_is_refused_black(self):
        rend, i75 = make_renderer("single")
        self.assertEqual(rend.draw(b"\x00" * 100), 0)
        self.assertEqual(i75.snapshots[-1].lit(), {})

    def test_update_signature_fallback(self):
        fake, _ = fake_board.make_module(update_needs_arg=True)
        i75 = fake.Interstate75(display="DISPLAY_INTERSTATE75_64X32")
        rend = renderer_mod.Renderer(i75, i75.display, "single", 0)
        rend.draw(records("idle")[0])
        self.assertEqual(len(i75.snapshots), 1)


class FakeTime:
    """Drives player.Clock deterministically."""

    def __init__(self, start=0, period=1 << 30):
        self.t = start
        self.period = period
        self.clock = player_mod.Clock(now_fn=lambda: self.t, period=period)


class TrackingOpener:
    def __init__(self):
        self.open_now = 0
        self.max_open = 0
        self.total = 0

    def __call__(self, path, mode="r"):
        fh = open(path, mode)
        tracker = self
        orig_close = fh.close

        class Wrapper:
            def __init__(self):
                tracker.open_now += 1
                tracker.total += 1
                tracker.max_open = max(tracker.max_open, tracker.open_now)
                self.closed = False

            def readinto(self, b):
                return fh.readinto(b)

            def seek(self, n):
                return fh.seek(n)

            def read(self, *a):
                return fh.read(*a)

            def close(self):
                if not self.closed:
                    self.closed = True
                    tracker.open_now -= 1
                    orig_close()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()

        return Wrapper()


class PlayerBase(unittest.TestCase):
    assets = ASSETS

    def setUp(self):
        self.rend, self.i75 = make_renderer("single")
        self.time = FakeTime()
        self.logs = []
        self.opener = TrackingOpener()
        self.p = player_mod.Player(self.rend, self.assets, clock=self.time.clock, log=self.logs.append,
                                   opener=self.opener)

    def tearDown(self):
        self.p.close()

    def run_ms(self, ms, step=10):
        """Tick every `step` ms; return the list of (time, reaction) at each drawn frame."""
        out = []
        end = self.time.t + ms
        while self.time.t < end:
            if self.p.tick():
                out.append((self.time.t, self.p.cur))
            self.time.t += step
        return out


class PlayerScheduling(PlayerBase):
    def test_load_validates_everything_and_streams_one_file_at_a_time(self):
        self.assertTrue(self.p.load(verify_crc=True))
        self.assertEqual(len(self.p.available()), 18)
        self.assertIsNone(self.p.fault)
        self.run_ms(2000)
        self.assertEqual(self.opener.max_open, 1)
        self.p.close()
        self.assertEqual(self.opener.open_now, 0)

    def test_idle_loops_forever_at_150ms(self):
        self.p.load()
        draws = self.run_ms(20000)
        self.assertTrue(all(r == "idle" for _, r in draws))
        times = [t for t, _ in draws]
        self.assertEqual(times[:4], [0, 150, 300, 450])
        self.assertTrue(all(b - a == 150 for a, b in zip(times, times[1:])))
        self.assertEqual(len(draws), 20000 // 150 + 1)
        assert_snapshots_safe(self, self.i75)

    def test_tick_is_nonblocking_and_draws_only_when_due(self):
        self.p.load()
        self.assertTrue(self.p.tick())
        before = len(self.i75.snapshots)
        for _ in range(20):
            self.time.t += 5
            self.assertFalse(self.p.tick())
        self.assertEqual(len(self.i75.snapshots), before)

    def test_manual_reaction_plays_once_then_returns_to_idle(self):
        self.p.load()
        n = self.p.frames["wave"]
        self.assertTrue(self.p.play("wave"))
        draws = self.run_ms(n * 150 + 1000)
        names = [r for _, r in draws]
        self.assertEqual(names[:n], ["wave"] * n)
        self.assertTrue(all(r == "idle" for r in names[n:]))
        self.assertEqual(self.p.status()["reaction"], "idle")

    def test_cycles(self):
        self.p.load()
        n = self.p.frames["wave"]
        self.p.play("wave", cycles=3)
        names = [r for _, r in self.run_ms(3 * n * 150 + 600)]
        self.assertEqual(names[:3 * n], ["wave"] * (3 * n))
        self.assertEqual(names[3 * n], "idle")

    def test_speed_is_clamped_to_half_to_one(self):
        self.p.load()
        self.p.play("wave", speed_permille=2000)  # faster than allowed -> 1x
        t1 = [t for t, _ in self.run_ms(1000)]
        self.assertEqual(t1[1] - t1[0], 150)
        self.p.play("wave", speed_permille=100)  # slower than allowed -> 0.5x
        t2 = [t for t, _ in self.run_ms(1500)]
        self.assertEqual(t2[1] - t2[0], 300)
        self.p.play("wave", speed_permille=500)
        t3 = [t for t, _ in self.run_ms(1500)]
        self.assertEqual(t3[1] - t3[0], 300)

    def test_cycles_are_bounded(self):
        self.p.load()
        self.p.play("wave", cycles=10 ** 6)
        self.assertEqual(self.p.cycles, player_mod.MAX_CYCLES)
        self.p.play("wave", cycles=-5)
        self.assertEqual(self.p.cycles, 1)

    def test_hold_loops_until_stop_which_takes_priority(self):
        self.p.load()
        n = self.p.frames["dance"]
        self.p.play("dance", hold=True)
        names = [r for _, r in self.run_ms(3 * n * 150)]
        self.assertTrue(all(r == "dance" for r in names))
        self.p.stop()
        self.assertEqual(self.p.cur, "idle")
        draws = self.run_ms(500)
        self.assertEqual(draws[0][1], "idle")

    def test_hold_expires_by_itself(self):
        self.p.load()
        self.p.play("dance", hold=True)
        self.time.t += player_mod.MAX_HOLD_MS + 1000
        self.p.tick()  # hold clock check happens at end of the next cycle
        names = [r for _, r in self.run_ms(2 * self.p.frames["dance"] * 150)]
        self.assertIn("idle", names)

    def test_unknown_reaction_is_refused_and_changes_nothing(self):
        self.p.load()
        self.run_ms(300)
        self.assertFalse(self.p.play("../../etc/passwd"))
        self.assertFalse(self.p.play("nope"))
        self.assertEqual(self.p.cur, "idle")

    def test_same_reaction_again_restarts_from_frame_zero(self):
        self.p.load()
        self.p.play("wave")
        self.run_ms(150 * 10)
        self.assertGreater(self.p.frame, 5)
        self.p.play("wave")
        self.run_ms(10)
        self.assertEqual(self.p.frame, 1)

    def test_wrap_safe_across_the_tick_counter_wrapping(self):
        self.time = FakeTime(start=(1 << 30) - 1000)
        self.p = player_mod.Player(self.rend, ASSETS, clock=self.time.clock, log=self.logs.append, opener=self.opener)
        self.p.load()
        draws = self.run_ms(5000)
        times = [t for t, _ in draws]
        self.assertGreater(max(times), 1 << 30)  # raw counter went past the wrap
        self.assertTrue(all(b - a == 150 for a, b in zip(times, times[1:])))

    def test_falling_behind_resyncs_instead_of_bursting(self):
        self.p.load()
        self.p.tick()
        self.time.t += 5000  # a long stall, e.g. a slow network call elsewhere
        n = len(self.i75.snapshots)
        self.assertTrue(self.p.tick())
        self.assertFalse(self.p.tick())  # not due again until a full frame later
        self.assertEqual(len(self.i75.snapshots), n + 1)

    def test_blackout_keeps_running_and_stays_black(self):
        self.p.load()
        self.p.set_blackout(True)
        self.run_ms(2000)
        self.assertTrue(all(s.lit() == {} for s in self.i75.snapshots))
        self.p.set_blackout(False)
        self.run_ms(400)
        self.assertTrue(self.i75.snapshots[-1].lit())

    def test_every_frame_of_every_reaction_played_by_the_player_is_safe(self):
        self.p.load()
        for rid in self.p.available():
            self.p.play(rid)
            self.run_ms(self.p.frames[rid] * 150 + 150)
        assert_snapshots_safe(self, self.i75)


class PlayerFaults(PlayerBase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.assets = os.path.join(self.tmp, "assets")
        shutil.copytree(ASSETS, self.assets)
        super().setUp()
        self.p = player_mod.Player(self.rend, self.assets, clock=self.time.clock, log=self.logs.append,
                                   opener=self.opener)

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmp)

    def expected_fallback(self):
        return reference_lit(fallback.RECORD, "single", 0)

    def test_fallback_is_idle_record_zero_byte_for_byte(self):
        self.assertEqual(fallback.RECORD, records("idle")[0])
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        mf = importlib.import_module("make_fallback")
        with open(os.path.join(FW, "fallback.py")) as fh:
            self.assertEqual(fh.read(), mf.render(), "run scripts/make_fallback.py")

    def test_missing_manifest_shows_fallback_not_a_crash(self):
        os.remove(os.path.join(self.assets, "manifest.json"))
        self.assertFalse(self.p.load())
        self.assertIsNotNone(self.p.fault)
        self.run_ms(3000)
        self.assertTrue(all(s.lit() == self.expected_fallback() for s in self.i75.snapshots))
        self.assertFalse(self.p.play("wave"))

    def test_garbage_manifest_shows_fallback(self):
        with open(os.path.join(self.assets, "manifest.json"), "w") as fh:
            fh.write("{not json")
        self.assertFalse(self.p.load())
        self.run_ms(1500)
        self.assertEqual(self.i75.snapshots[-1].lit(), self.expected_fallback())

    def test_missing_idle_file_shows_fallback(self):
        os.remove(os.path.join(self.assets, "idle.bin"))
        self.assertFalse(self.p.load())
        self.run_ms(1500)
        self.assertEqual(self.i75.snapshots[-1].lit(), self.expected_fallback())

    def test_truncated_reaction_is_refused_but_idle_keeps_playing(self):
        path = os.path.join(self.assets, "sleep.bin")
        with open(path, "r+b") as fh:
            fh.truncate(os.path.getsize(path) - 100)
        self.assertTrue(self.p.load())
        self.assertEqual(self.p.bad["sleep"], "wrong size")
        self.assertFalse(self.p.play("sleep"))
        self.assertTrue(self.p.play("wave"))
        self.assertEqual(len(self.p.available()), 17)

    def test_checksum_mismatch_only_found_when_verifying(self):
        path = os.path.join(self.assets, "morph.bin")
        with open(path, "r+b") as fh:
            fh.seek(100)
            b = fh.read(1)
            fh.seek(100)
            fh.write(bytes([b[0] ^ 0xFF]))
        self.assertTrue(self.p.load(verify_crc=False))
        self.assertIn("morph", self.p.frames)
        self.assertTrue(self.p.load(verify_crc=True))
        self.assertEqual(self.p.bad["morph"], "checksum mismatch")
        self.assertFalse(self.p.play("morph"))

    def test_file_that_shrinks_after_load_drops_back_to_idle_without_crashing(self):
        self.assertTrue(self.p.load())
        self.p.play("wave")
        self.run_ms(300)
        path = os.path.join(self.assets, "wave.bin")
        with open(path, "r+b") as fh:
            fh.truncate(RECORD * 3 + 100)  # now ends mid-record
        self.p.play("wave")
        self.run_ms(150 * 10)
        self.assertEqual(self.p.cur, "idle")
        self.assertNotIn("wave", self.p.available())
        self.assertIsNone(self.p.fault)
        assert_snapshots_safe(self, self.i75)

    def test_idle_file_that_shrinks_after_load_falls_back(self):
        self.assertTrue(self.p.load())
        self.run_ms(300)
        with open(os.path.join(self.assets, "idle.bin"), "r+b") as fh:
            fh.truncate(RECORD * 3 + 5)
        self.p.stop()  # reopen idle
        self.run_ms(150 * 6)
        self.assertIsNotNone(self.p.fault)
        self.assertEqual(self.i75.snapshots[-1].lit(), self.expected_fallback())

    def test_manifest_with_path_traversal_name_is_ignored(self):
        mpath = os.path.join(self.assets, "manifest.json")
        with open(mpath) as fh:
            man = json.load(fh)
        man["reactions"][1]["file"] = "../evil.bin"
        with open(mpath, "w") as fh:
            json.dump(man, fh)
        self.assertTrue(self.p.load())
        self.assertEqual(self.p.bad[man["reactions"][1]["id"]], "unexpected file name")


if __name__ == "__main__":
    unittest.main()
