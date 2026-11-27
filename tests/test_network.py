"""Host tests for firmware/isotime.py, config_store.py, network_client.py and app.py.

The HTTP client is exercised against a REAL local HTTP server over real non-blocking sockets;
Wi-Fi and the backend scheduler use fakes. These prove the software logic only: they model no
radio, no lwIP and no flash wear on the board.
"""
import datetime
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _paths  # noqa: F401
import fake_board  # noqa: F401
import reference_renderer as rr
import test_player as tp

FW = os.path.join(_paths.REPO, "firmware")
if FW not in sys.path:
    sys.path.insert(0, FW)

import app as app_mod  # noqa: E402
import config_store as cs  # noqa: E402
import isotime  # noqa: E402
import network_client as nc  # noqa: E402
import player as player_mod  # noqa: E402
import power  # noqa: E402


# ---------------------------------------------------------------- isotime

class IsoTime(unittest.TestCase):
    def test_matches_datetime_across_many_dates(self):
        import random
        rnd = random.Random(7)
        for _ in range(500):
            dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(milliseconds=rnd.randrange(0, 4_000_000_000_000))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
            self.assertEqual(isotime.parse_iso_ms(s), int(dt.timestamp() * 1000) if False else (dt - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)) // datetime.timedelta(milliseconds=1), s)

    def test_leap_days_and_no_fraction(self):
        self.assertEqual(isotime.parse_iso_ms("2028-02-29T00:00:00Z"), 1835395200000)
        self.assertEqual(isotime.parse_iso_ms("1970-01-01T00:00:00.000Z"), 0)

    def test_rejects_junk(self):
        for bad in ("", "2026-11-26", "2026-11-26T20:10:00", "2026-13-26T20:10:00Z", "2026-11-26 20:10:00Z", None, 5, "2026-11-26T20:10:00.xZ", "x" * 40):
            with self.assertRaises(ValueError):
                isotime.parse_iso_ms(bad)


# ---------------------------------------------------------------- config validation and store

def good_config(**over):
    c = json.loads(json.dumps(cs.DEFAULT))
    c.update(revision=3, asset_version="abc", server_time="2026-11-26T20:00:00.000Z")
    c.update(over)
    return c


def good_command(**over):
    c = {"id": "12345678-1234-1234-1234-123456789abc", "type": "play", "reaction": "wave", "speed": 1, "cycles": 1, "hold": False, "expires_at": "2026-11-26T20:00:30.000Z"}
    c.update(over)
    return c


