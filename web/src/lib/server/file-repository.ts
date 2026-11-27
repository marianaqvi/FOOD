// Development-only repository: one JSON file, written atomically (temp file + rename) with a
// previous-copy backup, serialised through a promise queue. Not for Vercel (read-only/ephemeral disk).
import { randomUUID } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync, openSync, fsyncSync, closeSync } from "node:fs";
import { dirname } from "node:path";
import {
  applyPatch,
  defaultSettings,
  validateSettingsPatch,
  type DeviceCommand,
  type Heartbeat,
  type Settings,
  type SettingsPatch,
} from "../schema";
import type { Command, DeviceRecord, Fail, HistoryEntry, NewCommand, Ok, Repository } from "./repository";

interface HistoryRecord extends HistoryEntry {
  before: SettingsPatchable | null; // settings snapshot taken before the change (kind 'settings')
}
type SettingsPatchable = Omit<Settings, "schema_version" | "revision" | "updated_at" | "blackout">;

interface State {
  version: 1;
  settings: Settings;
  history: HistoryRecord[];
  commands: Command[];
}

const MAX_HISTORY = 50;
const MAX_COMMANDS = 50;

const iso = (ms: number) => new Date(ms).toISOString();

function editable(s: Settings): SettingsPatchable {
  const { schema_version: _a, revision: _b, updated_at: _c, blackout: _d, ...rest } = JSON.parse(JSON.stringify(s));
  return rest;
}

function summarize(patch: SettingsPatch): string {
  const keys = Object.keys(patch);
  return keys.length ? "changed " + keys.join(", ") : "no change";
}

export class FileRepository implements Repository {
  private state: State;
  private device: DeviceRecord | null = null; // in memory on purpose: "online" must come from a real heartbeat
  private chain: Promise<unknown> = Promise.resolve();
  /** Set when the state file was unreadable at start (a copy was kept next to it). */
  recoveredFrom: string | null = null;

  constructor(private path: string) {
    this.state = this.load();
  }

  // ---- persistence ----
  private load(): State {
    const fresh = (): State => ({ version: 1, settings: defaultSettings(), history: [], commands: [] });
    for (const candidate of [this.path, this.path + ".bak"]) {
      if (!existsSync(candidate)) continue;
      try {
        const raw = JSON.parse(readFileSync(candidate, "utf8"));
        if (raw?.version !== 1 || !raw.settings || !Array.isArray(raw.history) || !Array.isArray(raw.commands)) throw new Error("bad shape");
        // Re-validate settings against the current schema; anything outside it is dropped to defaults.
        const base = defaultSettings();
        const { schema_version: _a, revision, updated_at, blackout, ...editableRaw } = raw.settings;
        const v = validateSettingsPatch(editableRaw);
        const merged = v.ok ? applyPatch(base, v.value) : null;
        if (!merged || !merged.ok) throw new Error("settings failed validation");
        const settings: Settings = { ...merged.value, revision: Number.isInteger(revision) && revision >= 1 ? revision : 1, updated_at: String(updated_at ?? ""), blackout: blackout === true };
        if (candidate !== this.path) this.recoveredFrom = candidate;
        return { version: 1, settings, history: raw.history.slice(-MAX_HISTORY), commands: raw.commands.slice(-MAX_COMMANDS) };
      } catch {
        try {
          copyFileSync(candidate, `${this.path}.corrupt-${Date.now()}`);
        } catch {
          /* best effort */
        }
      }
    }
    return fresh();
  }

