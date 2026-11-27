"""Host-side tests of firmware/power.py, firmware/hwtest_common.py and firmware/tools/hw*.py.

These run the real scripts against tests/fake_board.py. They check the safety logic (gate,
pixel count, clamp, blanking) and nothing electrical. Hardware results are recorded
separately in docs/test-log.md.
"""
import contextlib
import importlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

import _paths  # noqa: F401
import fake_board  # noqa: F401  (tests/ is on sys.path when run via discover -s tests)
import reference_renderer as rr

REPO = _paths.REPO
for sub in ("firmware", os.path.join("firmware", "tools")):
    p = os.path.join(REPO, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import power  # noqa: E402

TOOLS = os.path.join(REPO, "firmware", "tools")


def load_script(name, update_needs_arg=False):
    """Import a script fresh with a fake interstate75 installed. Returns (module, instances)."""
    fake, instances = fake_board.make_module(update_needs_arg)
    sys.modules["interstate75"] = fake
    for n in ("hwtest_common", name):
        sys.modules.pop(n, None)
    return importlib.import_module(name), instances


def run_quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **k)
    return out, buf.getvalue()


class PowerModule(unittest.TestCase):
    def test_limits_agree_with_shared_limits_json(self):
        with open(os.path.join(REPO, "shared", "limits.json")) as f:
            lim = json.load(f)
        self.assertEqual(power.HARD_MAX_PERMILLE, lim["rgb_scale"]["hard_max_permille"])
        self.assertEqual(power.DEFAULT_PERMILLE, lim["rgb_scale"]["default_permille"])
        self.assertEqual(power.MAX_LIT_PIXELS, lim["max_lit_habitat_pixels"])
        self.assertEqual((power.HABITAT_W, power.HABITAT_H), (lim["habitat"]["width"], lim["habitat"]["height"]))
        self.assertEqual(list(power.ALLOWED_ORIGINS), lim["allowed_habitat_origins"])

    def test_scaling_matches_reference_renderer(self):
        for rgb in [(0xF0, 0xF5, 0xF1), (0xFF, 0xB3, 0x4F), (255, 255, 255), (0, 0, 0), (1, 5, 9)]:
            for p in (0, 37, 100, 500, 1000):
                self.assertEqual(power.scale_rgb(rgb, p), rr.scale_colour(rgb, p), (rgb, p))

    def test_hard_clamp(self):
        self.assertEqual(power.clamp_permille(99999), power.HARD_MAX_PERMILLE)
        self.assertEqual(power.clamp_permille(-5), 0)
        self.assertEqual(power.MAX_CHANNEL, 51)
        self.assertEqual(max(power.scale_rgb((255, 255, 255), 1000)), power.MAX_CHANNEL)

    def test_parse_hex(self):
        self.assertEqual(power.parse_hex("#F0F5F1"), (240, 245, 241))
        for bad in ("F0F5F1", "#F0F5F", "#F0F5F1F", 5, None):
            with self.assertRaises(ValueError):
                power.parse_hex(bad)


class Gate(unittest.TestCase):
    NAMES = ["hw10_sparse_pixel", "hw11_colour_order", "hw12_panel_order"]

    def test_scripts_committed_with_gate_closed(self):
        for n in self.NAMES:
            with open(os.path.join(TOOLS, n + ".py")) as f:
                src = f.read()
            self.assertRegex(src, r"(?m)^I_HAVE_CHECKED_POWER_AND_WIRING = False$", n)

    def test_refuses_and_never_touches_display_when_gate_closed(self):
        for n in self.NAMES:
            mod, instances = load_script(n)
            out, text = run_quiet(mod.main, sleep=lambda s: None)
            self.assertIs(out, False, n)
            self.assertIn("REFUSED", text)
            self.assertEqual(instances, [], n + " constructed a display while gated")

    def test_truthy_but_not_true_still_refuses(self):
        mod, instances = load_script("hw10_sparse_pixel")
        mod.I_HAVE_CHECKED_POWER_AND_WIRING = 1
        out, _ = run_quiet(mod.main, sleep=lambda s: None)
        self.assertIs(out, False)
        self.assertEqual(instances, [])


