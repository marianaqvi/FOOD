// All API logic as plain (Request, Deps) => Response functions, so tests call them directly and the
// Next route files stay one-liners. Endpoints (paths are fixed by the brief):
//   GET  /api/device/config      device token     read-only config + at most one command
//   POST /api/device/heartbeat   device token     acks, reports effective limits
//   GET/PATCH /api/settings      staff session    durable settings with revisions
//   POST /api/settings/undo, GET /api/settings/history
//   POST /api/commands           staff session    play / event / idle / blackout / resume
//   GET  /api/status             staff session    online state, last command, device report
// Nothing here accepts code, paths, firmware or frames: only the validated enums and bounds in schema.ts.
import {
  TIMING,
  TTL,
  buildDeviceConfig,
  validateCommandRequest,
  validateHeartbeat,
  validateSettingsPatch,
} from "../schema";
import { clearSessionCookie, deviceAuthorized, makeSessionCookie, safeEqual, sameOriginOk, sessionValid } from "./auth";
import type { Env } from "./env";
import { clientKey, fail, json, readJson } from "./http";
import type { RateLimiter } from "./rate-limit";
import type { Command, Repository } from "./repository";

export interface Deps {
  repo: Repository;
  env: Env;
  limiter: RateLimiter;
  now: () => number;
  assetVersion: () => string;
}

const ONE_DAY_S = 24 * 3600;

type Guard = { actor: string } | Response;

async function staff(req: Request, d: Deps, mutating: boolean): Promise<Guard> {
  if (d.env.problems.length) return fail(503, "not_configured", d.env.problems);
  if (!d.limiter.check(`staff:${clientKey(req)}`, 240, 60_000, d.now())) return fail(429, "rate_limited", ["slow down"]);
  if (d.env.mode === "prod" && !sessionValid(req, d.env, d.now())) return fail(401, "unauthorized", ["sign in first"]);
  if (mutating && !sameOriginOk(req, d.env)) return fail(403, "bad_origin", ["cross-site or missing X-Requested-With"]);
  return { actor: d.env.mode === "mock" ? "mock-staff" : "staff" };
}

function deviceGuard(req: Request, d: Deps): Response | null {
  if (d.env.problems.length) return fail(503, "not_configured", d.env.problems);
  if (!d.limiter.check(`device:${d.env.deviceId}`, 240, 60_000, d.now())) return fail(429, "rate_limited", ["slow down"]);
  if (!deviceAuthorized(req, d.env)) return fail(401, "unauthorized", []);
  return null;
}

const iso = (ms: number) => new Date(ms).toISOString();

// ---- device ----------------------------------------------------------------------------

export async function deviceConfig(req: Request, d: Deps): Promise<Response> {
  const denied = deviceGuard(req, d);
  if (denied) return denied;
  const now = d.now();
  const [settings, command] = await Promise.all([d.repo.getSettings(), d.repo.servableCommand(now)]);
  return json(buildDeviceConfig(settings, command, d.assetVersion(), iso(now)));
}

export async function deviceHeartbeat(req: Request, d: Deps): Promise<Response> {
  const denied = deviceGuard(req, d);
  if (denied) return denied;
  const body = await readJson(req, 4096);
  if (!body.ok) return body.res;
  const v = validateHeartbeat(body.value);
  if (!v.ok) return fail(422, "invalid", v.errors);
  const now = d.now();
  await d.repo.recordHeartbeat(v.value, now);
  const settings = await d.repo.getSettings();
  return json({ ok: true, server_time: iso(now), settings_revision: settings.revision });
}

// ---- staff: settings ------------------------------------------------------------------

export async function getSettings(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, false);
  if (g instanceof Response) return g;
  return json({ settings: await d.repo.getSettings() });
}

