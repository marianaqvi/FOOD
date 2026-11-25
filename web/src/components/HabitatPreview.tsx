"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  HARD_MAX_PERMILLE,
  LIMITS,
  compose,
  hardwareSize,
  parseLibrary,
  uniqueLitCount,
  type Colours,
  type Library,
} from "@/lib/sprites";

const SWATCHES: string[] = LIMITS.preset_swatches;
const DEFAULTS = LIMITS.default_colors;
const SPEEDS = [0.5, 0.75, 1];
const LED_SCALE = 10; // canvas pixels per LED in grid mode

type View = "habitat" | "both";
type Style = "led" | "raw";
type Intensity = "readable" | "hardware";

export default function HabitatPreview() {
  const [lib, setLib] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reactionId, setReactionId] = useState("idle");
  const [playing, setPlaying] = useState(true);
  const [frameIdx, setFrameIdx] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [view, setView] = useState<View>("habitat");
  const [style, setStyle] = useState<Style>("led");
  const [intensity, setIntensity] = useState<Intensity>("readable");
  const [brightnessPct, setBrightnessPct] = useState(100);
  const [colours, setColours] = useState({ a: DEFAULTS.sheep_a, b: DEFAULTS.sheep_b, fx: DEFAULTS.effects });

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const clock = useRef({ idx: 0, acc: 0, last: 0 });

  useEffect(() => {
    let cancelled = false;
    fetch("/assets/food_sheep_animation_assets.json")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j) => {
        if (!cancelled) setLib(parseLibrary(j));
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const choose = useCallback((id: string) => {
    clock.current = { idx: 0, acc: 0, last: performance.now() };
    setReactionId(id);
    setFrameIdx(0);
    setPlaying(true);
  }, []);

  // Frame clock: wrap-safe accumulator, local preview only. Speed 0.5x to 1x.
  useEffect(() => {
    if (!lib) return;
    const frames = lib.byId[reactionId].frames;
    let raf = 0;
    clock.current.last = performance.now();
    const tick = (t: number) => {
      const c = clock.current;
      if (playing) {
        let dt = t - c.last;
        if (dt > 1000) dt = 0; // tab was hidden; don't fast-forward
        c.acc += dt * speed;
        while (c.acc >= frames[c.idx].durationMs) {
          c.acc -= frames[c.idx].durationMs;
          c.idx = (c.idx + 1) % frames.length; // idle and previews loop
        }
        setFrameIdx((prev) => (prev === c.idx ? prev : c.idx));
      }
      c.last = t;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [lib, reactionId, playing, speed]);

  const cols: Colours = [colours.a, colours.b, colours.fx];
  const capPermille = HARD_MAX_PERMILLE;
  const hardwarePermille = Math.round((capPermille * brightnessPct) / 100);
  const shownPermille = intensity === "hardware" ? hardwarePermille : brightnessPct * 10;

  // Draw on a real canvas. Raw = native pixels scaled by the browser with nearest neighbour.
  useEffect(() => {
    const cv = canvasRef.current;
    if (!lib || !cv) return;
    const frame = lib.byId[reactionId].frames[frameIdx] ?? lib.byId[reactionId].frames[0];
    const mode = "chained" as const;
    const { w: hw, h: hh } = hardwareSize(mode);
    const showW = view === "both" ? hw : 64;
    const buf = compose(frame.masks, cols, shownPermille, 0, mode, false, intensity === "hardware");
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    if (style === "raw") {
      cv.width = showW;
      cv.height = hh;
      const img = ctx.createImageData(showW, hh);
      for (let y = 0; y < hh; y++)
        for (let x = 0; x < showW; x++) {
          const s = (y * hw + x) * 3;
          const d = (y * showW + x) * 4;
          img.data[d] = buf[s];
          img.data[d + 1] = buf[s + 1];
          img.data[d + 2] = buf[s + 2];
          img.data[d + 3] = 255;
        }
      ctx.putImageData(img, 0, 0);
    } else {
      const S = LED_SCALE;
      cv.width = showW * S;
      cv.height = hh * S;
      ctx.fillStyle = "#090b0b";
      ctx.fillRect(0, 0, cv.width, cv.height);
      for (let y = 0; y < hh; y++)
        for (let x = 0; x < showW; x++) {
          const s = (y * hw + x) * 3;
          const lit = buf[s] | buf[s + 1] | buf[s + 2];
          ctx.fillStyle = lit ? `rgb(${buf[s]},${buf[s + 1]},${buf[s + 2]})` : "#1a1e1e";
          ctx.fillRect(x * S, y * S, S - 1, S - 1);
        }
    }
    if (view === "both") {
      // UI overlay only: panel seam, drawn after the pixels; never part of the frame data.
      const sx = style === "raw" ? 64 : 64 * LED_SCALE;
      ctx.fillStyle = "#5b635f";
      ctx.fillRect(sx - (style === "raw" ? 0 : 1), 0, 1, cv.height);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lib, reactionId, frameIdx, view, style, intensity, shownPermille, colours]);

  if (error) return <p role="alert">Could not load sprite library: {error}</p>;
  if (!lib) return <p>Loading sprite library…</p>;

  const reaction = lib.byId[reactionId];
  const frame = reaction.frames[Math.min(frameIdx, reaction.frames.length - 1)];
  const lit = uniqueLitCount(frame.masks);
  const showW = view === "both" ? 128 : 64;

  return (
    <div className="layout">
      <section aria-labelledby="preview-h">
        <h2 id="preview-h" className="eyebrow">Local preview</h2>
        <div className="banner" role="note">
          Simulated on this device. Not a live feed and not hardware state. No display is connected.
        </div>
        <div className="screen">
          <canvas
            ref={canvasRef}
            className={style === "raw" ? "raw" : ""}
            style={{ aspectRatio: `${showW} / 32` }}
            aria-label={`Preview of ${reaction.label}, frame ${frameIdx + 1} of ${reaction.frames.length}`}
            role="img"
          />
        </div>
        <p className="readout" aria-live="off">
          {lit} / 2048 LEDS lit (unique) · {reaction.label.toUpperCase()} · frame {frameIdx + 1}/{reaction.frames.length} ·{" "}
          {view === "both" ? "128 × 32 (right panel reserved, black)" : "64 × 32 habitat"}
        </p>
        <p className="muted">{reaction.description}</p>

        <div className="row">
          <button onClick={() => setPlaying((p) => !p)} aria-pressed={!playing}>{playing ? "Pause preview" : "Play preview"}</button>
          <button onClick={() => choose(reactionId)}>Replay</button>
          <label>
            Preview speed{" "}
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </label>
        </div>
        <div className="row">
          <label>View{" "}
            <select value={view} onChange={(e) => setView(e.target.value as View)}>
              <option value="habitat">Habitat 64 × 32</option>
              <option value="both">Both panels 128 × 32</option>
            </select>
          </label>
          <label>Style{" "}
            <select value={style} onChange={(e) => setStyle(e.target.value as Style)}>
              <option value="led">LED grid</option>
              <option value="raw">Raw pixels</option>
            </select>
          </label>
          <label>Intensity{" "}
            <select value={intensity} onChange={(e) => setIntensity(e.target.value as Intensity)}>
              <option value="readable">Readable on screen</option>
              <option value="hardware">As scaled for hardware (dim)</option>
            </select>
          </label>
        </div>
        <p className="muted">Pause is local to this preview and does not stop any display.</p>
      </section>

      <section aria-labelledby="chars-h">
        <h2 id="chars-h" className="eyebrow">Character colours</h2>
        {([["a", "Sheep A"], ["b", "Sheep B"], ["fx", "Effects"]] as const).map(([k, name]) => (
          <div className="colour" key={k}>
            <label>
              {name}{" "}
              <input type="color" value={colours[k]} onChange={(e) => setColours((c) => ({ ...c, [k]: e.target.value.toUpperCase() }))} />
            </label>
            <code>{colours[k]}</code>
            <span className="swatches" role="group" aria-label={`${name} presets`}>
              {SWATCHES.map((hex) => (
                <button key={hex} style={{ background: hex }} title={hex} aria-label={`Set ${name} to ${hex}`} onClick={() => setColours((c) => ({ ...c, [k]: hex }))} />
              ))}
            </span>
          </div>
        ))}
        <button onClick={() => setColours({ a: DEFAULTS.sheep_a, b: DEFAULTS.sheep_b, fx: DEFAULTS.effects })}>Reset defaults</button>

        <h2 className="eyebrow">Brightness</h2>
        <label className="block">
          {brightnessPct}% of the firmware-approved cap
          <input type="range" min={0} max={100} value={brightnessPct} onChange={(e) => setBrightnessPct(Number(e.target.value))} aria-label="Brightness as a percentage of the firmware-approved cap" />
        </label>
        <p className="muted">
          Software cap in this repo: RGB scale {(capPermille / 1000).toFixed(2)} (a conservative default, not a measured electrical limit). At {brightnessPct}% the
          hardware scale would be {(hardwarePermille / 1000).toFixed(3)}. Board-reported limit: <strong>unknown, no device connected</strong>. This slider cannot raise the firmware limit.
        </p>
      </section>

      <section aria-labelledby="lib-h" className="wide">
        <h2 id="lib-h" className="eyebrow">Reaction library (preview only)</h2>
        <div className="buttons">
          {lib.reactions.map((r) => (
            <button key={r.id} onClick={() => choose(r.id)} aria-pressed={r.id === reactionId} title={r.description}>
              {r.label}
              <small>{r.id}</small>
            </button>
          ))}
        </div>
        <p className="muted">Sending to a display, ack states and settings storage arrive in later milestones. Nothing here talks to hardware.</p>
      </section>
    </div>
  );
}