def open_gate(name, **kw):
    mod, instances = load_script(name, **kw)
    mod.I_HAVE_CHECKED_POWER_AND_WIRING = True
    sleeps = []
    out, text = run_quiet(mod.main, sleep=sleeps.append)
    assert out is True, text
    return instances[0], sleeps


def assert_always_safe(tc, i75):
    """Every frame ever sent: black fill, only sparse pixels, no channel over the hard limit,
    and the final frame is completely black."""
    tc.assertGreaterEqual(len(i75.snapshots), 2)
    for s in i75.snapshots:
        tc.assertEqual(s.fill, (0, 0, 0))
        lit = s.lit()
        tc.assertLessEqual(len(lit), 8)
        for rgb in lit.values():
            tc.assertLessEqual(max(rgb), power.MAX_CHANNEL)
    tc.assertEqual(i75.snapshots[-1].lit(), {})


class SparsePixel(unittest.TestCase):
    def test_one_pixel_at_default_scale_then_black(self):
        i75, sleeps = open_gate("hw10_sparse_pixel")
        self.assertEqual((i75.display.w, i75.display.h), (64, 32))
        lit = [s.lit() for s in i75.snapshots if s.lit()]
        self.assertEqual(lit, [{(32, 16): (24, 25, 24)}])
        self.assertEqual(sleeps, [10])
        assert_always_safe(self, i75)


class ColourOrder(unittest.TestCase):
    def test_red_green_blue_left_to_right(self):
        i75, _ = open_gate("hw11_colour_order")
        lit = [s.lit() for s in i75.snapshots if s.lit()]
        self.assertEqual(lit, [{(16, 16): (26, 0, 0), (32, 16): (0, 26, 0), (48, 16): (0, 0, 26)}])
        assert_always_safe(self, i75)


class PanelOrder(unittest.TestCase):
    def test_markers_in_each_half_and_chained_size(self):
        i75, _ = open_gate("hw12_panel_order")
        self.assertEqual((i75.display.w, i75.display.h), (128, 32))
        lit = [s.lit() for s in i75.snapshots if s.lit()]
        self.assertEqual(len(lit), 1)
        self.assertEqual(sorted(lit[0]), [(2, 2), (2, 4), (66, 2), (68, 2)])
        self.assertEqual(sum(1 for (x, _y) in lit[0] if x < 64), 2)
        self.assertEqual(sum(1 for (x, _y) in lit[0] if x >= 64), 2)
        assert_always_safe(self, i75)


class ShowSafety(unittest.TestCase):
    def setUp(self):
        load_script("hw10_sparse_pixel")  # installs fake + fresh hwtest_common
        self.hw = sys.modules["hwtest_common"]
        self.i75, self.gfx = self.hw.open_display("single")

    def test_rejects_too_many_pixels(self):
        px = [(x, 1, (1, 1, 1)) for x in range(9)]
        with self.assertRaises(ValueError):
            self.hw.show(self.i75, self.gfx, px, 1, lambda s: None)
        self.assertEqual(self.i75.snapshots, [])  # rejected before anything was lit

    def test_rejects_over_limit_channel_and_out_of_bounds(self):
        for px in ([(1, 1, (255, 255, 255))], [(1, 1, (27, 0, 0))], [(64, 1, (1, 1, 1))], [(1, -1, (1, 1, 1))]):
            with self.assertRaises(ValueError):
                self.hw.show(self.i75, self.gfx, px, 1, lambda s: None)
        self.assertEqual(self.i75.snapshots, [])

    def test_blanks_even_when_interrupted(self):
        def stop(_s):
            raise KeyboardInterrupt  # what Thonny's Stop button raises on the board

        with self.assertRaises(KeyboardInterrupt):
            self.hw.show(self.i75, self.gfx, [(5, 5, (24, 25, 24))], 10, stop)
        self.assertEqual(self.i75.snapshots[-1].lit(), {})
        self.assertEqual(self.i75.snapshots[-1].fill, (0, 0, 0))

    def test_duration_is_bounded(self):
        got = []
        self.hw.show(self.i75, self.gfx, [(5, 5, (1, 1, 1))], 9999, got.append)
        self.assertEqual(got, [self.hw.MAX_SECONDS])

    def test_update_signature_fallback(self):
        mod, instances = load_script("hw10_sparse_pixel", update_needs_arg=True)
        mod.I_HAVE_CHECKED_POWER_AND_WIRING = True
        out, _ = run_quiet(mod.main, sleep=lambda s: None)
        self.assertIs(out, True)
        assert_always_safe(self, instances[0])


