// Versioned settings and command schema, with strict server-side validation.
// Shared by the API, the repository and the UI. Pure TypeScript: no Node or browser APIs.
// Limits come from shared/limits.json (copied by `npm run sync-assets`); the firmware keeps
// its own copy of the hard limits and tests assert they agree.
import limits from "../generated/limits.json";

export const SCHEMA_VERSION = 1;
export const REACTION_IDS: readonly string[] = limits.reaction_ids;
export const EVENT_NAMES: readonly string[] = limits.event_names;
export const SPEED_MIN: number = limits.speed.min;
export const SPEED_MAX: number = limits.speed.max;
export const CYCLES_MIN: number = limits.cycles.min;
export const CYCLES_MAX: number = limits.cycles.max;
export const HOLD_MAX_SECONDS: number = limits.hold_max_seconds;
export const TTL = limits.command_ttl_seconds;
export const TIMING = limits.device_timing_seconds;
export const NAME_MAX = 24;
export const LABEL_MAX = 32;
export const PRESETS_MAX = 20;
export const ROTATION_MAX = 18;
export const ROTATION_INTERVAL = { min: 30, max: 3600 };

export type Hex = string; // "#RRGGBB", stored upper-case

export interface Colors {
  sheep_a: Hex;
  sheep_b: Hex;
  effects: Hex;
}
export interface ReactionSetting {
  enabled: boolean;
  label: string | null; // null = use the label from the asset file
  speed: number; // 0.5 .. 1
  cycles: number; // 1 .. 20
}
export interface Ambient {
  mode: "idle" | "rotation";
  rotation: string[]; // reaction ids, enabled ones only
  interval_s: number;
}
export interface Preset {
  id: string;
  name: string;
  colors: Colors;
}
export interface Settings {
  schema_version: number;
  revision: number;
  updated_at: string;
  names: { sheep_a: string; sheep_b: string };
  colors: Colors;
  effects_linked: boolean; // true: effects use Sheep A's colour
  brightness_percent: number; // 0..100 of the firmware-approved cap, NOT raw hardware output
  ambient: Ambient;
  reactions: Record<string, ReactionSetting>;
  events: Record<string, string | null>; // event name -> reaction id
  presets: Preset[];
  blackout: boolean; // changed only through commands; survives reboot until explicit resume
}

/** Fields a staff PATCH may change. `blackout`, `revision` etc. are deliberately not here. */
export interface SettingsPatch {
  names?: Partial<Settings["names"]>;
  colors?: Partial<Colors>;
  effects_linked?: boolean;
  brightness_percent?: number;
  ambient?: Partial<Ambient>;
  reactions?: Record<string, Partial<ReactionSetting>>;
  events?: Record<string, string | null>;
  presets?: Preset[];
}

export type Result<T> = { ok: true; value: T } | { ok: false; errors: string[] };

const DEFAULT_EVENTS: Record<string, string | null> = {
  "person.arrived": "arrive",
  "weather.changed": "weather_cloud",
  birthday: "birthday",
  "gesture.wave": "wave",
  "schedule.sunset": "sunset",
};

export function defaultSettings(now = new Date(0).toISOString()): Settings {
  const reactions: Record<string, ReactionSetting> = {};
  for (const id of REACTION_IDS) reactions[id] = { enabled: true, label: null, speed: 1, cycles: 1 };
  const events: Record<string, string | null> = {};
  for (const e of EVENT_NAMES) events[e] = DEFAULT_EVENTS[e] ?? null;
  return {
    schema_version: SCHEMA_VERSION,
    revision: 1,
    updated_at: now,
    names: { sheep_a: "Sheep A", sheep_b: "Sheep B" },
    colors: { ...limits.default_colors },
    effects_linked: false,
    brightness_percent: 100,
    ambient: { mode: "idle", rotation: [], interval_s: 120 },
    reactions,
    events,
    presets: [],
    blackout: false,
  };
}

// ---- validation helpers ------------------------------------------------------------------

