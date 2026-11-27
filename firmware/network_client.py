# firmware/network_client.py
# Cooperative (non-blocking) HTTP client and Wi-Fi manager. MicroPython and CPython compatible.
#
#   - Http: ONE request at a time as a small state machine over a non-blocking socket. step() does
#     a bounded amount of work and never waits, so the animation loop keeps its frame timing.
#     Every request has an overall deadline (default 4 s). HTTP/1.0, Connection: close, responses
#     capped at MAX_BODY bytes. Plain HTTP only: TLS is NOT handled here (milestone 5 uses a
#     trusted TLS gateway or a tested TLS transport; certificate checks are never disabled).
#   - Wifi: non-blocking connect with backoff; reconnects by itself.
#   - NetClient: poll /api/device/config about every 2 s and POST /api/device/heartbeat about every
#     15 s (and promptly when something changed), with exponential backoff plus jitter on failure.
#
# Hostnames: resolution (getaddrinfo) can block. Use an IP address for the LAN proof of concept;
# the result is cached for the life of the client.

import json

try:
    import errno
except ImportError:  # pragma: no cover
    errno = None
import select
import socket

MAX_BODY = 4096
MAX_HEADER = 1024
WOULD_BLOCK = tuple(
    v for v in (getattr(errno, "EAGAIN", 11), getattr(errno, "EWOULDBLOCK", 11), getattr(errno, "EINPROGRESS", 115), getattr(errno, "EALREADY", 114), getattr(errno, "EINTR", 4)) if v
)
IDLE, CONNECTING, SENDING, READING = 0, 1, 2, 3


def _errno(e):
    try:
        return e.args[0]
    except Exception:
        return None


def dechunk(data):
    """Decode a chunked body. Returns (complete, bytes). Incomplete data returns (False, b'')."""
    out = b""
    i = 0
    while True:
        j = data.find(b"\r\n", i)
        if j < 0:
            return False, b""
        try:
            n = int(data[i:j].split(b";")[0], 16)
        except ValueError:
            raise ValueError("bad chunk size")
        i = j + 2
        if n == 0:
            return True, out
        if len(data) < i + n + 2:
            return False, b""
        out += data[i:i + n]
        i += n + 2


