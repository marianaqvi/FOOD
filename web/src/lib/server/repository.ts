// Repository interface. The development implementation is file-backed (file-repository.ts).
// The production target is Vercel + Supabase Postgres behind THE SAME interface (milestone 5);
// nothing in the handlers or UI knows which one is in use. Never write JSON to Vercel's disk.
import type { DeviceCommand, Heartbeat, Settings, SettingsPatch } from "../schema";

export type CommandStatus = "queued" | "delivered" | "applied" | "expired" | "superseded";

export interface Command {
  id: string; // uuid, new for every request, including a replay of the same reaction
  type: "play" | "idle" | "blackout" | "resume";
  reaction: string | null;
  speed: number;
  cycles: number;
  hold: boolean;
  issued_at: string;
  expires_at: string;
  issued_by: string;
  source: "manual" | "event";
  event: string | null;
  request_id: string | null; // client idempotency key: same key returns the same command
  status: CommandStatus;
  delivered_at: string | null;
  applied_at: string | null;
  offline_at_issue: boolean;
  applies_revision: number | null; // blackout/resume: settings revision the device must report
}

export interface HistoryEntry {
  revision: number;
  at: string;
  actor: string;
  kind: "settings" | "blackout" | "undo";
  summary: string;
  undone: boolean;
}

export interface DeviceRecord extends Heartbeat {
  received_at: number; // server clock, ms
}

export type Fail = { ok: false; code: "conflict" | "invalid" | "nothing_to_undo"; errors: string[]; current?: Settings };
export type Ok<T> = { ok: true; value: T };

export interface NewCommand {
  type: Command["type"];
  reaction: string | null;
  speed: number;
  cycles: number;
  hold: boolean;
  ttl_s: number;
  actor: string;
  source: "manual" | "event";
  event: string | null;
  request_id: string | null;
  offline: boolean;
  applies_revision: number | null;
}

export interface Repository {
  getSettings(): Promise<Settings>;
  patchSettings(patch: SettingsPatch, ctx: { actor: string; now: number; expectedRevision?: number }): Promise<Ok<Settings> | Fail>;
  undo(ctx: { actor: string; now: number; expectedRevision?: number }): Promise<Ok<Settings> | Fail>;
  setBlackout(on: boolean, ctx: { actor: string; now: number }): Promise<Settings>;
  listHistory(limit: number): Promise<HistoryEntry[]>;
  createCommand(input: NewCommand, now: number): Promise<{ command: Command; replayed: boolean }>;
  /** Newest non-expired, unacknowledged play/idle command, marked delivered. Null if none. */
  servableCommand(now: number): Promise<DeviceCommand | null>;
  recordHeartbeat(hb: Heartbeat, now: number): Promise<void>;
  getDevice(): Promise<DeviceRecord | null>;
  getCommands(limit: number, now: number): Promise<Command[]>;
}