const HEX = /^#[0-9a-fA-F]{6}$/;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function unknownKeys(o: Record<string, unknown>, allowed: readonly string[], path: string, errors: string[]) {
  for (const k of Object.keys(o)) if (!allowed.includes(k)) errors.push(`${path}${k}: unknown field`);
}
function hex(v: unknown, path: string, errors: string[]): Hex | undefined {
  if (typeof v !== "string" || !HEX.test(v)) {
    errors.push(`${path}: must be #RRGGBB`);
    return undefined;
  }
  return v.toUpperCase();
}
function text(v: unknown, path: string, max: number, errors: string[]): string | undefined {
  if (typeof v !== "string") {
    errors.push(`${path}: must be a string`);
    return undefined;
  }
  const t = v.trim();
  // printable text only: no control characters, no markup brackets (labels are rendered by the UI)
  if (t.length < 1 || t.length > max || /[\u0000-\u001f\u007f<>]/.test(t)) {
    errors.push(`${path}: 1 to ${max} printable characters, no < or >`);
    return undefined;
  }
  return t;
}
function num(v: unknown, path: string, lo: number, hi: number, errors: string[], integer = false): number | undefined {
  if (typeof v !== "number" || !Number.isFinite(v) || v < lo || v > hi || (integer && !Number.isInteger(v))) {
    errors.push(`${path}: must be ${integer ? "an integer" : "a number"} from ${lo} to ${hi}`);
    return undefined;
  }
  return v;
}
function reactionId(v: unknown, path: string, errors: string[]): string | undefined {
  if (typeof v !== "string" || !REACTION_IDS.includes(v)) {
    errors.push(`${path}: unknown reaction id`);
    return undefined;
  }
  return v;
}