  private persist() {
    mkdirSync(dirname(this.path), { recursive: true });
    const tmp = this.path + ".tmp";
    writeFileSync(tmp, JSON.stringify(this.state));
    const fd = openSync(tmp, "r");
    try {
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    if (existsSync(this.path)) copyFileSync(this.path, this.path + ".bak");
    renameSync(tmp, this.path);
  }

  private run<T>(fn: () => T): Promise<T> {
    const next = this.chain.then(fn, fn);
    this.chain = next.catch(() => undefined);
    return next;
  }

  // ---- settings ----
  getSettings() {
    return this.run(() => JSON.parse(JSON.stringify(this.state.settings)) as Settings);
  }

  patchSettings(patch: SettingsPatch, ctx: { actor: string; now: number; expectedRevision?: number }): Promise<Ok<Settings> | Fail> {
    return this.run(() => {
      const cur = this.state.settings;
      if (ctx.expectedRevision !== undefined && ctx.expectedRevision !== cur.revision) {
        return { ok: false, code: "conflict", errors: [`settings changed (now revision ${cur.revision}, you edited ${ctx.expectedRevision})`], current: cur } as Fail;
      }
      const applied = applyPatch(cur, patch);
      if (!applied.ok) return { ok: false, code: "invalid", errors: applied.errors } as Fail;
      const next = applied.value;
      next.revision = cur.revision + 1;
      next.updated_at = iso(ctx.now);
      this.record({ revision: next.revision, at: next.updated_at, actor: ctx.actor, kind: "settings", summary: summarize(patch), undone: false, before: editable(cur) });
      this.state.settings = next;
      this.persist();
      return { ok: true, value: JSON.parse(JSON.stringify(next)) } as Ok<Settings>;
    });
  }

  undo(ctx: { actor: string; now: number; expectedRevision?: number }): Promise<Ok<Settings> | Fail> {
    return this.run(() => {
      const cur = this.state.settings;
      if (ctx.expectedRevision !== undefined && ctx.expectedRevision !== cur.revision) {
        return { ok: false, code: "conflict", errors: ["settings changed since you loaded them"], current: cur } as Fail;
      }
      let idx = -1;
      for (let i = this.state.history.length - 1; i >= 0; i--) {
        const h = this.state.history[i];
        if (h.kind === "settings" && !h.undone && h.before) {
          idx = i;
          break;
        }
      }
      if (idx < 0) return { ok: false, code: "nothing_to_undo", errors: ["nothing to undo"] } as Fail;
      const entry = this.state.history[idx];
      // Restore the saved editable fields; blackout and the revision counter are never rolled back.
      const restored: Settings = { ...(JSON.parse(JSON.stringify(entry.before)) as SettingsPatchable), schema_version: cur.schema_version, revision: cur.revision + 1, updated_at: iso(ctx.now), blackout: cur.blackout };
      const check = applyPatch(defaultSettings(), validateSettingsPatchOrEmpty(entry.before));
      if (!check.ok) return { ok: false, code: "invalid", errors: ["stored history entry no longer valid"] } as Fail;
      entry.undone = true;
      this.record({ revision: restored.revision, at: restored.updated_at, actor: ctx.actor, kind: "undo", summary: `undid revision ${entry.revision}: ${entry.summary}`, undone: false, before: null });
      this.state.settings = restored;
      this.persist();
      return { ok: true, value: JSON.parse(JSON.stringify(restored)) } as Ok<Settings>;
    });
  }

  setBlackout(on: boolean, ctx: { actor: string; now: number }) {
    return this.run(() => {
      const cur = this.state.settings;
      if (cur.blackout === on) return JSON.parse(JSON.stringify(cur)) as Settings;
      const next: Settings = { ...cur, blackout: on, revision: cur.revision + 1, updated_at: iso(ctx.now) };
      this.record({ revision: next.revision, at: next.updated_at, actor: ctx.actor, kind: "blackout", summary: on ? "blackout on" : "resumed from blackout", undone: false, before: null });
      this.state.settings = next;
      this.persist();
      return JSON.parse(JSON.stringify(next)) as Settings;
    });
  }

  private record(h: HistoryRecord) {
    this.state.history.push(h);
    if (this.state.history.length > MAX_HISTORY) this.state.history.splice(0, this.state.history.length - MAX_HISTORY);
  }

  listHistory(limit: number) {
    return this.run(() =>
      this.state.history
        .slice(-limit)
        .reverse()
        .map(({ before: _b, ...h }) => h as HistoryEntry),
    );
  }

  // ---- commands ----
  createCommand(input: NewCommand, now: number) {
    return this.run(() => {
      if (input.request_id) {
        const existing = this.state.commands.find((c) => c.request_id === input.request_id);
        if (existing) return { command: { ...existing }, replayed: true };
      }
      if (input.type === "play" || input.type === "idle") {
        for (const c of this.state.commands) if ((c.status === "queued" || c.status === "delivered") && (c.type === "play" || c.type === "idle")) c.status = "superseded";
      }
      const command: Command = {
        id: randomUUID(),
        type: input.type,
        reaction: input.reaction,
        speed: input.speed,
        cycles: input.cycles,
        hold: input.hold,
        issued_at: iso(now),
        expires_at: iso(now + input.ttl_s * 1000),
        issued_by: input.actor,
        source: input.source,
        event: input.event,
        request_id: input.request_id,
        status: "queued",
        delivered_at: null,
        applied_at: null,
        offline_at_issue: input.offline,
        applies_revision: input.applies_revision,
      };
      this.state.commands.push(command);
      if (this.state.commands.length > MAX_COMMANDS) this.state.commands.splice(0, this.state.commands.length - MAX_COMMANDS);
      this.persist();
      return { command: { ...command }, replayed: false };
    });
  }

  private expire(now: number) {
    let changed = false;
    for (const c of this.state.commands) {
      if ((c.status === "queued" || c.status === "delivered") && Date.parse(c.expires_at) <= now) {
        c.status = "expired";
        changed = true;
      }
    }
    return changed;
  }

  servableCommand(now: number) {
    return this.run((): DeviceCommand | null => {
      const changed = this.expire(now);
      let found: Command | null = null;
      for (const c of this.state.commands) if ((c.type === "play" || c.type === "idle") && (c.status === "queued" || c.status === "delivered")) found = c;
      let write = changed;
      if (found && found.status === "queued") {
        found.status = "delivered";
        found.delivered_at = iso(now);
        write = true;
      }
      if (write) this.persist();
      if (!found) return null;
      return { id: found.id, type: found.type as "play" | "idle", reaction: found.reaction, speed: found.speed, cycles: found.cycles, hold: found.hold, expires_at: found.expires_at };
    });
  }

  recordHeartbeat(hb: Heartbeat, now: number) {
    return this.run(() => {
      this.device = { ...hb, received_at: now };
      let changed = this.expire(now);
      for (const c of this.state.commands) {
        if ((c.type === "play" || c.type === "idle") && hb.last_command_id === c.id && (c.status === "queued" || c.status === "delivered")) {
          c.status = "applied";
          c.applied_at = iso(now);
          changed = true;
        }
        if ((c.type === "blackout" || c.type === "resume") && c.status !== "applied" && c.applies_revision !== null && hb.config_revision >= c.applies_revision) {
          c.status = "applied";
          c.applied_at = iso(now);
          changed = true;
        }
      }
      if (changed) this.persist();
    });
  }

  getDevice() {
    return this.run(() => (this.device ? { ...this.device } : null));
  }

  getCommands(limit: number, now: number) {
    return this.run(() => {
      if (this.expire(now)) this.persist();
      return this.state.commands.slice(-limit).map((c) => ({ ...c }));
    });
  }
}

function validateSettingsPatchOrEmpty(before: SettingsPatchable | null): SettingsPatch {
  if (!before) return {};
  const v = validateSettingsPatch(before);
  return v.ok ? v.value : {};
}