class ConfigValidation(unittest.TestCase):
    def test_accepts_defaults_and_a_full_config_with_a_command(self):
        self.assertIsNone(cs.validate_config(cs.DEFAULT))
        self.assertIsNone(cs.validate_config(good_config(command=good_command())))

    def test_rejects_every_kind_of_bad_input(self):
        bad = [
            None, [], "x", {}, good_config(schema_version=2), good_config(revision=-1), good_config(revision=True), good_config(revision="3"),
            good_config(colors={"sheep_a": "#FFF", "sheep_b": "#F0F5F1", "effects": "#F0F5F1"}),
            good_config(colors={"sheep_a": "#GGGGGG", "sheep_b": "#F0F5F1", "effects": "#F0F5F1"}),
            good_config(colors={"sheep_a": "#F0F5F1", "sheep_b": "#F0F5F1"}),
            good_config(brightness_percent=101), good_config(brightness_percent=-1), good_config(brightness_percent=50.5),
            good_config(ambient={"mode": "party", "rotation": [], "interval_s": 120}),
            good_config(ambient={"mode": "rotation", "rotation": ["nope"], "interval_s": 120}),
            good_config(ambient={"mode": "idle", "rotation": [], "interval_s": 5}),
            good_config(enabled_reactions=["wave"]), good_config(enabled_reactions=["idle", "nope"]),
            good_config(blackout="no"), good_config(poll_interval_s=0), good_config(heartbeat_interval_s=1),
            good_config(server_time="yesterday"), good_config(asset_version="x" * 40),
            good_config(command={"id": "short", "type": "play"}),
            good_config(command=good_command(type="firmware")), good_config(command=good_command(reaction="../../x")),
            good_config(command=good_command(speed=2)), good_config(command=good_command(speed=0.1)),
            good_config(command=good_command(cycles=0)), good_config(command=good_command(cycles=99)),
            good_config(command=good_command(hold="yes")), good_config(command=good_command(expires_at="soon")),
            good_config(command=good_command(type="play", reaction=None)),
        ]
        for c in bad:
            self.assertIsNotNone(cs.validate_config(c), repr(c)[:120])

    def test_idle_command_may_have_no_reaction(self):
        self.assertIsNone(cs.validate_config(good_config(command=good_command(type="idle", reaction=None))))

    def test_reaction_ids_agree_with_shared_limits(self):
        self.assertEqual(list(cs.REACTION_IDS), rr.LIMITS["reaction_ids"])

    def test_validation_never_raises_on_weird_types(self):
        weird = good_config()
        weird["ambient"] = {"mode": "rotation", "rotation": [[], {}], "interval_s": 120}
        self.assertIsNotNone(cs.validate_config(weird))
        weird = good_config(colors={"sheep_a": 5, "sheep_b": None, "effects": []})
        self.assertIsNotNone(cs.validate_config(weird))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.t = [0]
        self.clock = player_mod.Clock(now_fn=lambda: self.t[0])
        self.logs = []
        self.store = cs.ConfigStore(self.clock, self.path, log=self.logs.append)

    def test_missing_file_gives_defaults(self):
        c = self.store.load()
        self.assertEqual(c["revision"], 0)
        self.assertFalse(c["blackout"])

    def test_corrupt_or_invalid_cache_gives_defaults(self):
        for text in ("{ not json", json.dumps({"schema_version": 1}), json.dumps(good_config(brightness_percent=999)), "x" * 9000):
            with open(self.path, "w") as f:
                f.write(text)
            c = cs.ConfigStore(self.clock, self.path, log=self.logs.append).load()
            self.assertEqual(c["revision"], 0, text[:30])

    def test_save_is_atomic_strips_the_command_and_round_trips_blackout(self):
        cfg = good_config(blackout=True, command=good_command())
        self.store.note(cfg)
        self.assertTrue(self.store.flush())
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with open(self.path) as fh:
            self.assertIsNone(json.load(fh)["command"])  # the FILE holds no command: a reboot cannot replay one
        loaded = cs.ConfigStore(self.clock, self.path).load()
        self.assertTrue(loaded["blackout"])
        self.assertIsNone(loaded["command"])
        self.assertEqual(loaded["revision"], 3)

    def test_unchanged_revision_causes_no_write_and_writes_are_rate_limited(self):
        self.store.note(good_config(revision=5))
        self.assertTrue(self.store.flush())
        self.store.note(good_config(revision=5))
        self.assertFalse(self.store.flush())
        self.assertEqual(self.store.writes, 1)
        self.store.note(good_config(revision=6))
        self.t[0] += 1000
        self.assertFalse(self.store.flush())  # too soon: stays pending
        self.t[0] += cs.MIN_SAVE_MS
        self.assertTrue(self.store.flush())
        self.assertEqual(self.store.writes, 2)
        self.assertEqual(cs.ConfigStore(self.clock, self.path).load()["revision"], 6)

    def test_a_failed_write_leaves_the_old_file_intact_and_retries(self):
        self.store.note(good_config(revision=5))
        self.store.flush()
        boom = {"n": 0}

        def bad_rename(a, b):
            boom["n"] += 1
            raise OSError(5, "EIO")

        s2 = cs.ConfigStore(self.clock, self.path, log=self.logs.append, rename=bad_rename)
        s2.note(good_config(revision=7))
        self.t[0] += cs.MIN_SAVE_MS * 2
        self.assertFalse(s2.flush())
        self.assertEqual(cs.ConfigStore(self.clock, self.path).load()["revision"], 5)
        self.assertIsNotNone(s2.dirty)