export function validateSettingsPatch(input: unknown): Result<SettingsPatch> {
  const errors: string[] = [];
  const out: SettingsPatch = {};
  if (!isObj(input)) return { ok: false, errors: ["patch must be an object"] };
  unknownKeys(input, ["names", "colors", "effects_linked", "brightness_percent", "ambient", "reactions", "events", "presets"], "", errors);

  if ("names" in input) {
    const n = input.names;
    if (!isObj(n)) errors.push("names: must be an object");
    else {
      unknownKeys(n, ["sheep_a", "sheep_b"], "names.", errors);
      out.names = {};
      for (const k of ["sheep_a", "sheep_b"] as const) if (k in n) {
        const t = text(n[k], `names.${k}`, NAME_MAX, errors);
        if (t !== undefined) out.names[k] = t;
      }
    }
  }
  if ("colors" in input) {
    const c = input.colors;
    if (!isObj(c)) errors.push("colors: must be an object");
    else {
      unknownKeys(c, ["sheep_a", "sheep_b", "effects"], "colors.", errors);
      out.colors = {};
      for (const k of ["sheep_a", "sheep_b", "effects"] as const) if (k in c) {
        const h = hex(c[k], `colors.${k}`, errors);
        if (h !== undefined) out.colors[k] = h;
      }
    }
  }
  if ("effects_linked" in input) {
    if (typeof input.effects_linked !== "boolean") errors.push("effects_linked: must be a boolean");
    else out.effects_linked = input.effects_linked;
  }
  if ("brightness_percent" in input) {
    const b = num(input.brightness_percent, "brightness_percent", 0, 100, errors, true);
    if (b !== undefined) out.brightness_percent = b;
  }
  if ("ambient" in input) {
    const a = input.ambient;
    if (!isObj(a)) errors.push("ambient: must be an object");
    else {
      unknownKeys(a, ["mode", "rotation", "interval_s"], "ambient.", errors);
      out.ambient = {};
      if ("mode" in a) {
        if (a.mode !== "idle" && a.mode !== "rotation") errors.push("ambient.mode: must be idle or rotation");
        else out.ambient.mode = a.mode;
      }
      if ("rotation" in a) {
        if (!Array.isArray(a.rotation) || a.rotation.length > ROTATION_MAX) errors.push(`ambient.rotation: array of at most ${ROTATION_MAX} reaction ids`);
        else {
          const ids = a.rotation.map((r, i) => reactionId(r, `ambient.rotation[${i}]`, errors));
          if (ids.every((i) => i !== undefined)) out.ambient.rotation = ids as string[];
        }
      }
      if ("interval_s" in a) {
        const n = num(a.interval_s, "ambient.interval_s", ROTATION_INTERVAL.min, ROTATION_INTERVAL.max, errors, true);
        if (n !== undefined) out.ambient.interval_s = n;
      }
    }
  }
  if ("reactions" in input) {
    const r = input.reactions;
    if (!isObj(r)) errors.push("reactions: must be an object");
    else {
      out.reactions = {};
      for (const [id, s] of Object.entries(r)) {
        if (!REACTION_IDS.includes(id)) {
          errors.push(`reactions.${id}: unknown reaction id`);
          continue;
        }
        if (!isObj(s)) {
          errors.push(`reactions.${id}: must be an object`);
          continue;
        }
        unknownKeys(s, ["enabled", "label", "speed", "cycles"], `reactions.${id}.`, errors);
        const o: Partial<ReactionSetting> = {};
        if ("enabled" in s) {
          if (typeof s.enabled !== "boolean") errors.push(`reactions.${id}.enabled: must be a boolean`);
          else o.enabled = s.enabled;
        }
        if ("label" in s) {
          if (s.label === null) o.label = null;
          else {
            const t = text(s.label, `reactions.${id}.label`, LABEL_MAX, errors);
            if (t !== undefined) o.label = t;
          }
        }
        if ("speed" in s) {
          const n = num(s.speed, `reactions.${id}.speed`, SPEED_MIN, SPEED_MAX, errors);
          if (n !== undefined) o.speed = n;
        }
        if ("cycles" in s) {
          const n = num(s.cycles, `reactions.${id}.cycles`, CYCLES_MIN, CYCLES_MAX, errors, true);
          if (n !== undefined) o.cycles = n;
        }
        out.reactions[id] = o;
      }
    }
  }
  if ("events" in input) {
    const e = input.events;
    if (!isObj(e)) errors.push("events: must be an object");
    else {
      out.events = {};
      for (const [name, v] of Object.entries(e)) {
        if (!EVENT_NAMES.includes(name)) {
          errors.push(`events.${name}: unknown event`);
          continue;
        }
        if (v === null) out.events[name] = null;
        else {
          const id = reactionId(v, `events.${name}`, errors);
          if (id !== undefined) out.events[name] = id;
        }
      }
    }
  }
  if ("presets" in input) {
    const p = input.presets;
    if (!Array.isArray(p) || p.length > PRESETS_MAX) errors.push(`presets: array of at most ${PRESETS_MAX}`);
    else {
      const list: Preset[] = [];
      const seen = new Set<string>();
      p.forEach((item, i) => {
        if (!isObj(item)) return void errors.push(`presets[${i}]: must be an object`);
        unknownKeys(item, ["id", "name", "colors"], `presets[${i}].`, errors);
        const id = typeof item.id === "string" && /^[a-z0-9-]{1,36}$/.test(item.id) ? item.id : undefined;
        if (!id) errors.push(`presets[${i}].id: 1 to 36 chars of a-z, 0-9, -`);
        else if (seen.has(id)) errors.push(`presets[${i}].id: duplicate`);
        else seen.add(id);
        const name = text(item.name, `presets[${i}].name`, NAME_MAX, errors);
        const c = item.colors;
        if (!isObj(c)) return void errors.push(`presets[${i}].colors: must be an object`);
        unknownKeys(c, ["sheep_a", "sheep_b", "effects"], `presets[${i}].colors.`, errors);
        const cs = ["sheep_a", "sheep_b", "effects"].map((k) => hex(c[k], `presets[${i}].colors.${k}`, errors));
        if (id && name && cs.every((x) => x !== undefined)) list.push({ id, name, colors: { sheep_a: cs[0]!, sheep_b: cs[1]!, effects: cs[2]! } });
      });
      out.presets = list;
    }
  }
  return errors.length ? { ok: false, errors } : { ok: true, value: out };
}

