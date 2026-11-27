// DEVELOPMENT ONLY: a software stand-in for the display, so the control room's pending/applied/offline
// states can be exercised without hardware. It reports `simulated: true` in every heartbeat and the
// control room labels it "SIMULATED DEVICE". It is NOT the firmware and proves nothing about the board.
//
//   node scripts/sim-device.mjs [--url http://localhost:3000] [--token <token>] [--heartbeat 5] [--cap 200]
//
// The token defaults to .data/dev-device-token (created by the server in mock mode). Ctrl-C to stop;
// after that the control room shows the display as offline once the heartbeat window passes.
import { readFileSync } from "node:fs";
import { join } from "node:path";

const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > 0 ? process.argv[i + 1] : d; };
const url = arg("url", "http://localhost:3000");
const heartbeatS = Number(arg("heartbeat", "5"));
const cap = Number(arg("cap", "200"));
let token = arg("token", process.env.DEVICE_TOKEN);
if (!token) token = readFileSync(join(process.cwd(), ".data", "dev-device-token"), "utf8").trim();

const headers = { authorization: `Bearer ${token}`, "content-type": "application/json" };
const state = { revision: 0, lastCommand: null, reaction: "idle", mode: "idle", blackout: false, percent: 100, until: 0, hold: false, started: Date.now(), assetVersion: "unknown" };
let polling = false;

async function beat() {
  const body = {
    fw_version: "simulator-0", asset_version: state.assetVersion, config_revision: state.revision, last_command_id: state.lastCommand,
    reaction: state.blackout ? null : state.reaction, state: state.blackout ? "blackout" : state.mode, blackout: state.blackout,
    brightness_permille: Math.round((cap * state.percent) / 100), effective_cap_permille: cap, uptime_s: Math.round((Date.now() - state.started) / 1000), simulated: true,
  };
  const r = await fetch(url + "/api/device/heartbeat", { method: "POST", headers, body: JSON.stringify(body) });
  if (!r.ok) console.log("heartbeat refused:", r.status, await r.text());
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    const r = await fetch(url + "/api/device/config", { headers });
    if (!r.ok) return console.log("config refused:", r.status);
    const cfg = await r.json();
    let changed = false;
    state.assetVersion = cfg.asset_version;
    if (cfg.revision !== state.revision) { state.revision = cfg.revision; changed = true; }
    if (cfg.blackout !== state.blackout) { state.blackout = cfg.blackout; changed = true; console.log(cfg.blackout ? "BLACKOUT" : "resumed"); }
    state.percent = cfg.brightness_percent;
    const c = cfg.command;
    if (c && c.id !== state.lastCommand && Date.parse(c.expires_at) > Date.now()) {
      state.lastCommand = c.id;
      changed = true;
      if (c.type === "play") {
        state.reaction = c.reaction; state.mode = "playing"; state.hold = c.hold;
        state.until = Date.now() + (c.hold ? 600000 : (5000 * c.cycles) / c.speed);
        console.log(`play ${c.reaction} x${c.cycles} @${c.speed}${c.hold ? " (hold)" : ""} [${c.id.slice(0, 8)}]`);
      } else { state.reaction = "idle"; state.mode = "idle"; console.log(`idle [${c.id.slice(0, 8)}]`); }
    }
    if (state.mode === "playing" && Date.now() > state.until) { state.reaction = "idle"; state.mode = "idle"; changed = true; console.log("back to idle"); }
    if (changed) await beat(); // acknowledge promptly instead of waiting for the next timer
  } catch (e) { console.log("poll failed:", e.message); } finally { polling = false; }
}

console.log(`simulated device -> ${url}  heartbeat ${heartbeatS}s  cap ${cap}`);
setInterval(poll, 2000);
setInterval(() => beat().catch((e) => console.log("heartbeat failed:", e.message)), heartbeatS * 1000);
poll();
