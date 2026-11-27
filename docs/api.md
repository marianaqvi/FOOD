# Control room API and device contract (milestone 3)

Status: implemented and tested against a software simulator AND against the real firmware modules running on the Mac with a fake display (`tests/e2e_device_vs_server.py`). The board itself has not been connected yet (see `docs/hardware-proof.md` Part F).

## Run it (development, no credentials)

```bash
cd web
export PATH="$HOME/.local/node/bin:$PATH"
npm install                    # first time only
MOCK_MODE=1 npm run dev        # http://localhost:3000, no staff login, banner says MOCK MODE
node scripts/sim-device.mjs    # optional second terminal: a SIMULATED display (reports simulated:true)
npm test                       # 66 tests (5 sprite parity + 61 API)
```

State is kept in `web/.data/state.json` (git-ignored, atomic write with a `.bak` copy). In mock mode a random device token is created at `web/.data/dev-device-token`. Outside mock mode the server **fails closed** (HTTP 503) unless `STAFF_PASSWORD` (12+ chars), `SESSION_SECRET` (32+) and `DEVICE_TOKEN` (32+) are set; see `web/.env.example`. Nothing secret is in the repo or the browser bundle.

## Endpoints

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /api/device/config` | device bearer token | Current config plus at most one unexpired, unacknowledged command |
| `POST /api/device/heartbeat` | device bearer token | Acks, reports effective limits (4 KB max) |
| `GET /api/settings`, `PATCH /api/settings` | staff session | Durable settings, revisions, `expected_revision` conflict check |
| `POST /api/settings/undo`, `GET /api/settings/history` | staff session | Undo and change history (blackout is never undone) |
| `POST /api/commands` | staff session | `play`, `event`, `idle`, `blackout`, `resume` (2 KB max) |
| `GET /api/status` | staff session | Online state, last command, what the display itself reported |
| `POST /api/auth/login`, `/logout`, `GET /api/auth/session` | none / session | Staff session cookie (HttpOnly, SameSite=Strict, 8 h) |

State-changing staff calls need `X-Requested-With: control-room` and, when the browser sends `Origin`, it must match `Host` (or `ALLOWED_ORIGINS`). Rate limits (in memory, per instance): staff 240/min, device 240/min, login 10 per 15 min.

## Device config (what the firmware will read)

```json
{"schema_version":1,"revision":5,"asset_version":"f02e018d6e95",
 "colors":{"sheep_a":"#F0F5F1","sheep_b":"#FFB34F","effects":"#F0F5F1"},
 "brightness_percent":75,"ambient":{"mode":"idle","rotation":[],"interval_s":120},
 "enabled_reactions":["idle","wake","..."],
 "command":{"id":"uuid","type":"play","reaction":"birthday","speed":1,"cycles":1,"hold":false,"expires_at":"UTC ISO"},
 "blackout":false,"poll_interval_s":2,"heartbeat_interval_s":15,"server_time":"UTC ISO"}
```

`brightness_percent` is a percentage of the **firmware's own cap** (`power.HARD_MAX_PERMILLE`), never raw output. Firmware must clamp regardless of what it receives.

## Command lifecycle (what the UI shows)

1. Every click on Send or Replay is a new command with a fresh UUID. The same client `request_id` returns the same command (idempotent).
2. `queued` then `delivered` (the device fetched it) then **`applied` only when a heartbeat carries `last_command_id` equal to it**. Until then the UI says Pending.
3. A command expires after its TTL (default 30 s, 5 to 300). If no heartbeat was seen in the last 45 s when it is sent, the TTL is cut to 30 s and the UI warns: an offline display must not wake to a stale greeting.
4. An acknowledged command is never served again, so a reboot cannot replay it. A newer play/idle supersedes older unacknowledged ones.
5. Blackout and resume change settings (revision bump) and are applied when the device reports that revision. Blackout survives restarts until an explicit resume.

Firmware expectations for milestone 4: poll every `poll_interval_s`, send a heartbeat every `heartbeat_interval_s` **and immediately after applying a command or a new revision**, drop commands whose `expires_at` has passed by its own clock (never replay on boot), cache only a validated last-known-good config atomically, keep playing offline.

## Known gaps

- Firmware side written and host-tested, NOT yet run on the board: polling, config cache, ambient rotation, brightness from config. Per-reaction default speed and cycles are server-side only (commands carry them). No watchdog yet.
- No browser automation suite (Playwright) yet: UI was driven by hand in the Browser pane (send, edit and save, blackout and resume, offline, phone width). API logic has automated tests with mutation checks.
- `file-repository.ts` triggers a Turbopack "dynamic filesystem access" build warning. It is the development repository only; production replaces it with Supabase behind the same `Repository` interface (milestone 5).
- Rate limiting is per process; production needs a shared store. Dev traffic is cleartext HTTP on a trusted LAN only; production must be HTTPS with certificate validation.
- No Supabase adapter, no deployment, no week-long test.
