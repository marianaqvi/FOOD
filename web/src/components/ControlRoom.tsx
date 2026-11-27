"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type CommandView, type HistoryItem, type Status } from "@/lib/api-client";
import {
  CYCLES_MAX,
  CYCLES_MIN,
  EVENT_NAMES,
  LABEL_MAX,
  NAME_MAX,
  PRESETS_MAX,
  REACTION_IDS,
  ROTATION_INTERVAL,
  SPEED_MAX,
  SPEED_MIN,
  defaultSettings,
  effectiveColors,
  type Settings,
  type SettingsPatch,
} from "@/lib/schema";
import { HARD_MAX_PERMILLE, LIMITS, parseLibrary, type Colours, type Library } from "@/lib/sprites";
import PreviewPanel from "./PreviewPanel";

const SWATCHES: string[] = LIMITS.preset_swatches;
const SPEEDS = [0.5, 0.75, 1];

type Notice = { kind: "ok" | "warn" | "error" | "info"; text: string } | null;

function editable(s: Settings): SettingsPatch {
  return { names: s.names, colors: s.colors, effects_linked: s.effects_linked, brightness_percent: s.brightness_percent, ambient: s.ambient, reactions: s.reactions, events: s.events, presets: s.presets };
}
const msg = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
const ago = (s?: number) => (s === undefined ? "never" : s < 2 ? "just now" : s < 120 ? `${s} s ago` : `${Math.round(s / 60)} min ago`);
const short = (id?: string | null) => (id ? id.slice(0, 8) : "none");