/** Apply a validated patch. Cross-field rules are enforced here, so the result is always valid. */
export function applyPatch(base: Settings, patch: SettingsPatch): Result<Settings> {
  const next: Settings = JSON.parse(JSON.stringify(base));
  if (patch.names) Object.assign(next.names, patch.names);
  if (patch.colors) Object.assign(next.colors, patch.colors);
  if (patch.effects_linked !== undefined) next.effects_linked = patch.effects_linked;
  if (patch.brightness_percent !== undefined) next.brightness_percent = patch.brightness_percent;
  if (patch.ambient) Object.assign(next.ambient, patch.ambient);
  if (patch.reactions) for (const [id, s] of Object.entries(patch.reactions)) Object.assign(next.reactions[id], s);
  if (patch.events) Object.assign(next.events, patch.events);
  if (patch.presets) next.presets = patch.presets;

  const errors: string[] = [];
  for (const [ev, id] of Object.entries(next.events)) {
    if (id && !next.reactions[id].enabled) errors.push(`events.${ev}: ${id} is disabled`);
  }
  for (const id of next.ambient.rotation) if (!next.reactions[id].enabled) errors.push(`ambient.rotation: ${id} is disabled`);
  if (next.ambient.mode === "rotation" && next.ambient.rotation.length === 0) errors.push("ambient.rotation: choose at least one reaction for rotation mode");
  if (!next.reactions.idle.enabled) errors.push("reactions.idle: idle cannot be disabled (it is the fallback)");
  return errors.length ? { ok: false, errors } : { ok: true, value: next };
}

// ---- commands ----------------------------------------------------------------------------

export type CommandRequest =
  | { type: "play"; reaction: string; speed?: number; cycles?: number; hold?: boolean; ttl_s?: number; request_id?: string }
  | { type: "event"; event: string; ttl_s?: number; request_id?: string }
  | { type: "idle"; ttl_s?: number; request_id?: string }
  | { type: "blackout"; request_id?: string }
  | { type: "resume"; request_id?: string };

export function validateCommandRequest(input: unknown): Result<CommandRequest> {
  const errors: string[] = [];
  if (!isObj(input)) return { ok: false, errors: ["body must be an object"] };
  const type = input.type;
  const common = (allowed: string[]) => unknownKeys(input, ["type", "request_id", ...allowed], "", errors);
  let request_id: string | undefined;
  if ("request_id" in input) {
    if (typeof input.request_id !== "string" || !/^[A-Za-z0-9_-]{8,64}$/.test(input.request_id)) errors.push("request_id: 8 to 64 chars of A-Z a-z 0-9 _ -");
    else request_id = input.request_id;
  }
  let ttl_s: number | undefined;
  const ttl = () => {
    if ("ttl_s" in input) ttl_s = num(input.ttl_s, "ttl_s", TTL.min, TTL.max, errors, true);
  };
  let out: CommandRequest | undefined;
  if (type === "play") {
    common(["reaction", "speed", "cycles", "hold", "ttl_s"]);
    ttl();
    const reaction = reactionId(input.reaction, "reaction", errors);
    const o: { speed?: number; cycles?: number; hold?: boolean } = {};
    if ("speed" in input) o.speed = num(input.speed, "speed", SPEED_MIN, SPEED_MAX, errors);
    if ("cycles" in input) o.cycles = num(input.cycles, "cycles", CYCLES_MIN, CYCLES_MAX, errors, true);
    if ("hold" in input) {
      if (typeof input.hold !== "boolean") errors.push("hold: must be a boolean");
      else o.hold = input.hold;
    }
    if (reaction) out = { type, reaction, ...o, ttl_s, request_id };
  } else if (type === "event") {
    common(["event", "ttl_s"]);
    ttl();
    if (typeof input.event !== "string" || !EVENT_NAMES.includes(input.event)) errors.push("event: unknown event");
    else out = { type, event: input.event, ttl_s, request_id };
  } else if (type === "idle") {
    common(["ttl_s"]);
    ttl();
    out = { type, ttl_s, request_id };
  } else if (type === "blackout" || type === "resume") {
    common([]);
    out = { type, request_id };
  } else {
    errors.push("type: must be play, event, idle, blackout or resume");
  }
  return errors.length || !out ? { ok: false, errors } : { ok: true, value: out };
}

// ---- device payloads ---------------------------------------------------------------------

export interface DeviceCommand {
  id: string;
  type: "play" | "idle";
  reaction: string | null;
  speed: number;
  cycles: number;
  hold: boolean;
  expires_at: string;
}
export interface DeviceConfig {
  schema_version: number;
  revision: number;
  asset_version: string;
  colors: Colors;
  brightness_percent: number;
  ambient: Ambient;
  enabled_reactions: string[];
  command: DeviceCommand | null;
  blackout: boolean;
  poll_interval_s: number;
  heartbeat_interval_s: number;
  server_time: string;
}