# ---------------------------------------------------------------- real-socket HTTP client

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _do(self):
        mode = self.server.mode
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.seen.append((self.command, self.path, dict(self.headers), body))
        if mode == "slow":
            time.sleep(1.5)
        if mode == "garbage":
            self.wfile.write(b"this is not http\r\n\r\n")
            return
        if mode == "truncated":
            self.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\n0123456789")
            return
        if mode == "chunked":
            payload = json.dumps({"hello": "chunked"}).encode()
            self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            half = len(payload) // 2
            for part in (payload[:half], payload[half:]):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.write(b"0\r\n\r\n")
            return
        if mode == "big":
            payload = b"x" * 10000
        elif mode == "echo":
            payload = json.dumps({"method": self.command, "path": self.path, "auth": self.headers.get("authorization"), "body": body.decode()}).encode()
        else:
            payload = json.dumps({"ok": True}).encode()
        status = 401 if mode == "401" else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _do


class Server:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.mode = "ok"
        self.httpd.seen = []
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def drive(http, limit_s=5.0):
    """Step the request like the main loop does, recording the longest single step."""
    worst = 0.0
    end = time.monotonic() + limit_s
    while http.busy and time.monotonic() < end:
        t0 = time.perf_counter()
        http.step()
        worst = max(worst, time.perf_counter() - t0)
        time.sleep(0.001)
    return worst