export default function ControlRoom() {
  const [lib, setLib] = useState<Library | null>(null);
  const [libError, setLibError] = useState<string | null>(null);
  const [auth, setAuth] = useState<"loading" | "in" | "out" | "unconfigured">("loading");
  const [mode, setMode] = useState<"mock" | "prod" | null>(null);
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [selected, setSelected] = useState("idle");
  const [opts, setOpts] = useState({ speed: 1, cycles: 1, hold: false });
  const [replayKey, setReplayKey] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [password, setPassword] = useState("");
  const [presetName, setPresetName] = useState("");
  const lastSent = useRef<Record<string, unknown> | null>(null);

  // ---- boot ----
  useEffect(() => {
    let off = false;
    fetch("/assets/food_sheep_animation_assets.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => !off && setLib(parseLibrary(j)))
      .catch((e) => !off && setLibError(String(e.message ?? e)));
    api.session().then(
      (s) => {
        if (off) return;
        setMode(s.mode);
        setAuth(s.authenticated ? "in" : "out");
      },
      (e) => !off && (e instanceof ApiError && e.status === 503 ? (setAuth("unconfigured"), setNotice({ kind: "error", text: e.errors.join("; ") })) : setAuth("out")),
    );
    return () => {
      off = true;
    };
  }, []);

  const loadSettings = useCallback(async () => {
    const [s, h] = await Promise.all([api.settings(), api.history()]);
    setSaved(s.settings);
    setDraft(s.settings);
    setHistory(h.history);
  }, []);

  useEffect(() => {
    if (auth !== "in") return;
    loadSettings().catch((e) => setNotice({ kind: "error", text: msg(e) }));
  }, [auth, loadSettings]);

  // ---- status polling (real heartbeats only; nothing here is simulated by the browser) ----
  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.status());
      setStatusErr(null);
    } catch (e) {
      setStatusErr(msg(e));
    }
  }, []);
  useEffect(() => {
    if (auth !== "in") return;
    refreshStatus();
    const t = setInterval(refreshStatus, 2000);
    return () => clearInterval(t);
  }, [auth, refreshStatus]);

  // An "waiting for the display" notice is replaced by the tracker once the display really confirms.
  const lastState = status?.last_command?.display_state;
  useEffect(() => {
    if (lastState === "applied") setNotice((n) => (n && n.kind === "info" ? null : n));
  }, [lastState]);

  const dirty = useMemo(() => !!saved && !!draft && JSON.stringify(editable(saved)) !== JSON.stringify(editable(draft)), [saved, draft]);

  const upd = (fn: (d: Settings) => void) =>
    setDraft((d) => {
      if (!d) return d;
      const n: Settings = JSON.parse(JSON.stringify(d));
      fn(n);
      return n;
    });

  const choose = (id: string) => {
    setSelected(id);
    const r = draft?.reactions[id];
    if (r) setOpts({ speed: r.speed, cycles: r.cycles, hold: false });
    setReplayKey((k) => k + 1);
  };

  // ---- actions ----
  async function save() {
    if (!saved || !draft) return;
    setBusy("save");
    setNotice(null);
    try {
      const r = await api.patch(editable(draft), saved.revision);
      setSaved(r.settings);
      setDraft(r.settings);
      setNotice({ kind: "ok", text: `Saved as revision ${r.settings.revision}. The display applies it when it next polls; watch the status above.` });
      api.history().then((h) => setHistory(h.history));
      refreshStatus();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await loadSettings();
        setNotice({ kind: "warn", text: "Settings were changed somewhere else. I reloaded the saved version; your edits were discarded." });
      } else setNotice({ kind: "error", text: `Not saved: ${msg(e)}` });
    } finally {
      setBusy(null);
    }
  }

  async function undo() {
    if (!saved) return;
    setBusy("undo");
    try {
      const r = await api.undo(saved.revision);
      setSaved(r.settings);
      setDraft(r.settings);
      setNotice({ kind: "ok", text: `Undid the last change (now revision ${r.settings.revision}).` });
      api.history().then((h) => setHistory(h.history));
      refreshStatus();
    } catch (e) {
      setNotice({ kind: "error", text: `Could not undo: ${msg(e)}` });
    } finally {
      setBusy(null);
    }
  }

  async function send(body: Record<string, unknown>, label: string) {
    setBusy(label);
    setNotice(null);
    try {
      lastSent.current = body;
      const r = await api.command(body);
      setNotice({ kind: r.warning ? "warn" : "info", text: r.warning ?? `Sent command ${short(r.command.id)}. Waiting for the display to confirm.` });
      if (body.type === "blackout" || body.type === "resume") await loadSettings();
      refreshStatus();
    } catch (e) {
      setNotice({ kind: "error", text: `Not sent: ${msg(e)}` });
    } finally {
      setBusy(null);
    }
  }
  const sendSelected = () => send({ type: "play", reaction: selected, speed: opts.speed, cycles: opts.cycles, hold: opts.hold }, "send");

  async function doLogin(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.login(password);
      setPassword("");
      setAuth("in");
      setNotice(null);
    } catch (err) {
      setNotice({ kind: "error", text: msg(err) });
    }
  }

  // ---- render ----
  if (libError) return <p role="alert">Could not load the sprite library: {libError}</p>;
  if (auth === "loading" || !lib) return <p>Loading…</p>;
  if (auth === "unconfigured") return <p role="alert">The control server is not configured and refuses requests. {notice?.text}</p>;
  if (auth === "out")
    return (
      <form onSubmit={doLogin} className="login" aria-labelledby="login-h">
        <h2 id="login-h">Staff sign in</h2>
        <p className="muted">The control room needs a staff session to change settings or send to the display. The local preview works without one in mock mode.</p>
        <label>Password <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <button type="submit">Sign in</button>
        {notice && <p role="alert" className={`notice ${notice.kind}`}>{notice.text}</p>}
      </form>
    );
  if (!draft || !saved) return <p>Loading settings…</p>;

  const colours = effectiveColors(draft);
  const cols: Colours = [colours.sheep_a, colours.sheep_b, colours.effects];
  const dev = status?.device;
  const lc = status?.last_command ?? null;
  const reactionLabel = (id: string) => draft.reactions[id].label ?? lib.byId[id].label;
  const enabledIds = REACTION_IDS.filter((id) => draft.reactions[id].enabled);
  const capScale = (HARD_MAX_PERMILLE / 1000).toFixed(2);
  const blackout = status?.blackout ?? saved.blackout;

  return (
    <>
      <StatusBar status={status} err={statusErr} mode={mode} savedRev={saved.revision} />
      {notice && <p role={notice.kind === "error" ? "alert" : "status"} className={`notice ${notice.kind}`}>{notice.text}</p>}

      <div className="layout">
        <PreviewPanel lib={lib} reactionId={selected} cols={cols} brightnessPct={draft.brightness_percent} replayKey={replayKey} />

        <section aria-labelledby="send-h">
          <h2 id="send-h" className="eyebrow">Send to display</h2>
          <p><strong>{reactionLabel(selected)}</strong> <code>{selected}</code></p>
          <div className="row">
            <label>Speed{" "}
              <select value={opts.speed} onChange={(e) => setOpts({ ...opts, speed: Number(e.target.value) })}>
                {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
              </select>
            </label>
            <label>Cycles{" "}
              <input type="number" min={CYCLES_MIN} max={CYCLES_MAX} value={opts.cycles} disabled={opts.hold}
                onChange={(e) => setOpts({ ...opts, cycles: Math.max(CYCLES_MIN, Math.min(CYCLES_MAX, Math.round(Number(e.target.value) || 1))) })} />
            </label>
            <label><input type="checkbox" checked={opts.hold} onChange={(e) => setOpts({ ...opts, hold: e.target.checked })} /> Hold (loop until stopped, max 10 min)</label>
          </div>
          <div className="row">
            <button className="primary" disabled={!!busy || !draft.reactions[selected].enabled || blackout} onClick={sendSelected}>
              {busy === "send" ? "Sending…" : "Send to display"}
            </button>
            <button disabled={!!busy || !lastSent.current || lastSent.current.type !== "play"} onClick={() => lastSent.current && send(lastSent.current, "replay")} title="Sends the same reaction again as a new command">
              Replay on display
            </button>
            <button disabled={!!busy} onClick={() => send({ type: "idle" }, "idle")}>Return to idle</button>
            {blackout ? (
              <button className="primary" disabled={!!busy} onClick={() => send({ type: "resume" }, "resume")}>Resume from blackout</button>
            ) : (
              <button className="danger" disabled={!!busy} onClick={() => send({ type: "blackout" }, "blackout")}>Blackout</button>
            )}
          </div>
          {!draft.reactions[selected].enabled && <p className="muted">This reaction is disabled in the library below.</p>}
          {blackout && <p className="notice warn" role="status">Blackout is on and stays on, even after the display reboots, until you resume.</p>}
          <CommandTracker cmd={lc} dev={dev} busy={busy} />
          <p className="muted">
            Preview first, then send. Each click sends a NEW command, so repeating the same reaction plays it again. Unsent edits below are not sent until you press Save.
          </p>
        </section>

        <section aria-labelledby="chars-h">
          <h2 id="chars-h" className="eyebrow">Characters</h2>
          {([["sheep_a", "Sheep A"], ["sheep_b", "Sheep B"]] as const).map(([k, fallback]) => (
            <div className="colour" key={k}>
              <label>Name{" "}
                <input type="text" maxLength={NAME_MAX} value={draft.names[k]} aria-label={`${fallback} name`} onChange={(e) => upd((d) => void (d.names[k] = e.target.value))} />
              </label>
              <ColourPicker label={`${fallback} colour`} value={draft.colors[k]} onChange={(v) => upd((d) => void (d.colors[k] = v))} />
            </div>
          ))}
          <div className="colour">
            <label><input type="checkbox" checked={!draft.effects_linked} onChange={(e) => upd((d) => void (d.effects_linked = !e.target.checked))} /> Separate effects colour</label>
            {!draft.effects_linked ? (
              <ColourPicker label="Effects colour" value={draft.colors.effects} onChange={(v) => upd((d) => void (d.colors.effects = v))} />
            ) : (
              <span className="muted">Effects follow Sheep A ({draft.colors.sheep_a})</span>
            )}
          </div>
          <div className="row">
            <button onClick={() => upd((d) => { const x = defaultSettings(); d.colors = x.colors; d.effects_linked = x.effects_linked; d.names = x.names; })}>Reset colours and names to defaults</button>
          </div>

          <h2 className="eyebrow">Presets</h2>
          <div className="row">
            <label>Name{" "}
              <input type="text" maxLength={NAME_MAX} value={presetName} onChange={(e) => setPresetName(e.target.value)} />
            </label>
            <button disabled={!presetName.trim() || draft.presets.length >= PRESETS_MAX}
              onClick={() => { upd((d) => void d.presets.push({ id: `p-${Date.now().toString(36)}`, name: presetName.trim(), colors: { ...d.colors } })); setPresetName(""); }}>
              Save current colours as preset
            </button>
          </div>
          <ul className="plain">
            {draft.presets.map((p) => (
              <li key={p.id} className="row">
                <span className="dots" aria-hidden="true">{[p.colors.sheep_a, p.colors.sheep_b, p.colors.effects].map((c, i) => <i key={i} style={{ background: c }} />)}</span>
                <span>{p.name}</span>
                <button onClick={() => upd((d) => void (d.colors = { ...p.colors }))}>Apply</button>
                <button onClick={() => upd((d) => void (d.presets = d.presets.filter((x) => x.id !== p.id)))} aria-label={`Delete preset ${p.name}`}>Delete</button>
              </li>
            ))}
          </ul>

          <h2 className="eyebrow">Brightness</h2>
          <label className="block">
            {draft.brightness_percent}% of the firmware-approved cap
            <input type="range" min={0} max={100} value={draft.brightness_percent} aria-label="Brightness as a percentage of the firmware-approved cap"
              onChange={(e) => upd((d) => void (d.brightness_percent = Number(e.target.value)))} />
          </label>
          <p className="muted">
            Cap in this build: RGB scale {capScale} (a software limit, not a measured electrical limit). At {draft.brightness_percent}% the display would use{" "}
            {((HARD_MAX_PERMILLE * draft.brightness_percent) / 100000).toFixed(3)}. Board-reported limit:{" "}
            <strong>{dev?.seen && dev.effective_cap_permille !== undefined ? `${(dev.effective_cap_permille / 1000).toFixed(2)}${dev.simulated ? " (reported by the SIMULATOR, not hardware)" : ""}` : "unknown, no display has reported yet"}</strong>.
            This slider can never raise the firmware limit.
          </p>

          <h2 className="eyebrow">Ambient</h2>
          <label>Between reactions the display shows{" "}
            <select value={draft.ambient.mode} onChange={(e) => upd((d) => void (d.ambient.mode = e.target.value as "idle" | "rotation"))}>
              <option value="idle">Idle only</option>
              <option value="rotation">Rotate through chosen reactions</option>
            </select>
          </label>
          {draft.ambient.mode === "rotation" && (
            <fieldset>
              <legend>Rotation</legend>
              <div className="checks">
                {enabledIds.map((id) => (
                  <label key={id}><input type="checkbox" checked={draft.ambient.rotation.includes(id)}
                    onChange={(e) => upd((d) => void (d.ambient.rotation = e.target.checked ? [...d.ambient.rotation, id] : d.ambient.rotation.filter((x) => x !== id)))} /> {reactionLabel(id)}</label>
                ))}
              </div>
              <label>Every{" "}
                <input type="number" min={ROTATION_INTERVAL.min} max={ROTATION_INTERVAL.max} value={draft.ambient.interval_s}
                  onChange={(e) => upd((d) => void (d.ambient.interval_s = Math.max(ROTATION_INTERVAL.min, Math.min(ROTATION_INTERVAL.max, Math.round(Number(e.target.value) || ROTATION_INTERVAL.min)))))} /> seconds
              </label>
            </fieldset>
          )}
          <p className="muted">Stored and sent to the display. The firmware does not play ambient rotation yet.</p>
        </section>

        <section aria-labelledby="save-h" className="wide savebar">
          <h2 id="save-h" className="eyebrow">Settings</h2>
          <div className="row">
            <button className="primary" disabled={!dirty || !!busy} onClick={save}>{busy === "save" ? "Saving…" : "Save and apply to display"}</button>
            <button disabled={!dirty || !!busy} onClick={() => setDraft(saved)}>Discard edits</button>
            <span role="status">{dirty ? "Unsaved edits (preview shows them, the display does not)" : `Saved, revision ${saved.revision}`}</span>
          </div>
        </section>

        <section aria-labelledby="lib-h" className="wide">
          <h2 id="lib-h" className="eyebrow">Reaction library</h2>
          <p className="muted">Click a name to preview it and load it into the send panel. Disabled reactions cannot be sent, mapped or rotated.</p>
          <div className="rxlist">
            {lib.reactions.map((r) => {
              const s = draft.reactions[r.id];
              return (
                <div key={r.id} className={`rx ${r.id === selected ? "sel" : ""}`}>
                  <button className="rxname" aria-pressed={r.id === selected} onClick={() => choose(r.id)} title={r.description}>
                    {reactionLabel(r.id)}<small>{r.id}</small>
                  </button>
                  <label className="rxf"><input type="checkbox" checked={s.enabled} disabled={r.id === "idle"} onChange={(e) => upd((d) => void (d.reactions[r.id].enabled = e.target.checked))} /> Enabled</label>
                  <label className="rxf">Label{" "}
                    <input type="text" maxLength={LABEL_MAX} placeholder={r.label} value={s.label ?? ""} onChange={(e) => upd((d) => void (d.reactions[r.id].label = e.target.value.trim() ? e.target.value : null))} />
                  </label>
                  <label className="rxf">Speed{" "}
                    <select value={s.speed} onChange={(e) => upd((d) => void (d.reactions[r.id].speed = Number(e.target.value)))}>
                      {SPEEDS.filter((x) => x >= SPEED_MIN && x <= SPEED_MAX).map((x) => <option key={x} value={x}>{x}×</option>)}
                    </select>
                  </label>
                  <label className="rxf">Cycles{" "}
                    <input type="number" min={CYCLES_MIN} max={CYCLES_MAX} value={s.cycles} onChange={(e) => upd((d) => void (d.reactions[r.id].cycles = Math.max(CYCLES_MIN, Math.min(CYCLES_MAX, Math.round(Number(e.target.value) || 1)))))} />
                  </label>
                </div>
              );
            })}
          </div>
        </section>

        <section aria-labelledby="ev-h">
          <h2 id="ev-h" className="eyebrow">Event mapping</h2>
          <p className="muted">Events will come from later integrations. Here you choose which approved reaction each one plays.</p>
          {EVENT_NAMES.map((ev) => (
            <div className="row" key={ev}>
              <code className="evname">{ev}</code>
              <select aria-label={`Reaction for ${ev}`} value={draft.events[ev] ?? ""} onChange={(e) => upd((d) => void (d.events[ev] = e.target.value || null))}>
                <option value="">(none)</option>
                {enabledIds.map((id) => <option key={id} value={id}>{reactionLabel(id)}</option>)}
              </select>
              <button disabled={!!busy || dirty} title={dirty ? "Save your edits first: events use the saved mapping" : "Trigger this event now"} onClick={() => send({ type: "event", event: ev }, "event")}>Trigger</button>
            </div>
          ))}
        </section>

        <section aria-labelledby="hist-h">
          <h2 id="hist-h" className="eyebrow">Change history</h2>
          <div className="row">
            <button disabled={!!busy || !history.some((h) => h.kind === "settings" && !h.undone)} onClick={undo}>Undo last change</button>
          </div>
          <ol className="plain hist">
            {history.length === 0 && <li className="muted">No changes yet.</li>}
            {history.map((h) => (
              <li key={`${h.revision}-${h.kind}`} className={h.undone ? "undone" : ""}>
                <code>r{h.revision}</code> {h.kind} · {h.summary} <small className="muted">· {new Date(h.at).toLocaleTimeString()}{h.undone ? " · undone" : ""}</small>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}

function ColourPicker(props: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <span className="picker">
      <label>{props.label}{" "}
        <input type="color" value={props.value} onChange={(e) => props.onChange(e.target.value.toUpperCase())} />
      </label>
      <code>{props.value}</code>
      <span className="swatches" role="group" aria-label={`${props.label} presets`}>
        {SWATCHES.map((hex) => (
          <button key={hex} style={{ background: hex }} title={hex} aria-label={`Set ${props.label} to ${hex}`} onClick={() => props.onChange(hex)} />
        ))}
      </span>
    </span>
  );
}

function StatusBar({ status, err, mode, savedRev }: { status: Status | null; err: string | null; mode: "mock" | "prod" | null; savedRev: number }) {
  const d = status?.device;
  let badge: { cls: string; text: string };
  if (err) badge = { cls: "bad", text: `Control server unreachable: ${err}` };
  else if (!status) badge = { cls: "dim", text: "Checking…" };
  else if (!d?.seen) badge = { cls: "dim", text: "No display has connected yet" };
  else if (d.online) badge = { cls: "good", text: `Display online · last heartbeat ${ago(d.age_s)}${d.simulated ? " · SIMULATED DEVICE" : ""}` };
  else badge = { cls: "bad", text: `Display OFFLINE · last heartbeat ${ago(d.age_s)}` };
  return (
    <div className="statusbar" role="region" aria-label="Display status">
      {mode === "mock" && <span className="chip mock">MOCK MODE: no staff login, development data only</span>}
      <span className={`chip ${badge.cls}`} role="status">{badge.text}</span>
      <span className="chip dim">Saved revision {savedRev}</span>
      {d?.seen && (
        <>
          <span className={`chip ${!d.online ? "dim" : d.config_in_sync ? "good" : "warn"}`}>{d.online ? "Display applied" : "Last applied by display"}: revision {d.config_revision_applied}{d.config_in_sync ? "" : " (behind)"}</span>
          <span className="chip dim">{d.online ? "Display says" : "Last report"}: {d.state}{d.reaction ? ` · ${d.reaction}` : ""}{d.blackout_reported ? " · blackout" : ""}</span>
        </>
      )}
    </div>
  );
}

function CommandTracker({ cmd, dev, busy }: { cmd: CommandView | null; dev?: Status["device"]; busy: string | null }) {
  let state: { cls: string; label: string; detail: string };
  if (busy === "send" || busy === "replay" || busy === "idle" || busy === "blackout" || busy === "resume" || busy === "event")
    state = { cls: "warn", label: "Sending", detail: "Posting the command to the control server…" };
  else if (!cmd) state = { cls: "dim", label: "No command yet", detail: "Nothing has been sent from this control room." };
  else if (cmd.display_state === "applied") state = { cls: "good", label: "Applied", detail: `The display confirmed it.` };
  else if (cmd.display_state === "pending" && dev && !dev.online) state = { cls: "bad", label: "Offline", detail: "Saved, but no display is connected. One-off reactions expire quickly so they do not play later." };
  else if (cmd.display_state === "pending") state = { cls: "warn", label: "Pending", detail: "Sent to the server; waiting for the display to pick it up and confirm." };
  else if (cmd.display_state === "expired") state = { cls: "bad", label: "Expired", detail: "The display did not confirm in time, so it will never play." };
  else state = { cls: "dim", label: "Superseded", detail: "A newer command replaced this one." };
  return (
    <div className="tracker" role="status" aria-live="polite">
      <span className={`chip ${state.cls}`}>{state.label}</span>{" "}
      {cmd && <span>{cmd.type === "play" ? cmd.reaction : cmd.type} · command <code>{short(cmd.id)}</code></span>}
      <p className="muted">{state.detail}{dev?.last_command_id ? ` Display last acknowledged ${short(dev.last_command_id)}.` : ""}</p>
    </div>
  );
}