export function effectiveColors(s: Settings): Colors {
  return { ...s.colors, effects: s.effects_linked ? s.colors.sheep_a : s.colors.effects };
}

export function buildDeviceConfig(s: Settings, command: DeviceCommand | null, assetVersion: string, nowIso: string): DeviceConfig {
  return {
    schema_version: SCHEMA_VERSION,
    revision: s.revision,
    asset_version: assetVersion,
    colors: effectiveColors(s),
    brightness_percent: s.brightness_percent,
    ambient: s.ambient,
    enabled_reactions: REACTION_IDS.filter((id) => s.reactions[id].enabled),
    command,
    blackout: s.blackout,
    poll_interval_s: TIMING.poll,
    heartbeat_interval_s: TIMING.heartbeat,
    server_time: nowIso,
  };
}

export interface Heartbeat {
  fw_version: string;
  asset_version: string;
  config_revision: number;
  last_command_id: string | null;
  reaction: string | null;
  state: "idle" | "playing" | "blackout" | "fallback" | "booting";
  blackout: boolean;
  brightness_permille: number;
  effective_cap_permille: number;
  uptime_s: number;
  free_ram?: number;
  rssi?: number;
  simulated?: boolean;
}

export function validateHeartbeat(input: unknown): Result<Heartbeat> {
  const errors: string[] = [];
  if (!isObj(input)) return { ok: false, errors: ["body must be an object"] };
  unknownKeys(
    input,
    ["fw_version", "asset_version", "config_revision", "last_command_id", "reaction", "state", "blackout", "brightness_permille", "effective_cap_permille", "uptime_s", "free_ram", "rssi", "simulated"],
    "",
    errors,
  );
  const str = (k: string, max: number) => {
    const v = input[k];
    if (typeof v !== "string" || v.length < 1 || v.length > max || /[\u0000-\u001f<>]/.test(v)) {
      errors.push(`${k}: 1 to ${max} printable characters`);
      return "";
    }
    return v;
  };
  const fw_version = str("fw_version", 32);
  const asset_version = str("asset_version", 32);
  const config_revision = num(input.config_revision, "config_revision", 0, 1e9, errors, true) ?? 0;
  let last_command_id: string | null = null;
  if (input.last_command_id !== null && input.last_command_id !== undefined) {
    if (typeof input.last_command_id !== "string" || !/^[0-9a-f-]{36}$/.test(input.last_command_id)) errors.push("last_command_id: must be a uuid or null");
    else last_command_id = input.last_command_id;
  }
  let reaction: string | null = null;
  if (input.reaction !== null && input.reaction !== undefined) {
    const r = reactionId(input.reaction, "reaction", errors);
    if (r) reaction = r;
  }
  const states = ["idle", "playing", "blackout", "fallback", "booting"];
  if (typeof input.state !== "string" || !states.includes(input.state)) errors.push("state: unknown");
  if (typeof input.blackout !== "boolean") errors.push("blackout: must be a boolean");
  const brightness_permille = num(input.brightness_permille, "brightness_permille", 0, 1000, errors, true) ?? 0;
  const effective_cap_permille = num(input.effective_cap_permille, "effective_cap_permille", 0, 1000, errors, true) ?? 0;
  const uptime_s = num(input.uptime_s, "uptime_s", 0, 1e9, errors, true) ?? 0;
  const out: Heartbeat = {
    fw_version,
    asset_version,
    config_revision,
    last_command_id,
    reaction,
    state: input.state as Heartbeat["state"],
    blackout: input.blackout as boolean,
    brightness_permille,
    effective_cap_permille,
    uptime_s,
  };
  if ("free_ram" in input) out.free_ram = num(input.free_ram, "free_ram", 0, 1e9, errors, true);
  if ("rssi" in input) out.rssi = num(input.rssi, "rssi", -150, 0, errors, true);
  if ("simulated" in input) {
    if (typeof input.simulated !== "boolean") errors.push("simulated: must be a boolean");
    else out.simulated = input.simulated;
  }
  return errors.length ? { ok: false, errors } : { ok: true, value: out };
}