class HttpOnRealSockets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def setUp(self):
        self.srv.httpd.mode = "ok"
        self.srv.httpd.seen.clear()
        self.http = nc.Http("127.0.0.1", self.srv.port, "tok-123", player_mod.Clock(), timeout_ms=700)

    def get(self, mode, path="/api/device/config", method="GET", body=None):
        self.srv.httpd.mode = mode
        self.assertTrue(self.http.start(method, path, body))
        worst = drive(self.http)
        self.assertFalse(self.http.busy)
        return self.http.result, worst

    def test_get_returns_status_and_body_and_sends_the_bearer_token(self):
        (status, body, err), _ = self.get("echo")
        self.assertEqual((status, err), (200, None))
        echoed = json.loads(body)
        self.assertEqual(echoed["auth"], "Bearer tok-123")
        self.assertEqual(echoed["path"], "/api/device/config")
        self.assertEqual(self.srv.httpd.seen[0][2].get("Connection"), "close")

    def test_post_sends_a_json_body_with_content_length(self):
        (status, body, err), _ = self.get("echo", "/api/device/heartbeat", "POST", '{"a":1}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["body"], '{"a":1}')
        self.assertEqual(self.srv.httpd.seen[0][2].get("Content-Type"), "application/json")

    def test_chunked_responses_are_decoded(self):
        (status, body, err), _ = self.get("chunked")
        self.assertEqual((status, json.loads(body)), (200, {"hello": "chunked"}))

    def test_http_errors_are_reported_not_raised(self):
        (status, body, err), _ = self.get("401")
        self.assertEqual((status, err), (401, None))

    def test_a_slow_server_times_out_and_no_step_ever_blocks(self):
        (status, body, err), worst = self.get("slow")
        self.assertEqual((status, body), (None, None))
        self.assertIn("timeout", err)
        self.assertLess(worst, 0.02, "a single step() must stay far below a 150 ms animation frame")

    def test_connection_refused_fails_fast_without_blocking(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        http = nc.Http("127.0.0.1", port, "t", player_mod.Clock(), timeout_ms=700)
        t0 = time.perf_counter()
        http.start("GET", "/x")
        worst = drive(http)
        self.assertIsNone(http.result[0])
        self.assertTrue(http.result[2])
        self.assertLess(worst, 0.02)
        self.assertLess(time.perf_counter() - t0, 1.0)

    def test_garbage_truncated_and_oversized_responses_are_rejected(self):
        for mode in ("garbage", "truncated", "big"):
            (status, body, err), _ = self.get(mode)
            self.assertIsNone(status, mode)
            self.assertTrue(err, mode)

    def test_one_request_at_a_time_and_clean_state_afterwards(self):
        self.srv.httpd.mode = "slow"
        self.assertTrue(self.http.start("GET", "/a"))
        self.assertFalse(self.http.start("GET", "/b"))
        drive(self.http)
        self.srv.httpd.mode = "ok"
        self.assertTrue(self.http.start("GET", "/c"))
        drive(self.http)
        self.assertEqual(self.http.result[0], 200)
        self.assertIsNone(self.http.sock)


# ---------------------------------------------------------------- Wi-Fi and the scheduler (fakes)

class FakeWlan:
    def __init__(self):
        self.up = False
        self.active_called = False
        self.connects = 0
        self.stat = 0

    def active(self, v):
        self.active_called = True

    def isconnected(self):
        return self.up

    def connect(self, ssid, pw):
        self.connects += 1

    def disconnect(self):
        pass

    def status(self, what=None):
        if what == "rssi":
            return -55
        return self.stat


class Clk:
    def __init__(self):
        self.t = 0
        self.clock = player_mod.Clock(now_fn=lambda: self.t)


class WifiTests(unittest.TestCase):
    def setUp(self):
        self.c = Clk()
        self.w = FakeWlan()
        self.wifi = nc.Wifi(self.w, "ssid", "pw", self.c.clock, log=lambda m: None)

    def advance(self, ms, step=500):
        end = self.c.t + ms
        while self.c.t < end:
            self.wifi.step()
            self.c.t += step

    def test_connects_and_reports_rssi(self):
        self.advance(1000)
        self.assertEqual(self.w.connects, 1)
        self.w.up = True
        self.advance(1000)
        self.assertTrue(self.wifi.connected)
        self.assertEqual(self.wifi.rssi(), -55)

    def test_failed_attempts_back_off_and_never_spam(self):
        self.w.stat = -2  # no AP
        self.advance(60000)
        self.assertLessEqual(self.w.connects, 6)
        self.assertGreaterEqual(self.w.connects, 3)

    def test_timeout_triggers_a_retry_and_a_lost_link_reconnects(self):
        self.advance(40000)  # first attempt hangs for 20 s, then a backed-off retry follows
        self.assertGreaterEqual(self.w.connects, 2)
        self.w.up = True
        self.advance(1000)
        self.assertTrue(self.wifi.connected)
        before = self.w.connects
        self.w.up = False
        self.advance(3000)
        self.assertFalse(self.wifi.connected)
        self.advance(10000)
        self.assertGreater(self.w.connects, before)


class FakeHttp:
    """Scripted stand-in for nc.Http so scheduling can be tested with a fake clock."""

    def __init__(self, clk, script):
        self.clk, self.script = clk, list(script)
        self.busy = False
        self.result = None
        self.calls = []
        self.finish_at = None

    def start(self, method, path, body=None):
        self.calls.append((self.clk.t, method, path, body))
        self.result = self.script.pop(0) if self.script else (200, b"{}", None)
        self.busy = True
        self.finish_at = self.clk.t + 20
        return True

    def step(self):
        if self.busy and self.clk.t >= self.finish_at:
            self.busy = False


class NetClientScheduling(unittest.TestCase):
    def setUp(self):
        self.c = Clk()
        self.w = FakeWlan()
        self.w.up = True
        self.wifi = nc.Wifi(self.w, "s", "p", self.c.clock, log=lambda m: None)
        self.got = []
        self.logs = []

    def make(self, script):
        self.http = FakeHttp(self.c, script)
        self.net = nc.NetClient(self.http, self.wifi, self.c.clock, self.got.append, lambda: {"fw_version": "t"}, log=self.logs.append)
        return self.net

    def run_for(self, ms, step=10):
        end = self.c.t + ms
        while self.c.t < end:
            self.net.step()
            self.c.t += step

    def cfg_ok(self):
        return (200, json.dumps({"revision": 1}).encode(), None)

    def test_heartbeat_first_then_polls_every_two_seconds_and_heartbeats_every_fifteen(self):
        net = self.make([(200, b"{}", None)] + [self.cfg_ok()] * 40)
        self.run_for(31000)
        kinds = [(p, m) for _, m, p, _ in self.http.calls]
        self.assertEqual(kinds[0], ("/api/device/heartbeat", "POST"))
        polls = [t for t, m, p, _ in self.http.calls if m == "GET"]
        beats = [t for t, m, p, _ in self.http.calls if m == "POST"]
        self.assertTrue(all(1900 <= b - a <= 2300 for a, b in zip(polls, polls[1:])), polls[:5])
        self.assertTrue(len(beats) in (2, 3), beats)
        self.assertTrue(all(14900 <= b - a <= 15300 for a, b in zip(beats, beats[1:])), beats)
        self.assertEqual(self.got[0], {"revision": 1})

    def test_a_requested_heartbeat_goes_out_promptly(self):
        net = self.make([])
        self.run_for(1000)
        n = sum(1 for c in self.http.calls if c[1] == "POST")
        net.request_heartbeat()
        self.run_for(100)
        self.assertEqual(sum(1 for c in self.http.calls if c[1] == "POST"), n + 1)

    def test_failures_back_off_exponentially_then_recover(self):
        net = self.make([(None, None, "timeout")] * 5 + [self.cfg_ok()] * 10)
        net.hb_dirty = False
        net.next_hb = self.c.t + 2 * 10 ** 8
        self.run_for(70000)
        times = [t for t, m, p, _ in self.http.calls]
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertGreater(gaps[1], gaps[0])  # backoff grows
        self.assertGreater(gaps[2], gaps[1])
        self.assertLessEqual(max(gaps[:4]), 30000 + 600)
        self.assertEqual(net.fails, 0)  # recovered
        self.assertTrue(self.got)

    def test_garbage_json_is_a_failure_and_never_reaches_the_app(self):
        net = self.make([(200, b"{broken", None), self.cfg_ok()])
        net.hb_dirty = False
        net.next_hb = self.c.t + 2 * 10 ** 8
        self.run_for(8000)
        self.assertEqual(self.got[0], {"revision": 1})  # the broken payload never reached the app
        self.assertTrue(all(isinstance(g, dict) for g in self.got))
        self.assertTrue(any("invalid JSON" in l for l in self.logs))

    def test_nothing_is_sent_while_wifi_is_down(self):
        self.w.up = False
        net = self.make([])
        self.run_for(3000)
        self.assertEqual(self.http.calls, [])

    def test_http_401_is_backed_off_not_hammered(self):
        net = self.make([(401, b"{}", None)] * 20)
        self.run_for(20000)
        self.assertLessEqual(len(self.http.calls), 8)

    def test_reachable_reflects_recent_success_only(self):
        net = self.make([self.cfg_ok()] * 5)
        self.run_for(500)
        self.assertTrue(net.reachable())
        self.http.script = [(None, None, "timeout")] * 99
        self.run_for(60000)
        self.assertFalse(net.reachable())


# ---------------------------------------------------------------- the app

class FakeNet:
    def __init__(self):
        self.hb = 0
        self.intervals = None
        self.wifi = type("W", (), {"connected": False, "rssi": lambda s: None})()
        self.http = type("H", (), {"busy": False})()
        self.requests = 0

    def request_heartbeat(self):
        self.hb += 1

    def set_intervals(self, a, b):
        self.intervals = (a, b)

    def step(self):
        pass


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = tp.FakeTime()
        self.logs = []
        self.players = []
        self.mk()

    def tearDown(self):
        for p in self.players:
            p.close()

    def mk(self, cache=None):
        if cache is not None:
            with open(os.path.join(self.tmp, "config.json"), "w") as f:
                f.write(json.dumps(cache))
        self.rend, self.i75 = tp.make_renderer("single", 0, colours=("#F0F5F1",) * 3)
        self.pl = player_mod.Player(self.rend, tp.ASSETS, clock=self.t.clock, log=self.logs.append)
        self.pl.load()
        self.players.append(self.pl)
        self.store = cs.ConfigStore(self.t.clock, os.path.join(self.tmp, "config.json"), log=self.logs.append)
        self.app = app_mod.App(self.pl, self.rend, self.store, self.t.clock, log=self.logs.append)
        self.net = FakeNet()
        self.app.net = self.net
        self.app.boot()

    def run_ms(self, ms, step=10):
        end = self.t.t + ms
        while self.t.t < end:
            self.app.tick()
            self.t.t += step

    def cfg(self, **over):
        return good_config(**over)

    def test_boot_with_no_cache_uses_defaults_and_starts_idle_before_any_network(self):
        self.run_ms(600)
        self.assertEqual(self.pl.cur, "idle")
        self.assertTrue(self.i75.snapshots[-1].lit())
        self.assertEqual(self.app.revision, 0)

    def test_applies_colours_and_brightness_as_a_percentage_of_the_firmware_cap(self):
        self.app.on_config(self.cfg(colors={"sheep_a": "#FFB34F", "sheep_b": "#75CAFF", "effects": "#F0F5F1"}, brightness_percent=50))
        self.assertEqual(self.rend.permille, power.HARD_MAX_PERMILLE * 50 // 100)
        self.run_ms(300)
        lit = self.i75.snapshots[-1].lit()
        self.assertLessEqual(max(max(v) for v in lit.values()), power.MAX_CHANNEL)
        self.assertEqual(self.net.hb, 1)  # a new revision is reported promptly
        self.assertEqual(self.net.intervals, (2, 15))

    def test_brightness_100_percent_is_the_firmware_cap_and_no_more(self):
        self.app.on_config(self.cfg(brightness_percent=100))
        self.assertEqual(self.rend.permille, power.HARD_MAX_PERMILLE)
        self.run_ms(300)
        for s in self.i75.snapshots:
            for rgb in s.lit().values():
                self.assertLessEqual(max(rgb), power.MAX_CHANNEL)

    def test_a_play_command_plays_once_then_returns_to_idle_and_is_never_replayed(self):
        cmd = good_command(reaction="wave")
        self.app.on_config(self.cfg(command=cmd))
        self.assertEqual(self.pl.cur, "wave")
        self.assertEqual(self.app.last_command, cmd["id"])
        n = self.pl.frames["wave"]
        self.run_ms(n * 150 + 400)
        self.assertEqual(self.pl.cur, "idle")
        self.app.on_config(self.cfg(command=cmd))  # server shows the same command again
        self.assertEqual(self.pl.cur, "idle")  # duplicate id: not replayed
        cmd2 = good_command(id="22345678-1234-1234-1234-123456789abc", reaction="wave")
        self.app.on_config(self.cfg(command=cmd2))
        self.assertEqual(self.pl.cur, "wave")  # same reaction, NEW id: plays again

    def test_speed_cycles_and_hold_are_passed_through_and_clamped_by_the_player(self):
        self.app.on_config(self.cfg(command=good_command(reaction="dance", speed=0.5, cycles=3)))
        self.assertEqual((self.pl.speed, self.pl.cycles, self.pl.hold), (500, 3, False))
        self.app.on_config(self.cfg(command=good_command(id="32345678-1234-1234-1234-123456789abc", reaction="dance", hold=True)))
        self.assertTrue(self.pl.hold)

    def test_an_expired_command_is_ignored_using_the_servers_clock_not_the_devices(self):
        late = good_command(expires_at="2026-11-26T19:59:59.000Z")  # before server_time 20:00:00
        self.app.on_config(self.cfg(command=late))
        self.assertEqual(self.pl.cur, "idle")
        self.assertIsNone(self.app.last_command)
        self.assertTrue(any("expired" in l for l in self.logs))

    def test_idle_command_stops_a_held_reaction(self):
        self.app.on_config(self.cfg(command=good_command(reaction="dance", hold=True)))
        self.run_ms(2000)
        self.app.on_config(self.cfg(command=good_command(id="42345678-1234-1234-1234-123456789abc", type="idle", reaction=None)))
        self.assertEqual(self.pl.cur, "idle")

    def test_disabled_reactions_are_refused(self):
        en = [r for r in cs.REACTION_IDS if r != "wave"]
        self.app.on_config(self.cfg(enabled_reactions=en, command=good_command(reaction="wave")))
        self.assertEqual(self.pl.cur, "idle")
        self.assertIsNone(self.app.last_command)

    def test_blackout_is_black_survives_reboot_and_ignores_commands(self):
        self.app.on_config(self.cfg(blackout=True, command=good_command()))
        self.run_ms(1000)
        self.assertTrue(all(s.lit() == {} for s in self.i75.snapshots[-5:]))
        self.assertEqual(self.pl.cur, "idle")  # command ignored during blackout
        self.t.t += cs.MIN_SAVE_MS + 1
        self.app.tick()
        # reboot: a new App built from the cached file is black from its very first frame
        self.mk()
        self.run_ms(400)
        self.assertTrue(self.app.cfg["blackout"])
        self.assertTrue(all(s.lit() == {} for s in self.i75.snapshots))
        # explicit resume
        self.app.on_config(self.cfg(revision=9, blackout=False))
        self.run_ms(400)
        self.assertTrue(self.i75.snapshots[-1].lit())

    def test_invalid_config_is_dropped_and_the_last_good_one_stays(self):
        self.app.on_config(self.cfg(revision=4, brightness_percent=40))
        before = self.rend.permille
        for bad in (self.cfg(revision=5, brightness_percent=5000), {"junk": 1}, None, self.cfg(revision=6, colors={"sheep_a": "red", "sheep_b": "#000000", "effects": "#000000"})):
            self.assertFalse(self.app.on_config(bad))
        self.assertEqual(self.app.revision, 4)
        self.assertEqual(self.rend.permille, before)
        self.assertEqual(self.app.rejected, 4)

    def test_it_keeps_animating_when_the_network_never_answers(self):
        self.net.step = lambda: None  # nothing ever arrives
        self.run_ms(3000)
        times = [i for i, s in enumerate(self.i75.snapshots)]
        self.assertGreaterEqual(len(times), 19)  # 150 ms frames for 3 s
        assert_safe = tp.assert_snapshots_safe
        assert_safe(self, self.i75)

    def test_ambient_rotation_plays_listed_reactions_only_while_idle(self):
        amb = {"mode": "rotation", "rotation": ["wave", "clap"], "interval_s": 30}
        self.app.on_config(self.cfg(ambient=amb))
        self.run_ms(31000)
        self.assertTrue(any("ambient wave" in l for l in self.logs))
        self.run_ms(50000)  # the interval counts idle time, so the next one follows the first reaction's end
        self.assertTrue(any("ambient clap" in l for l in self.logs))
        self.assertEqual(self.net.hb, 1)

    def test_rotation_is_skipped_during_blackout(self):
        amb = {"mode": "rotation", "rotation": ["wave"], "interval_s": 30}
        self.app.on_config(self.cfg(ambient=amb, blackout=True))
        self.run_ms(70000)
        self.assertFalse(any("ambient" in l for l in self.logs))

    def test_heartbeat_payload_has_the_fields_the_server_requires(self):
        hb = self.app.heartbeat()
        for k in ("fw_version", "asset_version", "config_revision", "last_command_id", "reaction", "state", "blackout", "brightness_permille", "effective_cap_permille", "uptime_s"):
            self.assertIn(k, hb)
        self.assertEqual(hb["effective_cap_permille"], power.HARD_MAX_PERMILLE)
        self.assertEqual(hb["state"], "idle")
        self.app.on_config(self.cfg(command=good_command(reaction="wave")))
        hb = self.app.heartbeat()
        self.assertEqual((hb["state"], hb["reaction"], hb["last_command_id"]), ("playing", "wave", good_command()["id"]))
        json.dumps(hb)  # serialisable

    def test_reserved_half_stays_black_in_chained_mode_through_a_full_session(self):
        i75 = tp.make_i75("chained")
        rend = player_mod.renderer_mod.Renderer(i75, i75.display, "chained", 64, 200, ("#F0F5F1",) * 3) if hasattr(player_mod, "renderer_mod") else tp.renderer_mod.Renderer(i75, i75.display, "chained", 64, 200, ("#F0F5F1",) * 3)
        pl = player_mod.Player(rend, tp.ASSETS, clock=self.t.clock, log=lambda m: None)
        pl.load()
        self.players.append(pl)
        a = app_mod.App(pl, rend, cs.ConfigStore(self.t.clock, os.path.join(self.tmp, "c2.json"), log=lambda m: None), self.t.clock, log=lambda m: None)
        a.boot()
        a.on_config(self.cfg(command=good_command(reaction="birthday")))
        for _ in range(400):
            a.tick()
            self.t.t += 10
        for s in i75.snapshots:
            self.assertFalse({x for x, _ in s.lit()} & set(range(0, 64)))


if __name__ == "__main__":
    unittest.main()
