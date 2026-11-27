# firmware/config_store.py
# Strict validation of what the server sends, and the durable last-known-good config.
#   - validate_config / validate_command never raise on bad input: they return a reason string.
#   - ConfigStore.save writes /config.json atomically (temp file + rename) and only when the
#     revision actually changed, at most once per MIN_SAVE_MS, to limit flash wear.
#   - A damaged or invalid cache is ignored: the device starts from DEFAULT (idle, not blacked out),
#     or from the cache if it validates, so a persisted blackout survives a reboot.
# Commands are NEVER cached: a reboot must not replay anything.
import json

import isotime

REACTION_IDS = (
    "idle", "wake", "arrive", "weather_rain", "weather_sun", "weather_cloud", "celebrate", "birthday",
    "sleep", "wave", "dance", "bored", "clap", "launch", "sunset", "christmas", "thought", "morph",
)
SCHEMA_VERSION = 1
MIN_SAVE_MS = 30000
MAX_BODY = 4096

DEFAULT = {
    "schema_version": 1,
    "revision": 0,
    "asset_version": "",
    "colors": {"sheep_a": "#F0F5F1", "sheep_b": "#F0F5F1", "effects": "#F0F5F1"},
    "brightness_percent": 100,
    "ambient": {"mode": "idle", "rotation": [], "interval_s": 120},
    "enabled_reactions": list(REACTION_IDS),
    "command": None,
    "blackout": False,
    "poll_interval_s": 2,
    "heartbeat_interval_s": 15,
    "server_time": "1970-01-01T00:00:00.000Z",
}


def _is_hex(s):
    if not isinstance(s, str) or len(s) != 7 or s[0] != "#":
        return False
    for c in s[1:]:
        if c not in "0123456789abcdefABCDEF":
            return False
    return True


def _is_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _is_num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def validate_command(c):
    """None if valid, else a short reason."""
    if not isinstance(c, dict):
        return "command not an object"
    cid = c.get("id")
    if not isinstance(cid, str) or len(cid) != 36:
        return "command id"
    t = c.get("type")
    if t not in ("play", "idle"):
        return "command type"
    r = c.get("reaction")
    if t == "play" and r not in REACTION_IDS:
        return "command reaction"
    if r is not None and r not in REACTION_IDS:
        return "command reaction"
    if not _is_num(c.get("speed"), 0.5, 1.0):
        return "command speed"
    if not _is_int(c.get("cycles"), 1, 20):
        return "command cycles"
    if not isinstance(c.get("hold"), bool):
        return "command hold"
    try:
        isotime.parse_iso_ms(c.get("expires_at"))
    except Exception:
        return "command expires_at"
    return None


def validate_config(cfg):
    """None if valid, else a short reason. Never raises."""
    try:
        if not isinstance(cfg, dict):
            return "config not an object"
        if cfg.get("schema_version") != SCHEMA_VERSION:
            return "schema_version"
        if not _is_int(cfg.get("revision"), 0, 1000000000):
            return "revision"
        av = cfg.get("asset_version")
        if not isinstance(av, str) or len(av) > 32:
            return "asset_version"
        col = cfg.get("colors")
        if not isinstance(col, dict):
            return "colors"
        for k in ("sheep_a", "sheep_b", "effects"):
            if not _is_hex(col.get(k)):
                return "colors." + k
        if not _is_int(cfg.get("brightness_percent"), 0, 100):
            return "brightness_percent"
        amb = cfg.get("ambient")
        if not isinstance(amb, dict) or amb.get("mode") not in ("idle", "rotation"):
            return "ambient.mode"
        rot = amb.get("rotation")
        if not isinstance(rot, list) or len(rot) > len(REACTION_IDS):
            return "ambient.rotation"
        for r in rot:
            if r not in REACTION_IDS:
                return "ambient.rotation id"
        if not _is_int(amb.get("interval_s"), 30, 3600):
            return "ambient.interval_s"
        en = cfg.get("enabled_reactions")
        if not isinstance(en, list) or "idle" not in en:
            return "enabled_reactions"
        for r in en:
            if r not in REACTION_IDS:
                return "enabled_reactions id"
        if not isinstance(cfg.get("blackout"), bool):
            return "blackout"
        if not _is_int(cfg.get("poll_interval_s"), 1, 60):
            return "poll_interval_s"
        if not _is_int(cfg.get("heartbeat_interval_s"), 5, 300):
            return "heartbeat_interval_s"
        try:
            isotime.parse_iso_ms(cfg.get("server_time"))
        except Exception:
            return "server_time"
        cmd = cfg.get("command")
        if cmd is not None:
            why = validate_command(cmd)
            if why:
                return why
        return None
    except Exception:
        return "unexpected shape"


def _copy(cfg):
    return json.loads(json.dumps(cfg))


class ConfigStore:
    def __init__(self, clock, path="/config.json", log=print, opener=open, rename=None, remove=None):
        self.clock = clock
        self.path = path
        self.tmp = path + ".tmp"
        self.log = log
        self.opener = opener
        if rename is None or remove is None:
            import os
            rename = rename or os.rename
            remove = remove or os.remove
        self.rename, self.remove = rename, remove
        self.dirty = None  # validated config waiting to be written
        self.saved_revision = None
        self.last_save = None
        self.writes = 0

    def load(self):
        """Last-known-good config (without any command), or DEFAULT. Never raises."""
        try:
            with self.opener(self.path, "r") as f:
                raw = f.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ValueError("config file too large")
            cfg = json.loads(raw)
            why = validate_config(cfg)
            if why:
                raise ValueError(why)
            cfg["command"] = None
            self.saved_revision = cfg["revision"]
            return cfg
        except OSError:
            self.log("config: no cached config, using defaults")
        except Exception as e:
            self.log("config: cached config unusable (%s), using defaults" % (e,))
        return _copy(DEFAULT)

    def note(self, cfg):
        """Remember a validated config to persist. Written by flush() when allowed."""
        if cfg["revision"] == self.saved_revision and self.dirty is None:
            return
        c = _copy(cfg)
        c["command"] = None
        self.dirty = c

    def flush(self):
        """Write the pending config if due. Returns True if a write happened."""
        if self.dirty is None:
            return False
        now = self.clock.ms()
        if self.last_save is not None and self.clock.diff(now, self.last_save) < MIN_SAVE_MS:
            return False
        cfg = self.dirty
        try:
            f = self.opener(self.tmp, "w")
            try:
                f.write(json.dumps(cfg))
            finally:
                f.close()
            self.rename(self.tmp, self.path)  # atomic replace
        except Exception as e:
            self.log("config: save failed (%r), will retry later" % (e,))
            self.last_save = now
            return False
        self.saved_revision = cfg["revision"]
        self.dirty = None
        self.last_save = now
        self.writes += 1
        return True
