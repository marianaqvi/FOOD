// Sprite decoding and the reference compositor for the browser.
// This MUST stay pixel-identical to scripts/reference_renderer.py (the firmware
// spec). tests/parity.test.ts checks every frame against hashes exported by the
// Python renderer. Masks are never modified, resampled or redrawn.
import limits from "../generated/limits.json";

export const HABITAT_W = 64;
export const HABITAT_H = 32;
export const ROW_BYTES = 8;
export const MASK_BYTES = 256;
export const LAYER_NAMES = ["sheep_a", "sheep_b", "effects"] as const;

export type Masks = readonly [Uint8Array, Uint8Array, Uint8Array];
export type Colours = readonly [string, string, string];
export type Mode = "chained" | "single";

export interface Frame {
  durationMs: number;
  masks: Masks;
}
export interface Reaction {
  id: string;
  label: string;
  description: string;
  frames: Frame[];
}
export interface Library {
  reactions: Reaction[];
  byId: Record<string, Reaction>;
}

export const LIMITS = limits;
export const HARD_MAX_PERMILLE: number = limits.rgb_scale.hard_max_permille;
export const MAX_LIT: number = limits.max_lit_habitat_pixels;

export function decodeBase64(text: string): Uint8Array {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const POP = Array.from({ length: 256 }, (_, i) => {
  let n = 0;
  for (let v = i; v; v >>= 1) n += v & 1;
  return n;
});

export function uniqueLitCount(masks: Masks): number {
  let n = 0;
  for (let i = 0; i < MASK_BYTES; i++) n += POP[masks[0][i] | masks[1][i] | masks[2][i]];
  return n;
}

/** Decode and validate the canonical JSON. Throws on any invariant violation. */
export function parseLibrary(json: unknown): Library {
  const d = json as Record<string, any>;
  if (d?.width !== HABITAT_W || d?.height !== HABITAT_H) throw new Error("unexpected sprite dimensions");
  if (JSON.stringify(d.layers) !== JSON.stringify(LAYER_NAMES)) throw new Error("unexpected layers");
  const ids: string[] = limits.reaction_ids;
  if (JSON.stringify(Object.keys(d.animations)) !== JSON.stringify(ids)) throw new Error("reaction IDs differ from limits");
  const reactions: Reaction[] = [];
  for (const id of ids) {
    const frames: Frame[] = (d.animations[id] as unknown[][]).map((rec, n) => {
      const where = `${id}[${n}]`;
      if (!Array.isArray(rec) || rec.length !== 4) throw new Error(`${where}: bad frame`);
      const durationMs = rec[0] as number;
      if (!Number.isInteger(durationMs) || durationMs < 1) throw new Error(`${where}: bad duration`);
      const masks = [1, 2, 3].map((i) => decodeBase64(rec[i] as string)) as unknown as Masks;
      for (const m of masks) if (m.length !== MASK_BYTES) throw new Error(`${where}: mask is not ${MASK_BYTES} bytes`);
      if (uniqueLitCount(masks) > MAX_LIT) throw new Error(`${where}: exceeds ${MAX_LIT} lit pixels`);
      return { durationMs, masks };
    });
    reactions.push({ id, label: d.labels[id], description: d.descriptions[id], frames });
  }
  return { reactions, byId: Object.fromEntries(reactions.map((r) => [r.id, r])) };
}

export function pixelSet(mask: Uint8Array, x: number, y: number): boolean {
  return (mask[y * ROW_BYTES + (x >> 3)] & (0x80 >> (x & 7))) !== 0;
}

export function parseHex(colour: string): [number, number, number] {
  if (!/^#[0-9a-fA-F]{6}$/.test(colour)) throw new Error(`colour must be #RRGGBB: ${colour}`);
  const v = parseInt(colour.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

export function clampScale(permille: number): number {
  return Math.max(0, Math.min(Math.trunc(permille), HARD_MAX_PERMILLE));
}

/** Integer-only, identical to the firmware: (c * p + 500) / 1000, floored. */
export function scaleColour(rgb: readonly number[], permille: number, clamp = true): [number, number, number] {
  const p = clamp ? clampScale(permille) : Math.max(0, Math.min(Math.trunc(permille), 1000));
  return rgb.map((c) => Math.floor((c * p + 500) / 1000)) as [number, number, number];
}

export function hardwareSize(mode: Mode): { w: number; h: number } {
  return mode === "chained" ? { w: limits.chained_display.width, h: limits.chained_display.height } : { w: HABITAT_W, h: HABITAT_H };
}

/**
 * Compose one frame into an RGB hardware buffer (w*h*3 bytes, row-major).
 * Whole buffer starts black; the habitat is clipped to 64x32 then offset by
 * `origin`; layers draw A, B, effects with later layers overwriting.
 * `clamp=false` is for the on-screen preview only and never models hardware.
 */
export function compose(
  masks: Masks,
  colours: Colours,
  scalePermille: number,
  origin: number,
  mode: Mode = "chained",
  blackout = false,
  clamp = true,
): Uint8Array {
  const { w, h } = hardwareSize(mode);
  if (mode === "single" && origin !== 0) throw new Error("single-panel mode requires origin 0");
  if (mode === "chained" && !(limits.allowed_habitat_origins as number[]).includes(origin)) throw new Error("origin must be 0 or 64");
  const buf = new Uint8Array(w * h * 3);
  if (blackout) return buf;
  const rgbs = colours.map((c) => scaleColour(parseHex(c), scalePermille, clamp));
  for (let l = 0; l < 3; l++) {
    const [r, g, b] = rgbs[l];
    for (let y = 0; y < HABITAT_H; y++) {
      for (let x = 0; x < HABITAT_W; x++) {
        if (masks[l][y * ROW_BYTES + (x >> 3)] & (0x80 >> (x & 7))) {
          const o = (y * w + origin + x) * 3;
          buf[o] = r;
          buf[o + 1] = g;
          buf[o + 2] = b;
        }
      }
    }
  }
  return buf;
}
