"use client";
// Local simulated preview on a real <canvas>: native 64 x 32 (or 128 x 32 with the reserved half
// black), scaled by the browser with nearest neighbour. It reads the same canonical JSON the
// firmware packer reads. It is NOT a live feed and never shows device state.
import { useEffect, useRef, useState } from "react";
import { HARD_MAX_PERMILLE, compose, hardwareSize, uniqueLitCount, type Colours, type Library } from "@/lib/sprites";

const SPEEDS = [0.5, 0.75, 1];
const LED_SCALE = 10;
type View = "habitat" | "both";
type Style = "led" | "raw";
type Intensity = "readable" | "hardware";

export default function PreviewPanel(props: { lib: Library; reactionId: string; cols: Colours; brightnessPct: number; replayKey: number }) {
  const { lib, reactionId, cols, brightnessPct, replayKey } = props;
  const [playing, setPlaying] = useState(true);
  const [frameIdx, setFrameIdx] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [view, setView] = useState<View>("habitat");
  const [style, setStyle] = useState<Style>("led");
  const [intensity, setIntensity] = useState<Intensity>("readable");
  const [localReplay, setLocalReplay] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const clock = useRef({ idx: 0, acc: 0, last: 0 });

  // Frame clock: accumulator, local preview only. Previews loop; the device plays once then returns to idle.
  useEffect(() => {
    const frames = lib.byId[reactionId].frames;
    clock.current = { idx: 0, acc: 0, last: performance.now() };
    setFrameIdx(0);
    let raf = 0;
    const tick = (t: number) => {
      const c = clock.current;
      if (playing) {
        let dt = t - c.last;
        if (dt > 1000) dt = 0; // hidden tab: do not fast-forward
        c.acc += dt * speed;
        while (c.acc >= frames[c.idx].durationMs) {
          c.acc -= frames[c.idx].durationMs;
          c.idx = (c.idx + 1) % frames.length;
        }
        setFrameIdx((p) => (p === c.idx ? p : c.idx));
      }
      c.last = t;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [lib, reactionId, playing, speed, replayKey, localReplay]);

  const hardwarePermille = Math.round((HARD_MAX_PERMILLE * brightnessPct) / 100);
  const shownPermille = intensity === "hardware" ? hardwarePermille : Math.max(brightnessPct, 20) * 10;

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const reaction = lib.byId[reactionId];
    const frame = reaction.frames[frameIdx] ?? reaction.frames[0];
    const { w: hw, h: hh } = hardwareSize("chained");
    const showW = view === "both" ? hw : 64;
    const buf = compose(frame.masks, cols, shownPermille, 0, "chained", false, intensity === "hardware");
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
      // UI overlay only: the seam between panels, drawn after the pixels, never part of the frame data.
      const sx = style === "raw" ? 64 : 64 * LED_SCALE;
      ctx.fillStyle = "#5b635f";
      ctx.fillRect(sx - (style === "raw" ? 0 : 1), 0, 1, cv.height);
    }
  }, [lib, reactionId, frameIdx, view, style, intensity, shownPermille, cols]);

  const reaction = lib.byId[reactionId];
  const frame = reaction.frames[Math.min(frameIdx, reaction.frames.length - 1)];
  const showW = view === "both" ? 128 : 64;

  return (
    <section aria-labelledby="preview-h">
      <h2 id="preview-h" className="eyebrow">Local preview</h2>
      <div className="banner" role="note">Simulated in this browser. Not a live feed and not hardware state.</div>
      <div className="screen">
        <canvas
          ref={canvasRef}
          className={style === "raw" ? "raw" : ""}
          style={{ aspectRatio: `${showW} / 32` }}
          role="img"
          aria-label={`Preview of ${reaction.label}, frame ${frameIdx + 1} of ${reaction.frames.length}`}
        />
      </div>
      <p className="readout">
        {uniqueLitCount(frame.masks)} / 2048 LEDS lit (unique) · {reaction.label.toUpperCase()} · frame {frameIdx + 1}/{reaction.frames.length} ·{" "}
        {view === "both" ? "128 × 32 (right panel reserved, black)" : "64 × 32 habitat"}
      </p>
      <p className="muted">{reaction.description}</p>
      <div className="row">
        <button onClick={() => setPlaying((p) => !p)} aria-pressed={!playing}>{playing ? "Pause preview" : "Play preview"}</button>
        <button onClick={() => setLocalReplay((n) => n + 1)}>Replay preview</button>
        <label>Preview speed{" "}
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
      <p className="muted">Pausing here only affects this preview. It does not stop any display.</p>
    </section>
  );
}