class Http:
    def __init__(self, host, port, token, clock, sock_mod=socket, sel_mod=select, timeout_ms=4000, max_body=MAX_BODY):
        self.host, self.port, self.token = host, port, token
        self.clock = clock
        self.sock_mod, self.sel_mod = sock_mod, sel_mod
        self.timeout_ms = timeout_ms
        self.max_body = max_body
        self.addr = None
        self.family = None
        self.state = IDLE
        self.sock = None
        self.poller = None
        self.result = None  # (status, body bytes, error) once finished
        self.req = b""
        self.off = 0
        self.buf = b""
        self.deadline = 0
        self.started = 0

    @property
    def busy(self):
        return self.state != IDLE

    def _resolve(self):
        info = self.sock_mod.getaddrinfo(self.host, self.port, 0, self.sock_mod.SOCK_STREAM)[0]
        self.family, self.addr = info[0], info[-1]

    def start(self, method, path, body=None):
        """Begin a request. Returns False if one is already running. Failures finish immediately
        with result = (None, None, reason), so callers always look at `result` once not busy."""
        if self.state != IDLE:
            return False
        self.result = None
        self.buf = b""
        self.off = 0
        try:
            if self.addr is None:
                self._resolve()
            head = "%s %s HTTP/1.0\r\nHost: %s\r\nAuthorization: Bearer %s\r\nUser-Agent: i75w\r\nConnection: close\r\n" % (method, path, self.host, self.token)
            if body is not None:
                head += "Content-Type: application/json\r\nContent-Length: %d\r\n" % len(body)
            self.req = (head + "\r\n").encode() + (body.encode() if body is not None else b"")
            s = self.sock_mod.socket(self.family, self.sock_mod.SOCK_STREAM)
            self.sock = s
            s.setblocking(False)
            self.poller = self.sel_mod.poll()
            self.poller.register(s, self.sel_mod.POLLOUT)
            try:
                s.connect(self.addr)
            except OSError as e:
                if _errno(e) not in WOULD_BLOCK:
                    raise
        except Exception as e:
            self.addr = None  # re-resolve next time
            self._fail("connect: %r" % (e,))
            return True
        self.started = self.clock.ms()
        self.deadline = self.clock.add(self.started, self.timeout_ms)
        self.state = CONNECTING
        return True

    def _close(self):
        s, p = self.sock, self.poller
        self.sock = self.poller = None
        self.state = IDLE
        try:
            if p is not None and s is not None:
                p.unregister(s)
        except Exception:
            pass
        try:
            if s is not None:
                s.close()
        except Exception:
            pass

    def _fail(self, why):
        self._close()
        self.result = (None, None, why)

    def _finish(self):
        try:
            status, body = self._parse()
        except Exception as e:
            self._fail("bad response: %r" % (e,))
            return
        self._close()
        self.result = (status, body, None)

    def _split(self):
        i = self.buf.find(b"\r\n\r\n")
        if i < 0:
            return None
        head = self.buf[:i].split(b"\r\n")
        parts = head[0].split(b" ")
        if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
            raise ValueError("bad status line")
        hdr = {}
        for line in head[1:]:
            k, _, v = line.partition(b":")
            hdr[k.strip().lower()] = v.strip()
        return int(parts[1]), hdr, self.buf[i + 4:]

    def _parse(self):
        sp = self._split()
        if sp is None:
            raise ValueError("no headers")
        status, hdr, body = sp
        if hdr.get(b"transfer-encoding", b"").lower() == b"chunked":
            ok, body = dechunk(self.buf[self.buf.find(b"\r\n\r\n") + 4:])
            if not ok:
                raise ValueError("truncated chunked body")
        else:
            cl = hdr.get(b"content-length")
            if cl is not None and len(body) < int(cl):
                raise ValueError("truncated body")
            if cl is not None:
                body = body[:int(cl)]
        if len(body) > self.max_body:
            raise ValueError("body too large")
        return status, body

    def _complete_by_length(self):
        sp = self._split()
        if sp is None:
            return False
        status, hdr, body = sp
        cl = hdr.get(b"content-length")
        return cl is not None and len(body) >= int(cl)

    def step(self):
        """Advance the request a little. Returns immediately."""
        if self.state == IDLE:
            return
        if self.clock.diff(self.clock.ms(), self.deadline) >= 0:
            self._fail("timeout")
            return
        try:
            if self.state == CONNECTING:
                for _o, ev in self.poller.poll(0):
                    if ev & (self.sel_mod.POLLERR | self.sel_mod.POLLHUP):
                        self.addr = None
                        self._fail("connection refused or reset")
                        return
                    if ev & self.sel_mod.POLLOUT:
                        self.state = SENDING
            if self.state == SENDING:
                try:
                    n = self.sock.send(memoryview(self.req)[self.off:])
                except OSError as e:
                    if _errno(e) in WOULD_BLOCK:
                        return
                    raise
                self.off += n or 0
                if self.off >= len(self.req):
                    self.state = READING
            if self.state == READING:
                for _ in range(4):  # bounded work per step
                    try:
                        data = self.sock.recv(512)
                    except OSError as e:
                        if _errno(e) in WOULD_BLOCK:
                            return
                        raise
                    if data is None:
                        return
                    if not data:  # server closed: response complete
                        self._finish()
                        return
                    self.buf += data
                    if len(self.buf) > self.max_body + MAX_HEADER:
                        self._fail("response too large")
                        return
                    if self._complete_by_length():
                        self._finish()
                        return
        except Exception as e:
            self._fail("io: %r" % (e,))


