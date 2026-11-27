# firmware/tools/stage_runner_main.py  (installed on the board as /main.py)
#
# STAGE RUNNER for the hardware proof. NOT the animation player and NOT the final autoboot
# program. It exists so a sparse test can run with the board on the wall adapter and the Mac
# unplugged. It never animates, never touches the network and lights at most 4 pixels.
#
# On boot: open the display ONCE (variant 1 = single 64 x 32 by default), keep it black, wait. Nothing is lit
# until you do two deliberate things with the two buttons on the board:
#
#   B (tap)               choose stage 1, 2, 3 or 4; the status LED flashes amber N times
#   A + B held 3 seconds  ARM: status LED goes green; armed for 60 seconds, then disarms
#   B held 3 s, released  next DISPLAY VARIANT (1..4, wraps): saved, then the board reboots
#   A held 1 s, released  RUN the chosen stage (only while armed). Disarms again afterwards.
#   any button, mid-run   ABORT: panel goes black at once
#
#   stage 1: one dim pixel at (32,16)        needs ONE panel on the board
#   stage 2: red, green, blue pixels         needs ONE panel on the board
#   stage 3: four marker pixels              needs BOTH panels chained
#   stage 4: VISIBILITY check, a 2 x 2 block at (31..32, 15..16), brighter than stages 1-3
#            (channel 96 of 255, 4 pixels, 8 s; see DIAG_* in hwtest_common.py)
#   stage 5: ANIMATION CLIP: the real idle animation, 30 s, through firmware/player.py and
#            firmware/renderer.py at power.RUN_PERMILLE (up to 281 lit pixels per frame)
#   stage 6: ANIMATION CLIP: sleep once, then morph once, then idle, about 20 s in total
#            Stages 5 and 6 need ONE panel (variants 1-4), the animation files in /assets,
#            and refuse to run otherwise. Any button aborts and blanks the panel.
#
# Display variants 1-4 = ONE panel (single 64 x 32): generic, FM6126A init, inverted strobe, both.
# Variants 5-8 = the same four setups for TWO chained panels (128 x 32). Default is variant 1.
# After each reboot the LED flashes cyan once per variant number. Kept in /panel_variant.
# A lone panel must use variants 1-4; stage 3 (panel order) only works in variants 5-8.
#
# Status LED (a short red, green, blue, white sweep at boot proves it works):
# blue = disarmed, green = armed, white = running, red = refused/error.
# The status LED is on the board, not on the panels. Ctrl-C from a serial connection stops
# the runner, blanks the panel and returns to the REPL.

import time

import hwtest_common as hw

try:
    import gc
except ImportError:  # pragma: no cover
    gc = None

ARM_HOLD_MS = 3000
ARM_WINDOW_MS = 60000
RUN_HOLD_MS = 1000
POLL_MS = 20
TAP_MAX_MS = 1000
VARIANT_HOLD_MS = 3000
STAGES = 6
ASSETS_DIR = "/assets"
REPORT_FILE = "/last_run.txt"  # last clip run summary, so it can be read later without the Mac attached
CLIP_MS = {5: 30000, 6: 20000}
CLIP_SCRIPT = {5: (), 6: ("sleep", "morph")}
VARIANT_FILE = "/panel_variant"

# Status LED levels (0-255). The first version used 16-24 and the LED was not visible on the
# real board (2026-11-25 dry run), so these are brighter. It is one small LED on the board.
BLUE = (0, 0, 48)
GREEN = (0, 64, 0)
WHITE = (48, 48, 48)
RED = (112, 0, 0)
AMBER = (112, 40, 0)
CYAN = (0, 64, 64)
OFF = (0, 0, 0)


class Abort(Exception):
    pass


def _ms():
    return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)


def _diff(a, b):
    return time.ticks_diff(a, b) if hasattr(time, "ticks_diff") else a - b


def _sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000)