class Inspect(unittest.TestCase):
    def test_inspection_lights_nothing_and_reports_key_facts(self):
        for mode, bounds in (("chained", "(128, 32)"), ("single", "(64, 32)")):
            mod, instances = load_script("hw00_inspect")
            mod.BLANK_UPDATES = 3
            mod.MODE = mode
            _, text = run_quiet(mod.main)
            self.assertIn("import interstate75: ok", text)
            self.assertIn("DISPLAY_INTERSTATE75_128X32 present", text)
            self.assertIn("%s bounds: %s" % (mode, bounds), text)
            self.assertIn("nothing was lit", text)
            # exactly ONE display per run: a second construct hung the real board
            self.assertEqual(len(instances), 1)
            for s in instances[0].snapshots:
                self.assertEqual(s.lit(), {})

    def test_missing_module_is_reported_not_crashed(self):
        sys.modules.pop("interstate75", None)
        sys.modules["interstate75"] = None  # makes `import interstate75` raise ImportError
        sys.modules.pop("hw00_inspect", None)
        mod = importlib.import_module("hw00_inspect")
        _, text = run_quiet(mod.main)
        self.assertIn("import interstate75: FAILED", text)
        self.assertIn("Do NOT flash", text)
        sys.modules.pop("interstate75", None)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- stage runner (main.py)
class RunnerHarness:
    """Drives firmware/tools/stage_runner_main.py's Runner with a fake clock and fake buttons."""

    def __init__(self, variant=None):
        fake, self.instances = fake_board.make_module()
        sys.modules["interstate75"] = fake
        for n in ("hwtest_common", "stage_runner_main"):
            sys.modules.pop(n, None)
        self.mod = importlib.import_module("stage_runner_main")
        hw = sys.modules["hwtest_common"]
        if variant is None:
            self.i75, self.gfx = hw.open_display("chained")  # the stage tests below need both halves
        else:
            mode, setup = hw.variant_parts(variant)
            self.i75, self.gfx = hw.open_display(mode, setup)
        self.t = 0
        self.logs = []
        self.runner = self.mod.Runner(
            self.i75, self.gfx, 0, 1, now=lambda: self.t, sleep_ms=self._sleep, log=self.logs.append,
            variant=variant or 1,
        )
        self.on_sleep = None  # optional hook called on every runner sleep (for abort tests)

    def _sleep(self, ms):
        self.t += ms
        if self.on_sleep:
            self.on_sleep()

    def hold(self, a, b, ms):
        self.i75.buttons[0], self.i75.buttons[1] = a, b
        end = self.t + ms
        while self.t < end:
            self.runner.tick()
            self.t += 20

    def release(self, ms=100):
        self.hold(False, False, ms)

    def arm(self):
        self.hold(True, True, 3100)
        self.release()

    def run_a(self, ms=1100):
        self.hold(True, False, ms)
        self.release()

    def lit_frames(self):
        return [s.lit() for s in self.i75.snapshots if s.lit()]


