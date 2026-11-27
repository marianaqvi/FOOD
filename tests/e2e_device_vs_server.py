#!/usr/bin/env python3
"""End-to-end check: the REAL firmware modules (app, network_client, player, renderer, config_store)
talking over real sockets to the REAL control room server, with a fake display and a fake Wi-Fi.

Not part of `unittest discover` (needs the server). Run with the server up in mock mode:

    cd web && MOCK_MODE=1 npm run dev          # terminal 1
    python3 tests/e2e_device_vs_server.py      # terminal 2   (optional: --url http://127.0.0.1:3000)

It proves the firmware's JSON matches the server's validators and that commands, acknowledgements,
settings, brightness, blackout and offline behaviour work across the wire. It does NOT prove anything
about the board's radio, lwIP, memory or timing.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for sub in ("tests", "firmware"):
    sys.path.insert(0, os.path.join(REPO, sub))

import app as app_mod  # noqa: E402
import config_store  # noqa: E402
import fake_board  # noqa: E402
import network_client as nc  # noqa: E402
import player as player_mod  # noqa: E402
import power  # noqa: E402
import renderer as renderer_mod  # noqa: E402
import test_network as tn  # noqa: E402

URL = "http://127.0.0.1:3000"
if "--url" in sys.argv:
    URL = sys.argv[sys.argv.index("--url") + 1].rstrip("/")
with open(os.path.join(REPO, "web", ".data", "dev-device-token")) as _fh:
    TOKEN = _fh.read().strip()


def staff(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers={"x-requested-with": "control-room", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, **json.loads(e.read() or b"{}")}


def wait(cond, secs, what):
    end = time.time() + secs
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.2)
    raise SystemExit("FAILED waiting for: " + what)


def main():
    tmp = tempfile.mkdtemp()
    fake, _ = fake_board.make_module()
    i75 = fake.Interstate75(display="DISPLAY_INTERSTATE75_64X32")
    clock = player_mod.Clock()
    rend = renderer_mod.Renderer(i75, i75.display, "single", 0, power.DEFAULT_PERMILLE)
    logs = []
    pl = player_mod.Player(rend, os.path.join(REPO, "firmware", "assets"), clock=clock, log=logs.append)
    pl.load(verify_crc=True)
    store = config_store.ConfigStore(clock, os.path.join(tmp, "config.json"), log=logs.append)
    application = app_mod.App(pl, rend, store, clock, log=logs.append)
    wlan = tn.FakeWlan()
    wlan.up = True
    wifi = nc.Wifi(wlan, "ssid", "pw", clock, log=logs.append)
    host, port = URL.split("//")[1].split(":")
    http = nc.Http(host, int(port), TOKEN, clock)
    application.net = nc.NetClient(http, wifi, clock, application.on_config, application.heartbeat, logs.append)
    application.boot()

    stop = threading.Event()
    worst = [0.0]

    def loop():
        while not stop.is_set():
            t0 = time.perf_counter()
            application.tick()
            worst[0] = max(worst[0], time.perf_counter() - t0)
            time.sleep(0.002)

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    try:
        # 1. the real heartbeat passes the real validator, and the server reports a real (non-simulated) device
        st = wait(lambda: (lambda s: s if s.get("device", {}).get("online") else None)(staff("GET", "/api/status")), 12, "device to appear online")
        assert st["device"]["simulated"] is False, st
        assert st["device"]["effective_cap_permille"] == power.HARD_MAX_PERMILLE, st["device"]
        print("ok  device online, real (not simulated), cap", st["device"]["effective_cap_permille"], "fw", st["device"]["fw_version"])

        # 2. settings change reaches the device and is acknowledged by revision
        cur = staff("GET", "/api/settings")["settings"]
        r = staff("PATCH", "/api/settings", {"expected_revision": cur["revision"], "patch": {"colors": {"sheep_a": "#FFB34F"}, "effects_linked": True, "brightness_percent": 50}})
        assert "settings" in r, r
        rev = r["settings"]["revision"]
        wait(lambda: application.revision == rev, 8, "device to apply the new revision")
        wait(lambda: staff("GET", "/api/status")["device"]["config_in_sync"], 8, "server to see the device in sync")
        assert rend.permille == power.HARD_MAX_PERMILLE * 50 // 100
        time.sleep(0.5)
        colours = {v for v in i75.snapshots[-1].lit().values()}
        assert all(max(c) <= power.MAX_CHANNEL for c in colours), colours
        print("ok  settings revision", rev, "applied; brightness permille", rend.permille, "colours on panel", sorted(colours)[:2])

        # 3. command -> played -> acknowledged by command id
        c = staff("POST", "/api/commands", {"type": "play", "reaction": "wave", "request_id": "e2e-wave-0001"})
        cid = c["command"]["id"]
        wait(lambda: pl.cur == "wave", 6, "device to start wave")
        wait(lambda: staff("GET", "/api/status")["last_command"]["display_state"] == "applied", 8, "server to show the command applied")
        wait(lambda: pl.cur == "idle", 10, "wave to finish and return to idle")
        # same request id: no second command; new request id: a new one that plays again
        again = staff("POST", "/api/commands", {"type": "play", "reaction": "wave", "request_id": "e2e-wave-0001"})
        assert again["replayed"] is True and again["command"]["id"] == cid
        replay = staff("POST", "/api/commands", {"type": "play", "reaction": "wave", "request_id": "e2e-wave-0002"})
        assert replay["command"]["id"] != cid
        wait(lambda: pl.cur == "wave", 6, "replay with a new id to play again")
        print("ok  command", cid[:8], "played and acknowledged; duplicate id not replayed; new id replays")

        # 4. blackout is black on the panel and resumes explicitly
        staff("POST", "/api/commands", {"type": "blackout", "request_id": "e2e-blackout-1"})
        wait(lambda: rend.blackout, 6, "device to black out")
        wait(lambda: staff("GET", "/api/status")["last_command"]["display_state"] == "applied", 8, "blackout acknowledged")
        time.sleep(0.6)
        assert i75.snapshots[-1].lit() == {}, "panel must be black during blackout"
        staff("POST", "/api/commands", {"type": "resume", "request_id": "e2e-resume-01"})
        wait(lambda: not rend.blackout, 6, "device to resume")
        print("ok  blackout black on the panel, acknowledged; resume restores")

        # 5. the server going away must not stop the animation
        n0 = len(i75.snapshots)
        http.host, http.port, http.addr = "127.0.0.1", 9, None  # nothing listens on port 9
        time.sleep(3.2)
        n1 = len(i75.snapshots)
        assert n1 - n0 >= 18, ("animation stalled while the backend was unreachable", n1 - n0)
        print("ok  backend unreachable for 3 s: %d frames still drawn (expect about 21)" % (n1 - n0))
        print("longest single tick() %.1f ms (frame period 150 ms)" % (worst[0] * 1000))
        assert worst[0] < 0.05, "a tick blocked for too long"
        for s in i75.snapshots:
            assert s.fill == (0, 0, 0)
            assert len(s.lit()) <= power.MAX_LIT_PIXELS
    finally:
        stop.set()
        th.join(2)
        pl.close()
    print("E2E PASSED")


if __name__ == "__main__":
    main()
