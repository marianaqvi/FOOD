import { mkdtempSync, writeFileSync, readFileSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { FileRepository } from "@/lib/server/file-repository";
import * as h from "@/lib/server/handlers";
import { loadEnv, type Env } from "@/lib/server/env";
import { RateLimiter } from "@/lib/server/rate-limit";
import { defaultSettings, validateSettingsPatch, validateCommandRequest, validateHeartbeat } from "@/lib/schema";

const TOKEN = "t".repeat(40);
const URL0 = "http://localhost:3000";
let clock = 1_700_000_000_000;
let dir: string;
let deps: h.Deps;

function makeDeps(envOver: Partial<Record<string, string>> = { MOCK_MODE: "1", DEVICE_TOKEN: TOKEN }): h.Deps {
  dir = mkdtempSync(join(tmpdir(), "fc-"));
  const env: Env = loadEnv({ DATA_DIR: dir, ...envOver });
  return { env, repo: new FileRepository(join(dir, "state.json")), limiter: new RateLimiter(), now: () => clock, assetVersion: () => "abc123def456" };
}
function rq(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Request {
  const init: RequestInit = { method, headers: { ...headers } };
  if (body !== undefined) {
    (init.headers as Record<string, string>)["content-type"] = "application/json";
    init.body = typeof body === "string" ? body : JSON.stringify(body);
  }
  return new Request(URL0 + path, init);
}
const staffH = { "x-requested-with": "control-room" };
const devH = { authorization: `Bearer ${TOKEN}` };
const hb = (over: Record<string, unknown> = {}) => ({
  fw_version: "test-1", asset_version: "abc123def456", config_revision: 1, last_command_id: null, reaction: "idle", state: "idle",
  blackout: false, brightness_permille: 200, effective_cap_permille: 200, uptime_s: 5, ...over,
});
async function j(res: Response) {
  return res.json();
}
async function play(body: Record<string, unknown> = {}) {
  return h.postCommand(rq("POST", "/api/commands", { type: "play", reaction: "wave", request_id: "req-" + Math.random().toString(36).slice(2, 12), ...body }, staffH), deps);
}
async function heartbeat(over: Record<string, unknown> = {}) {
  return h.deviceHeartbeat(rq("POST", "/api/device/heartbeat", hb(over), devH), deps);
}

beforeEach(() => {
  clock = 1_700_000_000_000;
  deps = makeDeps();
});

describe("schema validation", () => {
  it("accepts a sensible patch and normalises hex to upper case", () => {
    const v = validateSettingsPatch({ colors: { sheep_a: "#ffb34f" }, brightness_percent: 60, names: { sheep_a: "Dolly" } });
    expect(v).toEqual({ ok: true, value: { colors: { sheep_a: "#FFB34F" }, brightness_percent: 60, names: { sheep_a: "Dolly" } } });
  });
  it.each([
    [{ colors: { sheep_a: "red" } }],
    [{ colors: { sheep_a: "#FFF" } }],
    [{ brightness_percent: 101 }],
    [{ brightness_percent: -1 }],
    [{ brightness_percent: 50.5 }],
    [{ names: { sheep_a: "<script>" } }],
    [{ names: { sheep_a: "" } }],
    [{ names: { sheep_a: "x".repeat(25) } }],
    [{ reactions: { nope: { enabled: true } } }],
    [{ reactions: { wave: { speed: 2 } } }],
    [{ reactions: { wave: { speed: 0.1 } } }],
    [{ reactions: { wave: { cycles: 99 } } }],
    [{ reactions: { wave: { speed: 1, exec: "rm -rf" } } }],
    [{ events: { "made.up": "wave" } }],
    [{ events: { birthday: "not_a_reaction" } }],
    [{ ambient: { mode: "party" } }],
    [{ ambient: { interval_s: 5 } }],
    [{ hardware_cap: 1000 }],
    [{ blackout: true }],
    [{ revision: 99 }],
    ["string"],
    [[1, 2]],
  ])("rejects %j", (bad) => {
    expect(validateSettingsPatch(bad).ok).toBe(false);
  });
  it("cannot smuggle a brightness above 100% of the firmware cap", () => {
    expect(validateSettingsPatch({ brightness_percent: 150 }).ok).toBe(false);
    expect(validateSettingsPatch({ brightness_percent: 100 }).ok).toBe(true);
  });
  it("validates commands strictly", () => {
    expect(validateCommandRequest({ type: "play", reaction: "wave", speed: 0.5, cycles: 3 }).ok).toBe(true);
    for (const bad of [
      { type: "play", reaction: "wave", speed: 2 }, { type: "play", reaction: "wave", cycles: 0 }, { type: "play", reaction: "x" },
      { type: "play" }, { type: "firmware", url: "http://x" }, { type: "play", reaction: "wave", ttl_s: 99999 },
      { type: "play", reaction: "wave", script: "alert(1)" }, { type: "event", event: "bogus" }, { type: "idle", request_id: "short" },
    ]) expect(validateCommandRequest(bad).ok, JSON.stringify(bad)).toBe(false);
  });
  it("validates heartbeats and rejects unknown fields", () => {
    expect(validateHeartbeat(hb()).ok).toBe(true);
    expect(validateHeartbeat(hb({ extra: 1 })).ok).toBe(false);
    expect(validateHeartbeat(hb({ state: "on fire" })).ok).toBe(false);
    expect(validateHeartbeat(hb({ last_command_id: "not-a-uuid" })).ok).toBe(false);
    expect(validateHeartbeat(hb({ effective_cap_permille: 5000 })).ok).toBe(false);
  });
  it("applyPatch refuses disabling idle, mapping a disabled reaction, and empty rotation", () => {
    const base = defaultSettings();
    const off = validateSettingsPatch({ reactions: { idle: { enabled: false } } });
    expect(off.ok).toBe(true);
    // via the repository (cross-field rules live in applyPatch)
    return Promise.all([
      deps.repo.patchSettings((off as any).value, { actor: "t", now: clock }),
      deps.repo.patchSettings({ reactions: { birthday: { enabled: false } } }, { actor: "t", now: clock }),
      deps.repo.patchSettings({ ambient: { mode: "rotation", rotation: [] } }, { actor: "t", now: clock }),
    ]).then(([a, b, c]) => {
      expect(base.revision).toBe(1);
      expect(a.ok).toBe(false);
      expect(b.ok).toBe(false); // birthday is mapped to the birthday event
      expect(c.ok).toBe(false);
    });
  });
});

describe("mode and authentication", () => {
  it("fails closed outside mock mode when secrets are missing", async () => {
    const d = makeDeps({});
    expect(d.env.problems.length).toBe(3);
    for (const res of [await h.getStatus(rq("GET", "/api/status"), d), await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), d), await h.session(rq("GET", "/api/auth/session"), d)]) {
      expect(res.status).toBe(503);
    }
  });
  it("rejects short secrets", () => {
    expect(loadEnv({ DATA_DIR: dir, STAFF_PASSWORD: "short", SESSION_SECRET: "s", DEVICE_TOKEN: "t" }).problems.length).toBe(3);
  });
  it("mock mode writes a random device token into the data dir, not the repo", () => {
    const e = loadEnv({ DATA_DIR: dir, MOCK_MODE: "1" });
    expect(e.deviceToken).toMatch(/^[0-9a-f]{48}$/);
    expect(readFileSync(join(dir, "dev-device-token"), "utf8").trim()).toBe(e.deviceToken);
  });
  const prodEnv = { STAFF_PASSWORD: "correct horse battery", SESSION_SECRET: "s".repeat(40), DEVICE_TOKEN: TOKEN };
  it("prod mode needs a session; login sets an httpOnly strict cookie; bad password is refused", async () => {
    const d = makeDeps(prodEnv);
    expect((await h.getSettings(rq("GET", "/api/settings"), d)).status).toBe(401);
    const bad = await h.login(rq("POST", "/api/auth/login", { password: "nope" }, staffH), d);
    expect(bad.status).toBe(401);
    const ok = await h.login(rq("POST", "/api/auth/login", { password: prodEnv.STAFF_PASSWORD }, staffH), d);
    expect(ok.status).toBe(200);
    const cookie = ok.headers.get("set-cookie")!;
    expect(cookie).toMatch(/HttpOnly/);
    expect(cookie).toMatch(/SameSite=Strict/);
    const sess = cookie.split(";")[0];
    expect((await h.getSettings(rq("GET", "/api/settings", undefined, { cookie: sess }), d)).status).toBe(200);
    // tampered cookie
    expect((await h.getSettings(rq("GET", "/api/settings", undefined, { cookie: sess.slice(0, -2) + "xx" }), d)).status).toBe(401);
    // expired session
    clock += 9 * 3600 * 1000;
    expect((await h.getSettings(rq("GET", "/api/settings", undefined, { cookie: sess }), d)).status).toBe(401);
  });
  it("login is rate limited", async () => {
    const d = makeDeps(prodEnv);
    let last = 0;
    for (let i = 0; i < 12; i++) last = (await h.login(rq("POST", "/api/auth/login", { password: "bad" + i }, staffH), d)).status;
    expect(last).toBe(429);
  });
  it("mutating staff calls need the CSRF header and a same-origin Origin", async () => {
    expect((await h.patchSettings(rq("PATCH", "/api/settings", { patch: {} }), deps)).status).toBe(403);
    expect((await h.patchSettings(rq("PATCH", "/api/settings", { patch: {} }, { ...staffH, origin: "https://evil.example" }), deps)).status).toBe(403);
    expect((await h.patchSettings(rq("PATCH", "/api/settings", { patch: {} }, { ...staffH, origin: "http://localhost:3000", host: "localhost:3000" }), deps)).status).toBe(200);
  });
  it("device endpoints need the device token", async () => {
    expect((await h.deviceConfig(rq("GET", "/api/device/config"), deps)).status).toBe(401);
    expect((await h.deviceConfig(rq("GET", "/api/device/config", undefined, { authorization: "Bearer wrong" }), deps)).status).toBe(401);
    expect((await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps)).status).toBe(200);
    expect((await h.deviceHeartbeat(rq("POST", "/api/device/heartbeat", hb()), deps)).status).toBe(401);
  });
  it("a staff session cannot be used as device auth and the device token cannot read settings in prod", async () => {
    const d = makeDeps(prodEnv);
    expect((await h.getSettings(rq("GET", "/api/settings", undefined, devH), d)).status).toBe(401);
  });
});

