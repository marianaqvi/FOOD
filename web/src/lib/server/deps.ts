import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { loadEnv } from "./env";
import { FileRepository } from "./file-repository";
import type { Deps } from "./handlers";
import { RateLimiter } from "./rate-limit";

let cached: Deps | null = null;
let assetVersionCache: string | null = null;

/** First 12 hex of the SHA-256 of the canonical sprite JSON, the same value the packer writes as asset_version. */
function assetVersion(): string {
  if (assetVersionCache) return assetVersionCache;
  const f = join(process.cwd(), "public", "assets", "food_sheep_animation_assets.json");
  assetVersionCache = existsSync(f) ? createHash("sha256").update(readFileSync(f)).digest("hex").slice(0, 12) : "unknown";
  return assetVersionCache;
}

export function getDeps(): Deps {
  if (cached) return cached;
  const env = loadEnv();
  cached = {
    env,
    repo: new FileRepository(join(env.dataDir, "state.json")),
    limiter: new RateLimiter(),
    now: () => Date.now(),
    assetVersion,
  };
  if (env.mode === "mock") console.log(`[control room] MOCK MODE: no staff login. Device token file: ${join(env.dataDir, "dev-device-token")}`);
  else if (env.problems.length) console.error("[control room] NOT CONFIGURED, refusing requests:", env.problems.join("; "));
  return cached;
}