class Runner:
    def __init__(self, i75, gfx, sw_a, sw_b, now=_ms, sleep_ms=_sleep_ms, log=print, variant=1, on_variant=None):
        self.i75, self.gfx = i75, gfx
        self.variant, self.on_variant = variant, on_variant
        self.sw_a, self.sw_b = sw_a, sw_b
        self.now, self.sleep_ms, self.log = now, sleep_ms, log
        self.stage = 1
        self.armed_at = None  # tick when armed; None = disarmed
        self.need_release = False
        self.both_since = None
        self.a_since = None
        self.b_since = None
        self.b_combo = False
        self.led(BLUE)

    def led(self, rgb):
        self.i75.set_led(rgb[0], rgb[1], rgb[2])

    def _pressed(self):
        return self.i75.switch_pressed(self.sw_a), self.i75.switch_pressed(self.sw_b)

    def _disarm(self):
        self.armed_at = None
        self.led(BLUE)

    def _flash(self, colour, n):
        for _ in range(n):
            self.led(colour)
            self.sleep_ms(200)
            self.led(OFF)
            self.sleep_ms(200)
        self.led(GREEN if self.armed_at is not None else BLUE)

    def tick(self):
        t = self.now()
        if self.armed_at is not None and _diff(t, self.armed_at) >= ARM_WINDOW_MS:
            self.log("runner: arm window expired, disarmed")
            self._disarm()
        a, b = self._pressed()

        if self.need_release:
            if not a and not b:
                self.need_release = False
            return

        if a and b:
            self.a_since = self.b_since = None
            self.b_combo = True
            if self.both_since is None:
                self.both_since = t
            elif _diff(t, self.both_since) >= ARM_HOLD_MS:
                self.armed_at = t
                self.led(GREEN)
                self.log("runner: ARMED for %d s, stage %d" % (ARM_WINDOW_MS // 1000, self.stage))
                self.both_since = None
                self.need_release = True
            return
        self.both_since = None

        if b and not a:
            if self.b_since is None:
                self.b_since = t
                self.b_combo = False
            return
        if self.b_since is not None and not b:  # B released
            held = _diff(t, self.b_since)
            self.b_since = None
            if not self.b_combo and not a and held < TAP_MAX_MS:
                self.stage = self.stage % STAGES + 1
                self.log("runner: stage %d" % self.stage)
                self._flash(AMBER, self.stage)
            elif not self.b_combo and not a and held >= VARIANT_HOLD_MS:
                new_variant = self.variant % hw.NUM_VARIANTS + 1
                self.log("runner: display variant %d (%s), saving and rebooting" % (new_variant, hw.VARIANTS[new_variant]))
                self._flash(CYAN, new_variant)
                self._disarm()
                if self.on_variant is not None:
                    self.on_variant(new_variant)
            self.b_combo = False
            return

        if a and not b:
            if self.a_since is None:
                self.a_since = t
            return
        if self.a_since is not None and not a:  # A released
            held = _diff(t, self.a_since)
            self.a_since = None
            if held >= RUN_HOLD_MS:
                if self.armed_at is None:
                    self.log("runner: REFUSED, not armed (hold A+B for 3 s first)")
                    self._flash(RED, 3)
                else:
                    self.run_stage()

    def _save_report(self, lines):
        try:
            with open(REPORT_FILE, "w") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass  # a report is a convenience, never a reason to fail

    def _refuse(self, why):
        self.log("runner: REFUSED, " + why + "; nothing was lit")
        self._save_report(["runner v4 clip stage %d REFUSED: %s" % (self.stage, why)])
        self._flash(RED, 3)
        self._disarm()
        self.need_release = True

    def run_clip(self):
        """Stages 5 and 6: play real animation frames for a bounded time, through the player."""
        self.armed_at = None
        if hw.variant_parts(self.variant)[0] != "single":
            return self._refuse("animation clips run in single-panel variants 1-4 only (habitat origin not chosen yet)")
        try:
            import player
            import power
            import renderer
        except ImportError as e:
            return self._refuse("animation modules missing (%r)" % (e,))
        free0 = gc.mem_free() if gc is not None and hasattr(gc, "mem_free") else None
        try:
            rend = renderer.Renderer(self.i75, self.gfx, "single", 0, power.RUN_PERMILLE)
        except ValueError as e:
            return self._refuse("display does not match single-panel mode (%s)" % (e,))
        clock = player.Clock() if hasattr(time, "ticks_ms") else player.Clock(self.now)
        p = player.Player(rend, ASSETS_DIR, clock=clock, log=self.log)
        if not p.load(verify_crc=True) or p.fault is not None:
            return self._refuse("animation files not usable (%s)" % (p.fault,))
        script = CLIP_SCRIPT[self.stage]
        limit = CLIP_MS[self.stage]
        self.led(WHITE)
        report = []

        def note(msg):
            report.append(msg)
            self.log(msg)

        note("runner: RUN clip stage %d, %d ms max, asset %s, variant %d, scale %d permille (max channel %d)" % (self.stage, limit, p.asset_version, self.variant, rend.permille, power.MAX_CHANNEL))
        start = self.now()
        idx = 0
        frames = 0
        worst = total = 0
        us = getattr(time, "ticks_us", None)
        try:
            if script:
                p.play(script[0])
                idx = 1
            while _diff(self.now(), start) < limit:
                t0 = us() if us else 0
                if p.tick():
                    frames += 1
                    if us:
                        d = time.ticks_diff(us(), t0)
                        total += d
                        if d > worst:
                            worst = d
                if script and idx < len(script) and p.cur == "idle":
                    p.play(script[idx])
                    idx += 1
                self.sleep_ms(5)
                a, b = self._pressed()
                if a or b:
                    raise Abort()
            note("runner: clip done")
        except Abort:
            note("runner: ABORTED by button, panel blanked")
        finally:
            p.close()
            try:
                rend.blank()
            except Exception:
                pass
        if frames:
            note("runner: clip frames=%d, lit(last)=%d, rejected=%d, avg draw=%s us, worst draw=%s us" % (
                frames, rend.last_lit, rend.rejected, (total // frames) if us else "n/a", worst if us else "n/a"))
        if free0 is not None:
            note("runner: free RAM before %d, after %d" % (free0, gc.mem_free()))
        self._save_report(report)
        self._disarm()
        self.need_release = True

    def run_stage(self):
        if self.stage >= 5:
            return self.run_clip()
        pixels, seconds = hw.stage_pixels(self.stage)
        self.armed_at = None  # every run needs a fresh arm
        self.led(WHITE)
        self.log("runner: RUN stage %d, %d pixel(s), %d s" % (self.stage, len(pixels), seconds))

        def sleep(sec):
            for _ in range(int(sec * 1000 // 50)):
                self.sleep_ms(50)
                a, b = self._pressed()
                if a or b:
                    raise Abort()

        # let go of A first so the release itself cannot abort the run
        try:
            hw.show(self.i75, self.gfx, pixels, seconds, sleep, hw.stage_is_diagnostic(self.stage))
            self.log("runner: stage done, panel blanked")
        except Abort:
            self.log("runner: ABORTED by button, panel blanked")
        except ValueError as e:  # checked before anything is lit
            self.log("runner: stage %d cannot run in variant %d (%s); nothing was lit" % (self.stage, self.variant, e))
            self._flash(RED, 3)
        self._disarm()
        self.need_release = True


def led_selftest(i75, sleep_ms=None):
    """Boot sweep so you can see the status LED works: red, green, blue, white, then blue."""
    sleep_ms = sleep_ms or _sleep_ms
    for colour in (RED, GREEN, BLUE, WHITE):
        i75.set_led(colour[0], colour[1], colour[2])
        sleep_ms(500)
    i75.set_led(BLUE[0], BLUE[1], BLUE[2])


def read_variant():
    try:
        with open(VARIANT_FILE) as f:
            v = int(f.read().strip())
        return v if v in hw.VARIANTS else 1
    except Exception:
        return 1


def write_variant(v):
    with open(VARIANT_FILE, "w") as f:
        f.write(str(v))


def _reset():
    import machine
    machine.reset()


def main(reset=None):
    import interstate75

    reset = reset or _reset
    sw_a = getattr(interstate75, "SWITCH_A", 0)
    sw_b = getattr(interstate75, "SWITCH_B", 1)
    log = print
    variant = read_variant()
    mode, setup = hw.variant_parts(variant)
    log("stage runner v4: opening the display once, variant %d (%s), panel stays black" % (variant, hw.VARIANTS[variant]))
    i75 = gfx = None

    def change_variant(v):
        write_variant(v)
        _sleep_ms(300)
        reset()

    try:
        try:
            i75, gfx = hw.open_display(mode, setup)
        except Exception as e:
            if variant != 1:
                log("runner: variant %d failed to open (%r); falling back to variant 1 and rebooting" % (variant, e))
                write_variant(1)
                reset()
                return
            raise
        hw.blank(i75, gfx)
        led_selftest(i75)
        for _ in range(variant):  # cyan flashes = variant number
            i75.set_led(CYAN[0], CYAN[1], CYAN[2])
            _sleep_ms(250)
            i75.set_led(0, 0, 0)
            _sleep_ms(250)
        i75.set_led(BLUE[0], BLUE[1], BLUE[2])
        runner = Runner(i75, gfx, sw_a, sw_b, variant=variant, on_variant=change_variant)
        log("runner: disarmed. Tap B = stage, hold A+B 3 s = arm, hold A 1 s + release = run, hold B 3 s = next display variant. Stages 5-6 = animation clips (single panel).")
        while True:
            runner.tick()
            _sleep_ms(POLL_MS)
    except KeyboardInterrupt:
        log("runner: stopped from serial")
    except Exception as e:
        log("runner: ERROR %r, panel blanked, stopped" % (e,))
        if i75 is not None:
            i75.set_led(RED[0], RED[1], RED[2])
        raise
    finally:
        if i75 is not None:
            try:
                hw.blank(i75, gfx)
            except Exception:
                pass


if __name__ == "__main__":
    main()