class StageRunner(unittest.TestCase):
    def test_boot_is_black_and_disarmed_and_unarmed_run_is_refused(self):
        h = RunnerHarness()
        h.release(500)
        h.run_a()
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("REFUSED" in l for l in h.logs))
        self.assertEqual(h.i75.led, h.mod.BLUE)

    def test_arm_needs_three_seconds(self):
        h = RunnerHarness()
        h.hold(True, True, 2900)
        h.release()
        h.run_a()
        self.assertEqual(h.lit_frames(), [])
        self.assertFalse(any("ARMED" in l for l in h.logs))

    def test_armed_stage_one_lights_one_pixel_then_black_and_disarms(self):
        h = RunnerHarness()
        h.arm()
        self.assertTrue(any("ARMED" in l for l in h.logs))
        h.run_a()
        self.assertEqual(h.lit_frames(), [{(32, 16): (24, 25, 24)}])
        assert_always_safe(self, h.i75)
        self.assertEqual(h.i75.led, h.mod.BLUE)
        n = len(h.lit_frames())
        h.run_a()  # a second run without re-arming must be refused
        self.assertEqual(len(h.lit_frames()), n)

    def test_arm_window_expires(self):
        h = RunnerHarness()
        h.arm()
        h.hold(False, False, 61000)
        h.run_a()
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("expired" in l for l in h.logs))

    def test_b_tap_cycles_stages_and_each_runs_the_shared_definition(self):
        hw = None
        for expect_stage in (2, 3):  # stage 4 has its own test below
            h = RunnerHarness()
            for _ in range(expect_stage - 1):
                h.hold(False, True, 100)
                h.release()
            self.assertEqual(h.runner.stage, expect_stage)
            h.arm()
            h.run_a()
            hw = sys.modules["hwtest_common"]
            want = {(x, y): rgb for x, y, rgb in hw.stage_pixels(expect_stage)[0]}
            self.assertEqual(h.lit_frames(), [want])
            assert_always_safe(self, h.i75)
        h = RunnerHarness()
        for _ in range(6):
            h.hold(False, True, 100)
            h.release()
        self.assertEqual(h.runner.stage, 1)  # wraps after stage 6

    def test_arm_gesture_does_not_change_stage(self):
        h = RunnerHarness()
        h.arm()
        self.assertEqual(h.runner.stage, 1)

    def test_any_button_aborts_a_run_and_blanks(self):
        h = RunnerHarness()
        h.arm()
        h.hold(True, False, 1100)
        presses = []

        def press_later():
            presses.append(1)
            if len(presses) == 5:
                h.i75.buttons[1] = True

        h.on_sleep = press_later
        h.i75.buttons[0] = False
        h.release()  # releasing A triggers the run inside tick()
        self.assertTrue(any("ABORTED" in l for l in h.logs))
        self.assertEqual(h.i75.snapshots[-1].lit(), {})
        assert_always_safe(self, h.i75)

    def test_main_opens_display_once_blanks_and_stops_on_keyboard_interrupt(self):
        fake, instances = fake_board.make_module()
        sys.modules["interstate75"] = fake
        for n in ("hwtest_common", "stage_runner_main"):
            sys.modules.pop(n, None)
        mod = importlib.import_module("stage_runner_main")
        calls = []

        def stop(ms):
            calls.append(ms)
            if len(calls) > 5:
                raise KeyboardInterrupt

        mod._sleep_ms = stop
        _, text = run_quiet(mod.main)
        self.assertEqual(len(instances), 1)
        self.assertIn("stopped from serial", text)
        for s in instances[0].snapshots:
            self.assertEqual(s.lit(), {})
        self.assertEqual(instances[0].snapshots[-1].lit(), {})

    def test_runner_source_has_no_path_to_light_without_a_run(self):
        # Static guard: the only caller of hw.show in the runner is run_stage.
        with open(os.path.join(TOOLS, "stage_runner_main.py")) as f:
            src = f.read()
        self.assertEqual(len(re.findall(r"hw\.show\(", src)), 1)
        body = src.split("    def run_stage(self):")[1].split("\ndef main")[0]
        self.assertIn("hw.show(", body)