describe("request limits", () => {
  it("rejects oversized and malformed bodies", async () => {
    expect((await h.deviceHeartbeat(rq("POST", "/api/device/heartbeat", "x".repeat(5000), devH), deps)).status).toBe(413);
    expect((await h.deviceHeartbeat(rq("POST", "/api/device/heartbeat", "{bad", devH), deps)).status).toBe(400);
    expect((await h.postCommand(rq("POST", "/api/commands", "x".repeat(3000), staffH), deps)).status).toBe(413);
    const noType = new Request(URL0 + "/api/commands", { method: "POST", headers: staffH, body: "{}" });
    expect((await h.postCommand(noType, deps)).status).toBe(415);
  });
  it("rate limits the device", async () => {
    let last = 0;
    for (let i = 0; i < 245; i++) last = (await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps)).status;
    expect(last).toBe(429);
  });
});

describe("settings: persistence, revisions, history, undo", () => {
  const patch = (p: unknown, expected?: number) => h.patchSettings(rq("PATCH", "/api/settings", { patch: p, ...(expected ? { expected_revision: expected } : {}) }, staffH), deps);
  it("starts with the approved defaults", async () => {
    const s = (await j(await h.getSettings(rq("GET", "/api/settings"), deps))).settings;
    expect(s.colors).toEqual({ sheep_a: "#F0F5F1", sheep_b: "#F0F5F1", effects: "#F0F5F1" });
    expect(s.revision).toBe(1);
    expect(s.blackout).toBe(false);
  });
  it("a valid edit bumps the revision and survives a restart", async () => {
    const r = await patch({ colors: { sheep_b: "#ffb34f" }, brightness_percent: 70 }, 1);
    expect(r.status).toBe(200);
    const again = new FileRepository(join(dir, "state.json"));
    const s = await again.getSettings();
    expect(s.revision).toBe(2);
    expect(s.colors.sheep_b).toBe("#FFB34F");
    expect(s.brightness_percent).toBe(70);
  });
  it("a stale expected_revision is refused with the current settings", async () => {
    await patch({ brightness_percent: 10 });
    const r = await patch({ brightness_percent: 20 }, 1);
    expect(r.status).toBe(409);
    expect((await j(r)).current.brightness_percent).toBe(10);
  });
  it("undo restores the previous values, records history, and never rolls back blackout", async () => {
    await patch({ colors: { sheep_a: "#FF0000" } });
    await patch({ brightness_percent: 30 });
    await h.postCommand(rq("POST", "/api/commands", { type: "blackout" }, staffH), deps);
    const u1 = await j(await h.undoSettings(rq("POST", "/api/settings/undo", {}, staffH), deps));
    expect(u1.settings.brightness_percent).toBe(100);
    expect(u1.settings.colors.sheep_a).toBe("#FF0000");
    expect(u1.settings.blackout).toBe(true);
    const u2 = await j(await h.undoSettings(rq("POST", "/api/settings/undo", {}, staffH), deps));
    expect(u2.settings.colors.sheep_a).toBe("#F0F5F1");
    expect((await h.undoSettings(rq("POST", "/api/settings/undo", {}, staffH), deps)).status).toBe(404);
    const hist = (await j(await h.getHistory(rq("GET", "/api/settings/history"), deps))).history;
    expect(hist.map((e: any) => e.kind)).toEqual(["undo", "undo", "blackout", "settings", "settings"]);
    expect(hist.every((e: any) => !("before" in e))).toBe(true);
  });
  it("disabling a reaction blocks sending it", async () => {
    await patch({ events: { "gesture.wave": null }, reactions: { wave: { enabled: false } } });
    const r = await play({ reaction: "wave" });
    expect(r.status).toBe(422);
    expect((await j(r)).error).toBe("reaction_disabled");
  });
  it("a corrupt state file falls back safely and keeps a copy", () => {
    const f = join(dir, "state.json");
    writeFileSync(f, "{ this is not json");
    const repo = new FileRepository(f);
    return repo.getSettings().then((s) => {
      expect(s.revision).toBe(1);
      expect(readdirSync(dir).some((n) => n.startsWith("state.json.corrupt-"))).toBe(true);
    });
  });
  it("recovers from the previous copy when the main file is damaged", async () => {
    await patch({ brightness_percent: 40 });
    await patch({ brightness_percent: 41 });
    writeFileSync(join(dir, "state.json"), "garbage");
    const repo = new FileRepository(join(dir, "state.json"));
    const s = await repo.getSettings();
    expect(s.brightness_percent).toBe(40);
    expect(repo.recoveredFrom).toMatch(/\.bak$/);
  });
  it("writes atomically (no leftover temp file)", async () => {
    await patch({ brightness_percent: 50 });
    expect(existsSync(join(dir, "state.json.tmp"))).toBe(false);
  });
});

