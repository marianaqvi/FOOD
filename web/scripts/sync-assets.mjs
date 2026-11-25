// Copies the canonical sprite JSON and shared limits into the web app so the
// browser reads the SAME file the firmware packer reads. Never edits the source.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const jobs = [
  [resolve(repo, "assets/food_sheep_animation_assets.json"), resolve(here, "../public/assets/food_sheep_animation_assets.json")],
  [resolve(repo, "shared/limits.json"), resolve(here, "../src/generated/limits.json")],
];
for (const [from, to] of jobs) {
  if (!existsSync(from)) {
    console.error("sync-assets: missing source " + from);
    process.exit(1);
  }
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
}
console.log("sync-assets: ok");
