import { createHmac, timingSafeEqual } from "node:crypto";
import type { Env } from "./env";

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) {
    timingSafeEqual(ab, ab); // keep timing roughly flat
    return false;
  }
  return timingSafeEqual(ab, bb);
}

/** Device auth: Authorization: Bearer <token>, per-device token, constant-time compare. */
export function deviceAuthorized(req: Request, env: Env): boolean {
  if (!env.deviceToken) return false;
  const h = req.headers.get("authorization") ?? "";
  const m = /^Bearer (.+)$/.exec(h);
  return !!m && safeEqual(m[1], env.deviceToken);
}

const COOKIE = "fc_session";
const SESSION_MS = 8 * 60 * 60 * 1000;

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

export function makeSessionCookie(env: Env, now: number, secure: boolean): string {
  const payload = Buffer.from(JSON.stringify({ exp: now + SESSION_MS })).toString("base64url");
  const value = `${payload}.${sign(payload, env.sessionSecret!)}`;
  return `${COOKIE}=${value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${SESSION_MS / 1000}${secure ? "; Secure" : ""}`;
}
export function clearSessionCookie(): string {
  return `${COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0`;
}

export function sessionValid(req: Request, env: Env, now: number): boolean {
  if (!env.sessionSecret) return false;
  const cookie = (req.headers.get("cookie") ?? "").split(/;\s*/).find((c) => c.startsWith(COOKIE + "="));
  if (!cookie) return false;
  const [payload, mac] = cookie.slice(COOKIE.length + 1).split(".");
  if (!payload || !mac || !safeEqual(mac, sign(payload, env.sessionSecret))) return false;
  try {
    return JSON.parse(Buffer.from(payload, "base64url").toString()).exp > now;
  } catch {
    return false;
  }
}

/**
 * CSRF / origin protection for state-changing staff requests: a custom header that a cross-site
 * form or simple fetch cannot send, plus an Origin check against Host when the browser sends Origin.
 */
export function sameOriginOk(req: Request, env: Env): boolean {
  if (req.headers.get("x-requested-with") !== "control-room") return false;
  const origin = req.headers.get("origin");
  if (!origin) return true; // non-browser client; still needs the header and the session
  try {
    const o = new URL(origin);
    if (env.allowedOrigins.includes(o.origin)) return true;
    return o.host === req.headers.get("host");
  } catch {
    return false;
  }
}