class VisibilityStage(unittest.TestCase):
    """Stage 4: the only thing allowed above the normal clamp, separately bounded."""

    def setUp(self):
        load_script("hw10_sparse_pixel")
        self.hw = sys.modules["hwtest_common"]
        self.i75, self.gfx = self.hw.open_display("chained")

    def test_definition_is_a_small_block_inside_its_own_limits(self):
        px, secs = self.hw.stage_pixels(4)
        self.assertEqual(sorted((x, y) for x, y, _ in px), [(31, 15), (31, 16), (32, 15), (32, 16)])
        self.assertLessEqual(len(px), self.hw.DIAG_MAX_PIXELS)
        self.assertLessEqual(max(max(c) for _, _, c in px), self.hw.DIAG_MAX_CHANNEL)
        self.assertLessEqual(sum(sum(c) for _, _, c in px), self.hw.DIAG_MAX_SUM)
        self.assertLessEqual(secs, self.hw.DIAG_MAX_SECONDS)
        self.assertTrue(self.hw.stage_is_diagnostic(4))
        for st in (1, 2, 3):
            self.assertFalse(self.hw.stage_is_diagnostic(st))

    def test_normal_limits_still_reject_stage_four_pixels(self):
        px, secs = self.hw.stage_pixels(4)
        with self.assertRaises(ValueError):
            self.hw.show(self.i75, self.gfx, px, secs, lambda s: None)  # not marked diagnostic
        self.assertEqual(self.i75.snapshots, [])

    def test_diagnostic_bounds_are_enforced_before_anything_lights(self):
        for px in ([(1, 1, (97, 0, 0))], [(x, 1, (1, 1, 1)) for x in range(5)]):  # channel > 96, 5 pixels
            with self.assertRaises(ValueError):
                self.hw.show(self.i75, self.gfx, px, 1, lambda s: None, True)
        # Four pixels at 96 total 1152, under the 1200 cap, so the cap is a second guard.
        # Prove the sum check itself works by tightening the constant for this test.
        block = [(x, 1, (96, 96, 96)) for x in range(4)]
        self.hw.DIAG_MAX_SUM = 1000
        with self.assertRaises(ValueError):
            self.hw.show(self.i75, self.gfx, block, 1, lambda s: None, True)
        self.assertEqual(self.i75.snapshots, [])

    def test_diagnostic_duration_is_bounded(self):
        got = []
        self.hw.show(self.i75, self.gfx, [(5, 5, (96, 96, 96))], 9999, got.append, True)
        self.assertEqual(got, [self.hw.DIAG_MAX_SECONDS])

    def test_runner_stage_four_lights_block_then_black_and_needs_arming(self):
        h = RunnerHarness()
        for _ in range(3):
            h.hold(False, True, 100)
            h.release()
        self.assertEqual(h.runner.stage, 4)
        h.run_a()  # not armed: must refuse and light nothing
        self.assertEqual(h.lit_frames(), [])
        h.arm()
        h.run_a()
        self.assertEqual(h.lit_frames(), [{(31, 15): (96, 96, 96), (32, 15): (96, 96, 96), (31, 16): (96, 96, 96), (32, 16): (96, 96, 96)}])
        for s in h.i75.snapshots:
            self.assertEqual(s.fill, (0, 0, 0))
        self.assertEqual(h.i75.snapshots[-1].lit(), {})

    def test_power_hard_clamp_is_unchanged_by_the_diagnostic(self):
        self.assertEqual(power.HARD_MAX_PERMILLE, 200)  # raised from 100 on 2026-11-26, owner request
        self.assertEqual(power.MAX_CHANNEL, 51)
        self.assertEqual(max(power.scale_rgb((255, 255, 255), 1000)), 51)
        self.assertEqual(self.hw.PROOF_MAX_CHANNEL, 26)  # proof stages keep their own fixed ceiling