export async function patchSettings(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, true);
  if (g instanceof Response) return g;
  const body = await readJson(req, 32_768);
  if (!body.ok) return body.res;
  const b = body.value as Record<string, unknown> | null;
  if (!b || typeof b !== "object" || Array.isArray(b)) return fail(422, "invalid", ["body must be an object"]);
  const extra = Object.keys(b).filter((k) => k !== "patch" && k !== "expected_revision");
  if (extra.length) return fail(422, "invalid", extra.map((k) => `${k}: unknown field`));
  if (b.expected_revision !== undefined && (!Number.isInteger(b.expected_revision) || (b.expected_revision as number) < 1)) return fail(422, "invalid", ["expected_revision: positive integer"]);
  const v = validateSettingsPatch(b.patch);
  if (!v.ok) return fail(422, "invalid", v.errors);
  const r = await d.repo.patchSettings(v.value, { actor: g.actor, now: d.now(), expectedRevision: b.expected_revision as number | undefined });
  if (!r.ok) return fail(r.code === "conflict" ? 409 : 422, r.code, r.errors, r.current ? { current: r.current } : {});
  return json({ settings: r.value });
}

export async function undoSettings(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, true);
  if (g instanceof Response) return g;
  let expected: number | undefined;
  if ((req.headers.get("content-length") ?? "0") !== "0") {
    const body = await readJson(req, 1024);
    if (!body.ok) return body.res;
    const e = (body.value as { expected_revision?: unknown } | null)?.expected_revision;
    if (e !== undefined) {
      if (!Number.isInteger(e)) return fail(422, "invalid", ["expected_revision: integer"]);
      expected = e as number;
    }
  }
  const r = await d.repo.undo({ actor: g.actor, now: d.now(), expectedRevision: expected });
  if (!r.ok) return fail(r.code === "conflict" ? 409 : r.code === "nothing_to_undo" ? 404 : 422, r.code, r.errors, r.current ? { current: r.current } : {});
  return json({ settings: r.value });
}

export async function getHistory(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, false);
  if (g instanceof Response) return g;
  return json({ history: await d.repo.listHistory(30) });
}

// ---- staff: commands ------------------------------------------------------------------

export function displayState(c: Command): "pending" | "applied" | "expired" | "superseded" {
  if (c.status === "applied") return "applied";
  if (c.status === "expired") return "expired";
  if (c.status === "superseded") return "superseded";
  return "pending";
}

export async function postCommand(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, true);
  if (g instanceof Response) return g;
  const body = await readJson(req, 2048);
  if (!body.ok) return body.res;
  const v = validateCommandRequest(body.value);
  if (!v.ok) return fail(422, "invalid", v.errors);
  const c = v.value;
  const now = d.now();
  const [settings, device] = await Promise.all([d.repo.getSettings(), d.repo.getDevice()]);
  const offline = !device || now - device.received_at > TIMING.offline_after * 1000;
  const base = { actor: g.actor, request_id: c.request_id ?? null, offline, applies_revision: null as number | null };
  const ttlFor = (asked: number | undefined) => {
    const t = asked ?? TTL.default;
    return offline ? Math.min(t, TTL.offline_max) : t; // an offline display must not wake up to a stale greeting
  };

  let created;
  if (c.type === "blackout" || c.type === "resume") {
    const s = await d.repo.setBlackout(c.type === "blackout", { actor: g.actor, now });
    created = await d.repo.createCommand({ ...base, type: c.type, reaction: null, speed: 1, cycles: 1, hold: false, ttl_s: ONE_DAY_S, source: "manual", event: null, applies_revision: s.revision }, now);
  } else if (c.type === "idle") {
    created = await d.repo.createCommand({ ...base, type: "idle", reaction: "idle", speed: 1, cycles: 1, hold: true, ttl_s: ttlFor(c.ttl_s), source: "manual", event: null }, now);
  } else {
    let reaction: string;
    let source: "manual" | "event" = "manual";
    let event: string | null = null;
    if (c.type === "event") {
      const mapped = settings.events[c.event];
      if (!mapped) return fail(422, "event_unmapped", [`${c.event} is not mapped to a reaction`]);
      reaction = mapped;
      source = "event";
      event = c.event;
    } else {
      reaction = c.reaction;
    }
    if (!settings.reactions[reaction].enabled) return fail(422, "reaction_disabled", [`${reaction} is disabled in settings`]);
    const rs = settings.reactions[reaction];
    const speed = c.type === "play" && c.speed !== undefined ? c.speed : rs.speed;
    const cycles = c.type === "play" && c.cycles !== undefined ? c.cycles : rs.cycles;
    const hold = c.type === "play" && c.hold === true;
    created = await d.repo.createCommand({ ...base, type: "play", reaction, speed, cycles, hold, ttl_s: ttlFor(c.ttl_s), source, event }, now);
  }
  const warning = offline && (c.type === "play" || c.type === "event" || c.type === "idle") ? `display is offline: this reaction expires in ${Math.min(TTL.offline_max, TTL.default)} s if it does not reconnect` : null;
  return json({ command: created.command, replayed: created.replayed, display_state: displayState(created.command), warning }, created.replayed ? 200 : 201);
}

