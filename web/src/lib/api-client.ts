// Browser-side API client. Every state-changing call sends X-Requested-With (CSRF guard) and a
// fresh request_id for commands, so replaying a reaction is always a NEW command.
import type { Settings, SettingsPatch } from "./schema";

export interface DeviceStatus {
  seen: boolean;
  online: boolean;
  last_heartbeat_at?: string;
  age_s?: number;
  simulated?: boolean;
  fw_version?: string;
  asset_version?: string;
  config_revision_applied?: number;
  config_in_sync?: boolean;
  reaction?: string | null;
  state?: string;
  blackout_reported?: boolean;
  brightness_permille?: number;
  effective_cap_permille?: number;
  last_command_id?: string | null;
}
export interface CommandView {
  id: string;
  type: string;
  reaction: string | null;
  status: string;
  display_state: "pending" | "applied" | "expired" | "superseded";
  issued_at: string;
  expires_at?: string;
  speed?: number;
  cycles?: number;
  hold?: boolean;
  offline_at_issue?: boolean;
  applies_revision?: number | null;
}
export interface Status {
  mode: "mock" | "prod";
  server_time: string;
  settings_revision: number;
  blackout: boolean;
  timing: { poll: number; heartbeat: number; offline_after: number };
  device: DeviceStatus;
  last_command: CommandView | null;
  commands: CommandView[];
}
export interface HistoryItem {
  revision: number;
  at: string;
  actor: string;
  kind: "settings" | "blackout" | "undo";
  summary: string;
  undone: boolean;
}
export class ApiError extends Error {
  constructor(public status: number, public code: string, public errors: string[], public body: any) {
    super(errors.length ? errors.join("; ") : code);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: { "x-requested-with": "control-room" }, cache: "no-store" };
  if (body !== undefined) {
    (init.headers as Record<string, string>)["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error ?? "error", data.errors ?? [], data);
  return data as T;
}

export const uuid = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`);

export const api = {
  session: () => call<{ authenticated: boolean; mode: "mock" | "prod" }>("GET", "/api/auth/session"),
  login: (password: string) => call<{ authenticated: boolean }>("POST", "/api/auth/login", { password }),
  logout: () => call<{ authenticated: boolean }>("POST", "/api/auth/logout", {}),
  settings: () => call<{ settings: Settings }>("GET", "/api/settings"),
  patch: (patch: SettingsPatch, expected_revision: number) => call<{ settings: Settings }>("PATCH", "/api/settings", { patch, expected_revision }),
  undo: (expected_revision: number) => call<{ settings: Settings }>("POST", "/api/settings/undo", { expected_revision }),
  history: () => call<{ history: HistoryItem[] }>("GET", "/api/settings/history"),
  status: () => call<Status>("GET", "/api/status"),
  command: (body: Record<string, unknown>) =>
    call<{ command: CommandView; replayed: boolean; display_state: CommandView["display_state"]; warning: string | null }>("POST", "/api/commands", { ...body, request_id: uuid() }),
};