class DisplayVariants(unittest.TestCase):
    def setUp(self):
        self.fake, self.instances = fake_board.make_module()
        sys.modules["interstate75"] = self.fake
        sys.modules.pop("hwtest_common", None)
        import hwtest_common  # noqa: F401  (fresh import against the fake firmware)
        self.hw = sys.modules["hwtest_common"]

    def test_each_variant_passes_exactly_its_documented_options(self):
        want = {1: {}, 2: {"panel_type": 1}, 3: {"stb_invert": True}, 4: {"panel_type": 1, "stb_invert": True}}
        for v, kw in want.items():
            self.instances.clear()
            self.hw.open_display("chained", v)
            self.assertEqual(self.instances[0].init_kwargs, kw, v)
            self.assertEqual(len(self.instances), 1)

    def test_default_is_variant_one_with_no_extra_options(self):
        self.hw.open_display("chained")
        self.assertEqual(self.instances[0].init_kwargs, {})

    def test_bad_variant_and_missing_firmware_option_are_rejected(self):
        for bad in (0, 5, "2", None):
            with self.assertRaises(ValueError):
                self.hw.open_display("chained", bad)
        del self.fake.Interstate75.PANEL_FM6126A
        with self.assertRaises(ValueError):
            self.hw.open_display("chained", 2)

    def test_hold_b_three_seconds_asks_for_next_variant_and_wraps(self):
        for start, expect in ((1, 2), (4, 5), (7, 8), (8, 1)):
            h = RunnerHarness()
            asked = []
            h.runner.variant = start
            h.runner.on_variant = asked.append
            h.hold(False, True, 3100)
            h.release()
            self.assertEqual(asked, [expect], start)
            self.assertEqual(h.lit_frames(), [])  # never lights the panel

    def test_other_b_holds_do_not_change_variant(self):
        h = RunnerHarness()
        asked = []
        h.runner.on_variant = asked.append
        h.hold(False, True, 100)       # tap: stage change
        h.release()
        h.hold(False, True, 1800)      # in between: ignored
        h.release()
        h.arm()                         # A+B: arming, not a variant change
        self.assertEqual(asked, [])
        self.assertEqual(h.runner.stage, 2)

    def test_main_falls_back_to_variant_one_if_a_saved_variant_cannot_open(self):
        fake, instances = fake_board.make_module(reject_kwargs=True)
        sys.modules["interstate75"] = fake
        for n in ("hwtest_common", "stage_runner_main"):
            sys.modules.pop(n, None)
        mod = importlib.import_module("stage_runner_main")
        saved, resets = [], []
        mod.read_variant = lambda: 2
        mod.write_variant = saved.append
        mod._sleep_ms = lambda ms: None
        _, text = run_quiet(mod.main, reset=lambda: resets.append(1))
        self.assertIn("falling back to variant 1", text)
        self.assertEqual(saved, [1])
        self.assertEqual(resets, [1])
        self.assertEqual(instances, [])  # nothing was constructed, so nothing could light

    def test_main_runs_chosen_variant_and_persists_changes(self):
        fake, instances = fake_board.make_module()
        sys.modules["interstate75"] = fake
        for n in ("hwtest_common", "stage_runner_main"):
            sys.modules.pop(n, None)
        mod = importlib.import_module("stage_runner_main")
        mod.read_variant = lambda: 3
        _, text = run_quiet(lambda: _run_main_briefly(mod))
        self.assertIn("variant 3", text)
        self.assertEqual(instances[0].init_kwargs, {"stb_invert": True})
        self.assertEqual((instances[0].display.w, instances[0].display.h), (64, 32))  # variants 1-4 are single-panel
        for s in instances[0].snapshots:
            self.assertEqual(s.lit(), {})


def _run_main_briefly(mod):
    calls = []

    def stop(ms):
        calls.append(ms)
        if len(calls) > 40:
            raise KeyboardInterrupt

    mod._sleep_ms = stop
    mod.main()


class SingleVersusChained(unittest.TestCase):
    def test_variant_numbers_map_to_mode_and_setup(self):
        load_script("hw10_sparse_pixel")
        hw = sys.modules["hwtest_common"]
        self.assertEqual(hw.NUM_VARIANTS, 8)
        for v in range(1, 9):
            mode, setup = hw.variant_parts(v)
            self.assertEqual(mode, "single" if v <= 4 else "chained")
            self.assertEqual(setup, (v - 1) % 4 + 1)
            self.assertIn(mode.split()[0], hw.VARIANTS[v])
        for bad in (0, 9, "1", None):
            with self.assertRaises(ValueError):
                hw.variant_parts(bad)

    def test_default_variant_is_single_panel_default_driver(self):
        h = RunnerHarness(variant=1)
        self.assertEqual((h.i75.display.w, h.i75.display.h), (64, 32))
        self.assertEqual(h.i75.init_kwargs, {})

    def test_chained_variants_are_128_wide(self):
        for v in (5, 6, 7, 8):
            h = RunnerHarness(variant=v)
            self.assertEqual((h.i75.display.w, h.i75.display.h), (128, 32), v)

    def test_single_panel_stages_one_two_four_land_inside_the_panel(self):
        for stage in (1, 2, 4):
            h = RunnerHarness(variant=1)
            h.runner.stage = stage
            h.arm()
            h.run_a()
            lit = h.lit_frames()
            self.assertEqual(len(lit), 1, stage)
            for (x, y) in lit[0]:
                self.assertTrue(0 <= x < 64 and 0 <= y < 32, (stage, x, y))
            self.assertEqual(h.i75.snapshots[-1].lit(), {})

    def test_stage_three_is_refused_in_single_mode_and_lights_nothing(self):
        h = RunnerHarness(variant=1)
        h.runner.stage = 3
        h.arm()
        h.run_a()
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("cannot run in variant 1" in l for l in h.logs))
        self.assertEqual(h.i75.led, h.mod.BLUE)