describe("commands, idempotency, expiry and acknowledgement", () => {
  it("manual play creates a command the device receives once and acknowledges", async () => {
    await heartbeat();
    const created = await j(await play({ reaction: "birthday", speed: 0.5, cycles: 2 }));
    expect(created.command.status).toBe("queued");
    expect(created.display_state).toBe("pending");
    const cfg = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg.command).toMatchObject({ id: created.command.id, type: "play", reaction: "birthday", speed: 0.5, cycles: 2, hold: false });
    // still pending until the device says so
    let st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.last_command.display_state).toBe("pending");
    await heartbeat({ last_command_id: created.command.id, reaction: "birthday", state: "playing" });
    st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.last_command.display_state).toBe("applied");
    expect(st.device.reaction).toBe("birthday");
    // an acknowledged command is never served again, so a reboot cannot replay it
    const cfg2 = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg2.command).toBeNull();
  });
  it("the same request_id returns the same command and is not queued twice", async () => {
    const a = await play({ request_id: "same-request-1" });
    const b = await play({ request_id: "same-request-1" });
    expect(a.status).toBe(201);
    expect(b.status).toBe(200);
    const [ja, jb] = [await j(a), await j(b)];
    expect(jb.replayed).toBe(true);
    expect(jb.command.id).toBe(ja.command.id);
  });
  it("replaying the same reaction with a new request creates a NEW command id", async () => {
    const a = await j(await play({ reaction: "wave" }));
    const b = await j(await play({ reaction: "wave" }));
    expect(b.command.id).not.toBe(a.command.id);
    const st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.commands.find((c: any) => c.id === a.command.id).status).toBe("superseded");
    const cfg = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg.command.id).toBe(b.command.id);
  });
  it("expired commands are not served and show as expired", async () => {
    await heartbeat();
    const a = await j(await play({ ttl_s: 10 }));
    clock += 11_000;
    const cfg = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg.command).toBeNull();
    await heartbeat();
    const st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.commands.find((c: any) => c.id === a.command.id).display_state).toBe("expired");
  });
  it("an offline display gets a short expiry and a warning so it does not wake to a stale greeting", async () => {
    const r = await j(await play({ ttl_s: 300 }));
    expect(r.command.offline_at_issue).toBe(true);
    expect(Date.parse(r.command.expires_at) - Date.parse(r.command.issued_at)).toBe(30_000);
    expect(r.warning).toMatch(/offline/);
    clock += 31_000;
    expect((await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps))).command).toBeNull();
  });
  it("an online display keeps the requested ttl", async () => {
    await heartbeat();
    const r = await j(await play({ ttl_s: 120 }));
    expect(Date.parse(r.command.expires_at) - Date.parse(r.command.issued_at)).toBe(120_000);
    expect(r.warning).toBeNull();
  });
  it("idle is an explicit command", async () => {
    const r = await j(await h.postCommand(rq("POST", "/api/commands", { type: "idle" }, staffH), deps));
    const cfg = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg.command).toMatchObject({ id: r.command.id, type: "idle", reaction: "idle" });
  });
  it("blackout survives restarts until an explicit resume, and shows in the device config", async () => {
    await h.postCommand(rq("POST", "/api/commands", { type: "blackout" }, staffH), deps);
    const repo2 = new FileRepository(join(dir, "state.json"));
    expect((await repo2.getSettings()).blackout).toBe(true);
    expect((await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps))).blackout).toBe(true);
    const r = await j(await h.postCommand(rq("POST", "/api/commands", { type: "resume" }, staffH), deps));
    expect(r.command.type).toBe("resume");
    expect((await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps))).blackout).toBe(false);
  });
  it("blackout is acknowledged only when the device reports the new config revision", async () => {
    await heartbeat();
    const r = await j(await h.postCommand(rq("POST", "/api/commands", { type: "blackout" }, staffH), deps));
    await heartbeat({ config_revision: 1 });
    expect((await j(await h.getStatus(rq("GET", "/api/status"), deps))).last_command.display_state).toBe("pending");
    await heartbeat({ config_revision: r.command.applies_revision, blackout: true, state: "blackout" });
    const st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.last_command.display_state).toBe("applied");
    expect(st.device.blackout_reported).toBe(true);
  });
  it("events map to reactions, and unmapped events are refused", async () => {
    const r = await j(await h.postCommand(rq("POST", "/api/commands", { type: "event", event: "birthday" }, staffH), deps));
    expect(r.command).toMatchObject({ type: "play", reaction: "birthday", source: "event", event: "birthday" });
    await h.patchSettings(rq("PATCH", "/api/settings", { patch: { events: { "person.arrived": null } } }, staffH), deps);
    const u = await h.postCommand(rq("POST", "/api/commands", { type: "event", event: "person.arrived" }, staffH), deps);
    expect(u.status).toBe(422);
    expect((await j(u)).error).toBe("event_unmapped");
  });
  it("per-reaction defaults apply when speed and cycles are omitted", async () => {
    await h.patchSettings(rq("PATCH", "/api/settings", { patch: { reactions: { dance: { speed: 0.75, cycles: 3 } } } }, staffH), deps);
    const r = await j(await play({ reaction: "dance" }));
    expect(r.command).toMatchObject({ speed: 0.75, cycles: 3 });
  });
  it("rejects invalid commands and never accepts code, paths or firmware", async () => {
    for (const body of [{ type: "firmware", url: "http://x/y.bin" }, { type: "play", reaction: "../../main" }, { type: "play", reaction: "wave", speed: 5 }, { type: "run", code: "import os" }]) {
      expect((await h.postCommand(rq("POST", "/api/commands", body, staffH), deps)).status).toBe(422);
    }
  });
});