class Wifi:
    CONNECT_TIMEOUT_MS = 20000

    def __init__(self, wlan, ssid, password, clock, log=print, rand=None):
        self.wlan, self.ssid, self.password = wlan, ssid, password
        self.clock, self.log = clock, log
        self.rand = rand or (lambda n: 0)
        self.started = False
        self.connected = False
        self.attempt_at = None
        self.next_attempt = None
        self.fails = 0

    def rssi(self):
        try:
            v = self.wlan.status("rssi")
            return v if isinstance(v, int) and -150 <= v <= 0 else None
        except Exception:
            return None

    def _failed(self, now, why):
        self.fails += 1
        delay = min(60000, 5000 << min(self.fails - 1, 4)) + self.rand(1000)
        self.next_attempt = self.clock.add(now, delay)
        self.attempt_at = None
        self.log("wifi: %s, retry in %d s" % (why, delay // 1000))
        try:
            self.wlan.disconnect()
        except Exception:
            pass

    def step(self):
        now = self.clock.ms()
        if not self.started:
            self.wlan.active(True)
            self.started = True
        if self.wlan.isconnected():
            if not self.connected:
                self.log("wifi: connected")
            self.connected = True
            self.fails = 0
            self.attempt_at = None
            self.next_attempt = None
            return
        if self.connected:
            self.connected = False
            self.log("wifi: lost")
            self.attempt_at = None
        if self.attempt_at is not None:
            try:
                st = self.wlan.status()
            except Exception:
                st = 0
            if isinstance(st, int) and st < 0:
                self._failed(now, "connect failed (status %d)" % st)
            elif self.clock.diff(now, self.attempt_at) >= self.CONNECT_TIMEOUT_MS:
                self._failed(now, "connect timed out")
            return
        if self.next_attempt is not None and self.clock.diff(now, self.next_attempt) < 0:
            return
        self.wlan.connect(self.ssid, self.password)
        self.attempt_at = now


class NetClient:
    BACKOFF_MAX_MS = 30000

    def __init__(self, http, wifi, clock, on_config, heartbeat_payload, log=print, rand=None):
        self.http, self.wifi, self.clock = http, wifi, clock
        self.on_config = on_config
        self.heartbeat_payload = heartbeat_payload
        self.log = log
        self.rand = rand or (lambda n: 0)
        self.poll_ms = 2000
        self.hb_ms = 15000
        self.next_poll = None
        self.next_hb = None
        self.hb_dirty = True
        self.pending = None
        self.fails = 0
        self.backoff_until = None
        self.last_ok = None
        self.requests = 0

    def set_intervals(self, poll_s, hb_s):
        self.poll_ms = poll_s * 1000
        self.hb_ms = hb_s * 1000

    def request_heartbeat(self):
        self.hb_dirty = True

    def reachable(self):
        """True if a request succeeded recently (within three poll intervals)."""
        return self.last_ok is not None and self.clock.diff(self.clock.ms(), self.last_ok) < 3 * self.poll_ms + 5000

    def _due(self, at, now):
        return at is None or self.clock.diff(now, at) >= 0

    def _fail(self, now, kind, why):
        self.fails += 1
        delay = min(self.BACKOFF_MAX_MS, 2000 << min(self.fails - 1, 4)) + self.rand(500)
        self.backoff_until = self.clock.add(now, delay)
        self.log("net: %s failed (%s), backing off %d ms" % (kind, why, delay))

    def _complete(self, now):
        status, body, err = self.http.result
        kind, self.pending = self.pending, None
        if err or status != 200:
            self._fail(now, kind, err or "HTTP %s" % (status,))
            return
        if kind == "config":
            try:
                cfg = json.loads(body)
            except Exception:
                self._fail(now, kind, "invalid JSON")
                return
            self.fails = 0
            self.last_ok = now
            self.next_poll = self.clock.add(now, self.poll_ms)
            self.on_config(cfg)
        else:
            self.fails = 0
            self.last_ok = now
            self.hb_dirty = False
            self.next_hb = self.clock.add(now, self.hb_ms)

    def step(self):
        self.wifi.step()
        now = self.clock.ms()
        if self.http.busy:
            self.http.step()
            if not self.http.busy:
                self._complete(self.clock.ms())
            return
        if not self.wifi.connected:
            return
        if self.backoff_until is not None and self.clock.diff(now, self.backoff_until) < 0:
            return
        if self.hb_dirty or self._due(self.next_hb, now):
            body = json.dumps(self.heartbeat_payload())
            self.pending = "heartbeat"
            self.requests += 1
            self.http.start("POST", "/api/device/heartbeat", body)
        elif self._due(self.next_poll, now):
            self.pending = "config"
            self.requests += 1
            self.http.start("GET", "/api/device/config")
        else:
            return
        if not self.http.busy:  # failed instantly (e.g. connect error)
            self._complete(self.clock.ms())
