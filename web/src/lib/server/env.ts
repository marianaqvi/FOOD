// Environment and mode. Fails CLOSED: outside explicit mock mode the server refuses to serve
// unless real secrets are configured. No secret has a default and none is ever returned to the browser.
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export interface Env {
  mode: "mock" | "prod";
  staffPassword: string | null;
  sessionSecret: string | null;
  deviceToken: string | null;
  deviceId: string;
  dataDir: string;
  allowedOrigins: string[];
  problems: string[]; // why the server is not usable (prod mode only)
}

export function loadEnv(e: Record<string, string | undefined> = process.env): Env {
  const mock = e.MOCK_MODE === "1";
  const dataDir = e.DATA_DIR || join(process.cwd(), ".data");
  const problems: string[] = [];
  let deviceToken = e.DEVICE_TOKEN || null;
  if (mock && !deviceToken) {
    // Dev convenience: a random token kept in the git-ignored data dir, never in the repo.
    const f = join(dataDir, "dev-device-token");
    mkdirSync(dataDir, { recursive: true });
    if (!existsSync(f)) writeFileSync(f, randomBytes(24).toString("hex"), { mode: 0o600 });
    deviceToken = readFileSync(f, "utf8").trim();
  }
  if (!mock) {
    if (!e.STAFF_PASSWORD || e.STAFF_PASSWORD.length < 12) problems.push("STAFF_PASSWORD (12+ chars) is not set");
    if (!e.SESSION_SECRET || e.SESSION_SECRET.length < 32) problems.push("SESSION_SECRET (32+ chars) is not set");
    if (!deviceToken || deviceToken.length < 32) problems.push("DEVICE_TOKEN (32+ chars) is not set");
  }
  return {
    mode: mock ? "mock" : "prod",
    staffPassword: e.STAFF_PASSWORD || null,
    sessionSecret: e.SESSION_SECRET || null,
    deviceToken,
    deviceId: e.DEVICE_ID || "reception-1",
    dataDir,
    allowedOrigins: (e.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean),
    problems,
  };
}
