import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { compose, parseLibrary, scaleColour, uniqueLitCount, clampScale, HARD_MAX_PERMILLE, type Colours, type Masks } from "@/lib/sprites";

const repo = resolve(__dirname, "..", "..");
const lib = parseLibrary(JSON.parse(readFileSync(resolve(repo, "assets/food_sheep_animation_assets.json"), "utf8")));
const golden = JSON.parse(readFileSync(resolve(repo, "tests/golden/render_hashes.json"), "utf8")) as {
  colours: string[];
  scale_permille: number;
  hashes: Record<string, string[]>;
};

const h = (b: Uint8Array) => createHash("sha256").update(b).digest("hex").slice(0, 16);

describe("canonical library", () => {
  it("has 18 reactions, 624 frames, max 281 lit pixels, 150 ms frames", () => {
    expect(lib.reactions).toHaveLength(18);
    const frames = lib.reactions.flatMap((r) => r.frames);
    expect(frames).toHaveLength(624);
    expect(frames.every((f) => f.durationMs === 150)).toBe(true);
    expect(Math.max(...frames.map((f) => uniqueLitCount(f.masks)))).toBe(281);
  });
});

describe("browser vs Python reference renderer", () => {
  it("matches every frame for origin 0, origin 64 and single-panel mode", () => {
    let checked = 0;
    for (const r of lib.reactions) {
      r.frames.forEach((f, n) => {
        const want = golden.hashes[`${r.id}:${n}`];
        expect(want, `${r.id}:${n} missing from golden`).toBeDefined();
        const c = golden.colours as unknown as Colours;
        const s = golden.scale_permille;
        expect(h(compose(f.masks, c, s, 0)), `${r.id}:${n} origin 0`).toBe(want[0]);
        expect(h(compose(f.masks, c, s, 64)), `${r.id}:${n} origin 64`).toBe(want[1]);
        expect(h(compose(f.masks, c, s, 0, "single")), `${r.id}:${n} single`).toBe(want[2]);
        checked++;
      });
    }
    expect(checked).toBe(624);
    expect(Object.keys(golden.hashes)).toHaveLength(624);
  });
});

describe("safety behaviour", () => {
  it("colour scaling matches the firmware integer maths and is hard clamped", () => {
    expect(scaleColour([0xf0, 0xf5, 0xf1], 100)).toEqual([24, 25, 24]);
    expect(scaleColour([0xff, 0xb3, 0x4f], 100)).toEqual([26, 18, 8]);
    expect(clampScale(5000)).toBe(HARD_MAX_PERMILLE);
    expect(scaleColour([255, 255, 255], 1000)).toEqual(scaleColour([255, 255, 255], HARD_MAX_PERMILLE));
  });

  it("never lights the reserved half, for every frame and both origins", () => {
    const white: Colours = ["#FFFFFF", "#FFFFFF", "#FFFFFF"];
    for (const r of lib.reactions) {
      for (const f of r.frames) {
        for (const [origin, lo, hi] of [[0, 64, 128], [64, 0, 64]] as const) {
          const buf = compose(f.masks, white, HARD_MAX_PERMILLE, origin);
          for (let y = 0; y < 32; y++) for (let x = lo; x < hi; x++) {
            const o = (y * 128 + x) * 3;
            if (buf[o] | buf[o + 1] | buf[o + 2]) throw new Error(`${r.id} leaks at x=${x}`);
          }
        }
      }
    }
  });

  it("blackout is entirely black and bad origins are rejected", () => {
    const m = lib.reactions[0].frames[0].masks as Masks;
    const c: Colours = ["#FFFFFF", "#FFFFFF", "#FFFFFF"];
    expect(compose(m, c, 100, 0, "chained", true).every((v) => v === 0)).toBe(true);
    for (const o of [1, 32, 63, 65, 128, -1]) expect(() => compose(m, c, 100, o)).toThrow();
    expect(() => compose(m, c, 100, 64, "single")).toThrow();
  });
});