// ---- staff: status --------------------------------------------------------------------

export async function getStatus(req: Request, d: Deps): Promise<Response> {
  const g = await staff(req, d, false);
  if (g instanceof Response) return g;
  const now = d.now();
  const [settings, device, commands] = await Promise.all([d.repo.getSettings(), d.repo.getDevice(), d.repo.getCommands(10, now)]);
  const last = commands.length ? commands[commands.length - 1] : null;
  const age = device ? Math.max(0, Math.round((now - device.received_at) / 1000)) : null;
  return json({
    mode: d.env.mode,
    server_time: iso(now),
    settings_revision: settings.revision,
    blackout: settings.blackout,
    timing: TIMING,
    device: device
      ? {
          seen: true,
          online: age! <= TIMING.offline_after,
          last_heartbeat_at: iso(device.received_at),
          age_s: age,
          simulated: device.simulated === true,
          fw_version: device.fw_version,
          asset_version: device.asset_version,
          config_revision_applied: device.config_revision,
          config_in_sync: device.config_revision === settings.revision,
          reaction: device.reaction,
          state: device.state,
          blackout_reported: device.blackout,
          brightness_permille: device.brightness_permille,
          effective_cap_permille: device.effective_cap_permille,
          last_command_id: device.last_command_id,
        }
      : { seen: false, online: false },
    last_command: last ? { ...last, display_state: displayState(last) } : null,
    commands: commands.map((c) => ({ id: c.id, type: c.type, reaction: c.reaction, status: c.status, display_state: displayState(c), issued_at: c.issued_at })),
  });
}

// ---- staff session ----------------------------------------------------------------------

export async function session(req: Request, d: Deps): Promise<Response> {
  if (d.env.problems.length) return fail(503, "not_configured", d.env.problems);
  if (d.env.mode === "mock") return json({ authenticated: true, mode: "mock" });
  return json({ authenticated: sessionValid(req, d.env, d.now()), mode: "prod" });
}

export async function login(req: Request, d: Deps): Promise<Response> {
  if (d.env.problems.length) return fail(503, "not_configured", d.env.problems);
  if (d.env.mode === "mock") return json({ authenticated: true, mode: "mock" });
  if (!d.limiter.check(`login:${clientKey(req)}`, 10, 15 * 60_000, d.now())) return fail(429, "rate_limited", ["too many attempts"]);
  if (!sameOriginOk(req, d.env)) return fail(403, "bad_origin", []);
  const body = await readJson(req, 1024);
  if (!body.ok) return body.res;
  const pw = (body.value as { password?: unknown } | null)?.password;
  if (typeof pw !== "string" || !safeEqual(pw, d.env.staffPassword!)) return fail(401, "unauthorized", ["wrong password"]);
  const secure = new URL(req.url).protocol === "https:";
  return json({ authenticated: true, mode: "prod" }, 200, { "set-cookie": makeSessionCookie(d.env, d.now(), secure) });
}

export async function logout(req: Request, d: Deps): Promise<Response> {
  if (!sameOriginOk(req, d.env)) return fail(403, "bad_origin", []);
  return json({ authenticated: false }, 200, { "set-cookie": clearSessionCookie() });
}
