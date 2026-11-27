# firmware/app.py
# The networked player: ties the renderer/player to the backend. MicroPython and CPython compatible.
#
# Principles (CLAUDE.md milestone 4):
#   - Animation never waits for the network: player.tick() and net.step() are both non-blocking.
#   - Everything from the server is validated (config_store) before use; a bad payload is dropped
#     and the last-known-good config stays in force.
#   - Brightness arrives as a percentage of the FIRMWARE cap (power.HARD_MAX_PERMILLE) and is
#     clamped again by power.py/renderer.py. The server can never raise the cap.
#   - Commands are never cached or replayed. A command is played once per id, only if it has not
#     expired. Expiry is judged against the server_time in the SAME response (no RTC, no NTP):
#     remaining = expires_at - server_time. Nothing about wall-clock time is trusted offline.
#   - Blackout is part of the cached config, so it survives a reboot until the server says resume.
#   - Offline (or on a corrupt/unreachable backend) the device keeps playing idle and ambient from
#     the last-known-good config.
import json

import config_store
import isotime
import power

FW_VERSION = "i75w-0.4"
STATUS_FILE = "/net_status.txt"  # last log lines + link state, so a run can be inspected afterwards
STATUS_EVERY_MS = 30000
RECENT_MAX = 14
# status LED while supervised (stage 7): blue = no Wi-Fi, amber = Wi-Fi up but the control room is unreachable, green = talking to it
LED_COLOURS = ((0, 0, 48), (112, 40, 0), (0, 64, 0))

try:
    import gc
except ImportError:  # pragma: no cover
    gc = None