class ClipStages(unittest.TestCase):
    """Stages 5 and 6: real animation frames through firmware/player.py (host-side, fake display)."""

    def harness(self, variant=1, assets=None):
        h = RunnerHarness(variant=variant)
        h.mod.ASSETS_DIR = assets or os.path.join(REPO, "firmware", "assets")
        self.report = os.path.join(tempfile.mkdtemp(), "last_run.txt")
        h.mod.REPORT_FILE = self.report
        return h

    def select(self, h, stage):
        while h.runner.stage != stage:
            h.hold(False, True, 100)
            h.release()

    def run_stage_n(self, h, stage):
        self.select(h, stage)
        h.arm()
        h.run_a()

    def ref_frames(self, rid):
        import test_player as tp
        return [tp.reference_lit(rec, "single", 0, power.RUN_PERMILLE, ("#F0F5F1",) * 3) for rec in tp.records(rid)]

    def test_stage_5_plays_idle_for_30s_then_blanks_and_disarms(self):
        h = self.harness()
        self.run_stage_n(h, 5)
        idle = self.ref_frames("idle")
        shots = [s.lit() for s in h.i75.snapshots]
        self.assertGreaterEqual(len(shots), 195)
        for i, lit in enumerate(shots[:-1]):
            self.assertEqual(lit, idle[i % len(idle)])
        self.assertEqual(shots[-1], {})  # blanked at the end
        import test_player as tp
        tp.assert_snapshots_safe(self, h.i75)
        self.assertEqual(h.i75.led, h.mod.BLUE)
        n = len(shots)
        h.run_a()  # second run needs a fresh arm
        self.assertEqual(len(h.i75.snapshots), n)

    def test_stage_6_plays_sleep_then_morph_then_idle(self):
        h = self.harness()
        self.run_stage_n(h, 6)
        shots = [s.lit() for s in h.i75.snapshots][:-1]
        sleep, morph, idle = self.ref_frames("sleep"), self.ref_frames("morph"), self.ref_frames("idle")
        self.assertEqual(shots[:len(sleep)], sleep)
        # the player returns to idle for one frame before the runner starts the next reaction
        self.assertEqual(shots[len(sleep)], idle[0])
        m0 = len(sleep) + 1
        self.assertEqual(shots[m0:m0 + len(morph)], morph)
        self.assertEqual(shots[m0 + len(morph)], idle[0])
        import test_player as tp
        tp.assert_snapshots_safe(self, h.i75)

    def test_clips_refuse_in_chained_variants_and_light_nothing(self):
        h = self.harness(variant=5)
        self.run_stage_n(h, 5)
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("REFUSED" in l and "single-panel" in l for l in h.logs))

    def test_clip_refused_when_animation_files_are_missing(self):
        h = self.harness(assets="/definitely/not/here")
        self.run_stage_n(h, 5)
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("REFUSED" in l and "not usable" in l for l in h.logs))

    def test_clip_still_needs_arming(self):
        h = self.harness()
        self.select(h, 5)
        h.run_a()
        self.assertEqual(h.lit_frames(), [])
        self.assertTrue(any("not armed" in l for l in h.logs))

    def test_any_button_aborts_a_clip_and_blanks(self):
        h = self.harness()
        self.select(h, 5)
        h.arm()
        h.hold(True, False, 1100)
        presses = []

        def press_later():
            presses.append(1)
            if len(presses) == 200:  # about a second into the clip
                h.i75.buttons[1] = True

        h.on_sleep = press_later
        h.release()
        self.assertTrue(any("ABORTED" in l for l in h.logs))
        self.assertEqual(h.i75.snapshots[-1].lit(), {})
        self.assertLess(len(h.i75.snapshots), 20)

    def test_clip_run_leaves_a_readable_report_and_refusals_do_too(self):
        h = self.harness()
        self.run_stage_n(h, 5)
        text = open(self.report).read()
        self.assertIn("RUN clip stage 5", text)
        self.assertIn("clip done", text)
        self.assertIn("clip frames=", text)
        h2 = self.harness(variant=5)
        self.run_stage_n(h2, 5)
        self.assertIn("REFUSED", open(self.report).read())

    def test_unwritable_report_path_never_breaks_a_run(self):
        h = self.harness()
        h.mod.REPORT_FILE = "/no/such/dir/last_run.txt"
        self.run_stage_n(h, 5)
        self.assertGreater(len(h.i75.snapshots), 100)