describe("status never fakes an online display", () => {
  it("is never-seen, then online after a real heartbeat, then offline when heartbeats stop", async () => {
    let st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.device).toEqual({ seen: false, online: false });
    await heartbeat({ simulated: true });
    st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.device.online).toBe(true);
    expect(st.device.simulated).toBe(true);
    expect(st.device.effective_cap_permille).toBe(200);
    expect(st.device.config_in_sync).toBe(true);
    clock += 46_000;
    st = await j(await h.getStatus(rq("GET", "/api/status"), deps));
    expect(st.device.online).toBe(false);
    expect(st.device.seen).toBe(true);
  });
  it("shows config out of sync until the device reports the new revision", async () => {
    await heartbeat();
    await h.patchSettings(rq("PATCH", "/api/settings", { patch: { brightness_percent: 50 } }, staffH), deps);
    expect((await j(await h.getStatus(rq("GET", "/api/status"), deps))).device.config_in_sync).toBe(false);
    await heartbeat({ config_revision: 2 });
    expect((await j(await h.getStatus(rq("GET", "/api/status"), deps))).device.config_in_sync).toBe(true);
  });
  it("device config carries effective colours, brightness as percent of cap, and the asset version", async () => {
    await h.patchSettings(rq("PATCH", "/api/settings", { patch: { colors: { sheep_a: "#FFB34F", effects: "#75CAFF" }, effects_linked: true, brightness_percent: 55 } }, staffH), deps);
    const cfg = await j(await h.deviceConfig(rq("GET", "/api/device/config", undefined, devH), deps));
    expect(cfg.colors).toEqual({ sheep_a: "#FFB34F", sheep_b: "#F0F5F1", effects: "#FFB34F" });
    expect(cfg.brightness_percent).toBe(55);
    expect(cfg.asset_version).toBe("abc123def456");
    expect(cfg.schema_version).toBe(1);
    expect(JSON.stringify(cfg)).not.toContain(TOKEN);
  });
  it("never leaks secrets in any staff response", async () => {
    await heartbeat();
    const all = [await h.getStatus(rq("GET", "/api/status"), deps), await h.getSettings(rq("GET", "/api/settings"), deps), await h.session(rq("GET", "/api/auth/session"), deps)];
    for (const r of all) expect(await r.text()).not.toContain(TOKEN);
  });
});