class App:
    def __init__(self, player, rend, store, clock, log=print):
        self.player, self.rend, self.store, self.clock = player, rend, store, clock
        self._out = log
        self.net = None
        self.cfg = None
        self.revision = None
        self.last_command = None
        self.enabled = set(config_store.REACTION_IDS)
        self.ambient = {"mode": "idle", "rotation": [], "interval_s": 120}
        self.next_rotate = None
        self.rot_idx = 0
        self.rejected = 0
        self.applied = 0
        self.booted_at = clock.ms()
        self.max_tick_us = 0
        self.wifi_rssi = None
        self.rssi_at = None
        self.led = None  # optional callable(rgb); set by the supervised runner stage only
        self.led_state = None
        self.led_at = None
        self.status_path = None  # set on the board; None (no file) in tests unless asked
        self.recent = []
        self.status_at = None
        self.status_seen = 0

    def log(self, msg):
        self.recent.append(msg)
        if len(self.recent) > RECENT_MAX:
            del self.recent[0]
        self._out(msg)

    def _housekeeping(self, now):
        net = self.net
        if net is not None and self.led is not None and (self.led_at is None or self.clock.diff(now, self.led_at) >= 500):
            self.led_at = now
            st = 2 if net.reachable() else (1 if net.wifi.connected else 0)
            if st != self.led_state:
                self.led_state = st
                self.led(LED_COLOURS[st])
        if self.status_path and (self.status_at is None or self.clock.diff(now, self.status_at) >= STATUS_EVERY_MS):
            self.status_at = now
            if len(self.recent) != self.status_seen or self.status_seen == 0:
                self.status_seen = len(self.recent)
                try:
                    lines = list(self.recent)
                    if net is not None:
                        lines.append("link: wifi=%s reachable=%s fails=%s requests=%s revision=%s" % (net.wifi.connected, net.reachable(), net.fails, net.requests, self.revision))
                    with open(self.status_path, "w") as f:
                        f.write("\n".join(lines) + "\n")
                except Exception:
                    pass

    # ---- boot ----
    def boot(self):
        """Load the cached config (or defaults) and start from it, before any network."""
        cfg = self.store.load()
        self._apply(cfg)
        self.player.stop()  # start in idle immediately; a blackout in the cache is already applied above
        self.log("app: started from %s config, revision %s, blackout %s" % ("cached" if self.store.saved_revision is not None else "default", cfg["revision"], cfg["blackout"]))

    # ---- applying server data ----
    def _apply(self, cfg):
        c = cfg["colors"]
        permille = power.clamp_permille(power.HARD_MAX_PERMILLE * cfg["brightness_percent"] // 100)
        self.rend.set_colours((c["sheep_a"], c["sheep_b"], c["effects"]), permille)
        self.player.set_blackout(cfg["blackout"])
        self.enabled = set(cfg["enabled_reactions"])
        self.ambient = cfg["ambient"]
        self.next_rotate = None
        self.revision = cfg["revision"]
        self.cfg = cfg
        self.applied += 1

    def on_config(self, cfg):
        """Called with the parsed JSON of every successful config poll."""
        why = config_store.validate_config(cfg)
        if why:
            self.rejected += 1
            self.log("app: rejected config (%s), keeping revision %s" % (why, self.revision))
            return False
        if self.net is not None:
            self.net.set_intervals(cfg["poll_interval_s"], cfg["heartbeat_interval_s"])
        if cfg["revision"] != self.revision:
            self._apply(cfg)
            self.store.note(cfg)
            if self.net is not None:
                self.net.request_heartbeat()
            self.log("app: applied config revision %d" % cfg["revision"])
        cmd = cfg["command"]
        if cmd is not None:
            self._command(cmd, cfg["server_time"])
        return True

    def _command(self, cmd, server_time):
        if cmd["id"] == self.last_command:
            return  # duplicate: already played, never replay
        try:
            remaining = isotime.parse_iso_ms(cmd["expires_at"]) - isotime.parse_iso_ms(server_time)
        except Exception:
            return
        if remaining <= 0:
            self.log("app: ignoring expired command %s" % cmd["id"][:8])
            return
        if self.rend.blackout:
            self.log("app: ignoring command during blackout")
            return
        if cmd["type"] == "idle":
            self.player.stop()
        else:
            r = cmd["reaction"]
            if r not in self.enabled:
                self.log("app: ignoring disabled reaction %s" % r)
                return
            if not self.player.play(r, int(cmd["speed"] * 1000 + 0.5), cmd["cycles"], cmd["hold"]):
                self.log("app: cannot play %s" % r)
                return
        self.last_command = cmd["id"]
        self.next_rotate = None
        if self.net is not None:
            self.net.request_heartbeat()
        self.log("app: %s %s [%s]" % (cmd["type"], cmd["reaction"], cmd["id"][:8]))

    # ---- ambient rotation ----
    def _rotate(self):
        amb = self.ambient
        p = self.player
        if amb.get("mode") != "rotation" or not amb["rotation"] or self.rend.blackout or p.fault is not None or p.cur != "idle":
            self.next_rotate = None
            return
        now = self.clock.ms()
        if self.next_rotate is None:
            self.next_rotate = self.clock.add(now, amb["interval_s"] * 1000)
            return
        if self.clock.diff(now, self.next_rotate) < 0:
            return
        self.next_rotate = self.clock.add(now, amb["interval_s"] * 1000)
        rot = amb["rotation"]
        for _ in range(len(rot)):
            r = rot[self.rot_idx % len(rot)]
            self.rot_idx += 1
            if r in self.enabled and r != "idle" and p.play(r, 1000, 1, False):
                self.log("app: ambient %s" % r)
                return

    # ---- heartbeat ----
    def state(self):
        if self.player.fault is not None:
            return "fallback"
        if self.rend.blackout:
            return "blackout"
        return "idle" if self.player.cur in (None, "idle") else "playing"

    def heartbeat(self):
        hb = {
            "fw_version": FW_VERSION,
            "asset_version": (self.player.asset_version or "unknown")[:32],
            "config_revision": self.revision or 0,
            "last_command_id": self.last_command,
            "reaction": self.player.cur if self.player.fault is None else None,
            "state": self.state(),
            "blackout": bool(self.rend.blackout),
            "brightness_permille": self.rend.permille,
            "effective_cap_permille": power.HARD_MAX_PERMILLE,
            "uptime_s": self.clock.diff(self.clock.ms(), self.booted_at) // 1000,
        }
        if gc is not None and hasattr(gc, "mem_free"):
            hb["free_ram"] = gc.mem_free()
        if self.wifi_rssi is not None:
            hb["rssi"] = self.wifi_rssi
        return hb

    # ---- main loop step ----
    def tick(self):
        self.player.tick()
        if self.net is not None:
            self.net.step()
            now = self.clock.ms()
            if self.rssi_at is None or self.clock.diff(now, self.rssi_at) >= 10000:
                self.rssi_at = now
                self.wifi_rssi = self.net.wifi.rssi() if self.net.wifi.connected else None
        self.store.flush()
        self._rotate()
        self._housekeeping(self.clock.ms())


def build(i75, gfx, secrets, mode="single", origin=0, assets_dir="/assets", log=print):
    """Create the real objects for the board. The display must already be open (once per boot)."""
    import network
    import urandom

    import network_client as nc
    import player as player_mod
    import renderer as renderer_mod

    clock = player_mod.Clock()
    rend = renderer_mod.Renderer(i75, gfx, mode, origin, power.DEFAULT_PERMILLE)
    pl = player_mod.Player(rend, assets_dir, clock=clock, log=log)
    pl.load(verify_crc=True)
    store = config_store.ConfigStore(clock, log=log)
    app = App(pl, rend, store, clock, log)
    app.status_path = STATUS_FILE
    rand = lambda n: urandom.getrandbits(16) % n  # noqa: E731
    wlan = network.WLAN(network.STA_IF)
    wifi = nc.Wifi(wlan, secrets.WIFI_SSID, secrets.WIFI_PASSWORD, clock, log, rand)
    http = nc.Http(secrets.SERVER_HOST, getattr(secrets, "SERVER_PORT", 3000), secrets.DEVICE_TOKEN, clock)
    app.net = nc.NetClient(http, wifi, clock, app.on_config, app.heartbeat, log, rand)
    return app


def run(app, abort, sleep_ms, log=print):
    """Run until abort() is true. Blank the panel on the way out."""
    app.boot()
    try:
        while not abort():
            app.tick()
            sleep_ms(2)
    finally:
        app.player.close()
        try:
            app.rend.blank()
        except Exception:
            pass
