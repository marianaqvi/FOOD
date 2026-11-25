# FOOD / Two Little Sheep — implementation brief

## Role and objective
Act as a senior creative technologist, embedded systems engineer and frontend developer. Build a working interactive reception installation for FOOD Arts & Technology, London, UK. The studio's wider brief describes a slightly enigmatic living sign inspired by L.A. Story, remote web control, validated content, offline playback and later an AI agent. This milestone is ONLY the character habitat and its separate web control room. Text, fonts, AI chat and automated camera/weather integrations are later work. Do not replace the approved sheep designs or expand the scope without approval.

Build in small runnable milestones, write actual files, execute tests where possible, and report the results and precise next commands. Do not merely provide a plan. Do not pretend physical tests or deployment succeeded. Never flash or overwrite the device automatically; ask me to confirm backups, wiring and supply before any physical test. Do not ask me to buy additional hardware unless a specific measured requirement demands it.

## Read the supplied sources before writing code
- `reference/reception-display-brief.pdf`: studio requirements, power, style, architecture and acceptance criteria.
- `reference/IMG_9883.jpeg` through `IMG_9887.jpeg`: my actual hardware and connections; inspect the labels, but do not assume wiring or current is safe based on photos alone.
- `reference/original-sheep-demo.html`: original single sheep design.
- `reference/food_sheep_habitat.html`: approved two-sheep browser simulator; use its animations, colours, layer order and timings as the visual reference. It is a demo, not a working hardware control room.
- `reference/food_sheep_reaction_sheet.png`: visual reference.
- `assets/food_sheep_animation_assets.json`: canonical bitmap source. Do not redraw, simplify, smooth, scale, interpolate, generate or substitute sprites. Do not edit this source. Build a converter from it.

## Existing hardware
- Pimoroni Interstate 75 W (RP2350, wireless, USB-C; not the RP2040 model).
- Two RGB HUB75 panels, each 64 x 32, 6 mm pitch, intended side-by-side as 128 x 32. PCB markings suggest 1/16 scan; verify. The grey ribbon is the data link; red and black leads distribute power. Confirm input/output, orientation and labels with power off.
- Raspberry Pi 27 W USB-C power adapter, described as 5 V / 5 A in the brief. Actual negotiated current and distribution are unknown. A nominal 5 A adapter is not proof that this board, connector and wiring can safely supply 5 A.
- MacBook, MicroPython, Thonny and Claude Code. Wi-Fi credentials and server details will be provided locally, never committed.
- Official references: https://github.com/pimoroni/interstate75 ; https://github.com/pimoroni/pimoroni-pico/blob/main/micropython/modules_py/interstate75.md ; https://learn.pimoroni.com/article/getting-started-with-interstate-75 ; https://shop.pimoroni.com/products/interstate-75-w

## Physical display contract (non-negotiable)
Default chained mode: use the verified official Interstate75.DISPLAY_INTERSTATE75_128X32 configuration; graphics = i75.display; use the official pixel and update functions matching installed firmware. Treat coordinates 0–63, 0–31 as a 64 x 32 habitat. Coordinates x=64–127 must be black at every refresh in this milestone. Add a firmware-only configurable habitat origin (0 or 64), selected after panel order testing, so the physically intended left panel is active even if the wiring order is reversed. Do not expose this as an ordinary staff setting. Optional isolated single-panel test mode uses DISPLAY_INTERSTATE75_64X32 with origin 0. No text, clocks, scenery backgrounds or animations on the reserved panel. Preserve a clean interface for a future second renderer. Clear the entire hardware buffer before composing a frame; update once per frame. Clip every habitat pixel to the local 64 x 32 region before applying the origin.

Power: do not hot-plug HUB75 or power leads; confirm polarity and common ground, check supply labels, safe USB/external power configuration and board limits against RP2350 documentation. Do not connect two supplies unless manufacturer guidance explicitly permits the configuration. Back up existing firmware/files first. Begin with one sparse pixel at low intensity, then sparse panel-order markers and one panel. Use an appropriate known-safe power arrangement and current measurement, not the Mac USB port to drive two panels. Second panel black still draws standby current. Never run full-white or flashing tests. Start with a conservative software RGB scale of 0.10 (not a measured safe electrical limit), hard-clamped in firmware; use a fixed maximum of 281 distinct lit habitat pixels for the supplied library and reject more complex edits until reviewed. Apply a calibrated channel-weighted aggregate frame budget in firmware before update, including effects; document calibration and current measurements, do not invent them. Keep the stricter of all limits. No strobe, abrupt repeated global brightness changes, unapproved arbitrary drawing, or unsafe speed. Use black backgrounds. Do not increase the hard cap remotely. The preview cannot certify electrical safety.

## Exact assets and rendering
The source JSON has width=64, height=32, encoding=base64 row-major MSB-first 1-bit, 8 bytes per row; layers=[sheep_a,sheep_b,effects]. `animations` maps reaction ID to arrays of `[duration_ms, a_mask, b_mask, effects_mask]`. Each decoded mask is 256 bytes, 32 rows x 8 bytes. Pixel (x,y) is set when `mask[y*8 + (x >> 3)] & (0x80 >> (x & 7))` is nonzero. Draw in A, B, effects order, later layers overwrite earlier layers at shared pixels, matching the reference. Apply the chosen colours and brightness without modifying masks. Source contains 18 modes, 624 frames, all at 150 ms per frame; reactions last 4.8 or 6 seconds; max union coverage 281/2048. Check these invariants programmatically. The source base sheep is 17 x 16, with the exact original outline and face; the existing squashes, stretches, sleeps and morphs are already baked into frames. A/B have separately coloured masks but are choreographed together, not an arbitrary independent animation engine. For the MVP do not promise independent per-character reaction selection unless new, collision-safe composition and tests are implemented.

Build `scripts/pack_assets.py` using standard CPython to decode and validate all frames and write one compact binary file per reaction, plus a manifest with reaction IDs, frame count, duration, offsets/version/checksum. Use a documented simple format (e.g. fixed 770-byte records: uint16 little-endian duration then 3 x 256 mask bytes). Raw records total 480,480 bytes; check available filesystem space on the actual board before copying. Avoid loading the 641 KiB JSON or entire decoded library into MicroPython RAM. Stream a frame at a time, reuse buffers, cache only current or small bounded data, close file handles, validate file size/manifest and include a minimal built-in idle fallback. Never stream video or every animation frame over Wi-Fi. Browser reads the same canonical JSON; device plays the converted local assets. Add an automated round-trip parity test comparing every packed frame to its original masks and timings. Provide a CPU reference renderer and golden pixel tests for both panel origins and colour overlap.

## Reactions and timing
Expose all IDs exactly as provided: `idle`, `wake`, `arrive`, `weather_rain`, `weather_sun`, `weather_cloud`, `celebrate`, `birthday`, `sleep`, `wave`, `dance`, `bored`, `clap`, `launch`, `sunset`, `christmas`, `thought`, `morph`. Use labels and descriptions from the JSON. Preserve original blink, bounce, arrival, weather effects, birthday cake, squishy sleep, wave, dance and morph frames. Idle loops indefinitely. By default a manual reaction plays once, then returns to idle (or selected ambient state). Allow explicit loop/hold and duration/number of cycles subject to safe limits; stop/return-to-idle takes priority. Support a safe speed range (0.5x–1x initially; no faster until tested). For the installed version allow configurable ambient idle rotation and reaction enable/disable, ordering, labels, event mapping and safe per-reaction speed/repeat settings. Do not add user-generated pixels in v1. When a reaction ends, return to ambient even if network disappears. Use monotonic ticks with wrap-safe comparisons and a bounded scheduler. Do not block the animation for network retries; measure responsiveness and implement bounded nonblocking/cooperative network I/O where possible. If TLS stalls, document and solve via a tested transport or trusted local gateway, not by disabling verification.

## Separate web control room
Create a real responsive Next.js + TypeScript app in `web/` (not a webpage hosted by the microcontroller). Match the simple cream/black visual treatment of the supplied demo. Use a real Canvas at native 64 x 32, scaled via nearest neighbour with optional LED grid. Add optional 128 x 32 preview with reserved half black and panel seam as UI overlay only. Do not recreate assets using CSS or generic sprites.

UI requirements:
1. Preview with reaction name, animation frame, unique lit-pixel count, play/pause/replay and grid/raw toggle. Distinguish local preview from acknowledged hardware state.
2. Character settings: independent names and RGB hex colour pickers for Sheep A and B, preset swatches, optional separate effects colour, reset defaults. Colours persist after refresh and device reboot. Default A/B/effects #F0F5F1, choose low physical brightness separately.
3. Reaction library: all 18 buttons, descriptive names, preview before sending, select speed and cycle count or hold/loop where supported, enable/disable per reaction, edit event-to-reaction mapping, ambient mode/rotation. Store settings durably. Manual actions send a new command ID; replay the same reaction must generate a new ID. Pause preview is local only; separate device stop/idle control is explicit.
4. `Send to display` applies settings or triggers an event; `Return to idle` and `Blackout` controls; explicit resume. Show sending/pending/applied/offline/error states, last heartbeat and actual acknowledged reaction, config revision and command ID. Do not call a simulated preview a live feed. If offline, save settings but expire one-off reactions to avoid stale greetings when reconnecting.
5. Brightness slider 0–100% of the firmware-approved cap (NOT raw 0–100% hardware output). Show actual effective limit reported by board. No browser control may override firmware hard limits.
6. Persist presets, mappings and change history with undo; local preview works without credentials. Include accessible labels, keyboard controls and responsive layout. No AI chat, text panel or camera features for now.

## Backend and network
Start locally on my Mac (Node LTS, npm, Next.js) with explicit mock mode and a persistent local SQLite or file-backed repository for development only. For LAN proof of concept bind to the trusted network interface, not public internet. Use the Mac LAN IP (not localhost from the board); verify firewall and office Wi-Fi isolation, do not bypass policy. Use a dedicated trusted test network if necessary. Temporary HTTP only with non-sensitive test data on isolated trusted LAN; no production secrets over cleartext. The board polls small control JSON every ~2 seconds (configurable), sends heartbeat every ~15 seconds, with short timeouts and backoff. Production target Vercel + Supabase Postgres (or equivalent durable database), not runtime JSON writes to Vercel disk. Keep repository adapter interface consistent. Web remains available when Mac is shut down after deployment. Use HTTPS with actual certificate/hostname validation and device clock sync, verified against installed MicroPython TLS support; if unavailable, use a trusted TLS-capable gateway. Never disable certificate verification to make production work.

Define versioned endpoints: GET `/api/device/config` (read-only device credential), POST `/api/device/heartbeat` (device-specific token), GET/PATCH `/api/settings` (staff session), POST `/api/commands` (staff session), GET `/api/status` (staff session). Use separate high-entropy device token, per-device auth, staff login, CSRF/origin protection as appropriate, server-side validation, bounded request sizes, rate limiting, secure env vars and no secret in Git/browser bundles/logs. No arbitrary code, scripts, paths, remote firmware or unapproved frames accepted. Use command IDs and revisions (idempotent), expiry UTC, reject stale commands, support explicit replay and acknowledgements. Sample configuration (illustrative only):

```json
{"schema_version":1,"revision":5,"asset_version":"build-hash","colors":{"sheep_a":"#F0F5F1","sheep_b":"#FFB34F","effects":"#F0F5F1"},"brightness_percent":75,"ambient":"idle","command":{"id":"uuid","reaction":"birthday","speed":1,"cycles":1,"expires_at":"UTC ISO timestamp"},"blackout":false}
```

Persist settings separately from transient events; blackout survives reboot until explicit resume. Cache only validated last-known-good config atomically using temp+rename or dual-slot recovery; avoid unnecessary flash writes. Validate enums, hex values, bounds, versions and data length on server and device. On malformed payload, asset corruption or offline state retain safe local fallback; do not lose animation. On reboot, start with idle or persisted blackout, never replay expired events. Document how clock trust and expiry work offline. Verify network failure doesn't freeze frame playback. Do not publish without explicit user approval and appropriate credentials.

## Suggested repository layout
```
CLAUDE.md
README.md
assets/food_sheep_animation_assets.json
reference/...
scripts/pack_assets.py
firmware/main.py
firmware/renderer.py
firmware/player.py
firmware/power.py
firmware/network_client.py
firmware/config_store.py
firmware/secrets.example.py
firmware/assets/ (generated .bin + manifest)
web/ (Next.js, TypeScript, validator, canvas, API, storage)
shared/ (versioned schema, limits, defaults)
tests/ (packing, rendering, scheduling, API and integration)
docs/hardware.md
docs/test-log.md
```

## Build milestones in this order
1. Inspect reference and installed tools. Create repository files, README, architecture and safety checklist. Run asset validation/conversion and parity tests. Build mock/native Canvas preview. Show exact commands and test results. Do not touch board yet.
2. Hardware proof: give Mac/Thonny steps to identify the RP2350, back up files, select compatible Pimoroni UF2 only if needed, and verify imports and dimensions. After wiring/power confirmation, test sparse pixel, low-level colour order, panel order, black reserved half and one short local idle clip. Record current draw and behaviour. No automatic flashing. Run original idle and sleep/morph locally before Wi-Fi. Confirm on-device free space and memory, timing and current. Then upload all packed assets if space permits. Run 1-hour soak at approved limits.
3. Build web app and mock endpoints. Test preview parity, colour pickers, all reactions, speed, looping, defaults, validation and persistence. Use Playwright or equivalent for controls; no fake online badge. Run `npm install`, tests, and `npm run dev` when dependencies are available; document exact commands.
4. Connect firmware to real local backend. With approved network, provision secrets locally, copy device files using Thonny or tested mpremote workflow, verify actual panel update, repeated commands, ack and offline fallback. Give explicit steps to restart without laptop, using verified power. Do not write main.py as autoboot until standalone player tested. Reboot and network-loss tests. Keep panel B black even after failed commands.
5. Production deployment: configure durable store/auth on Vercel, HTTPS device polling, environment variables, database migrations and deployment instructions. Do not assume paid plan/account or deploy without consent. Verify remote updates when laptop off, reload and reboot persistence, safe offline playback. Run a week-long unattended test as required by the studio; log issues, do not claim it has passed before measured.
6. Later only: weather provider, time-based schedules, birthdays from manually entered events, opt-in arrival check-ins and local anonymous gesture detection. Define an event interface now (`person.arrived`, `weather.changed`, `birthday`, `gesture.wave`, etc.) that maps to approved reaction IDs, but no real integrations in this milestone. Text panel and AI agent remain separate future milestones. No facial recognition or camera capture in this version.

## Acceptance tests
- Browser and firmware produce identical mask pixels, layer order, frame timing at 1x and independently configurable RGB (subject to hardware cap). Validate all 624 frames and all 18 reactions. Test x=0 and x=64 origins and single panel mode.
- No sheep or effects pixel leaks into reserved panel, including boot, network failure and blackout.
- Exact original idle face, existing morphs and squashed sleep preserved; no interpolation or substitute sprite.
- Manual reaction plays then returns to idle, duplicate command not replayed, same reaction with new ID replays, expiry honored, blackout and resume work.
- Web edits persist, real acknowledgement distinguishes applied from pending/offline, invalid input cannot override safety limits, no secret in repo.
- Offline animation continues, reconnect applies current settings not stale events, corrupt files/config fall back safely, reboot works. Record CPU/RAM/flash usage, real measured power, physical LED orientation and reception-distance readability. Physical tests are pending until I execute them; distinguish software tests from hardware tests.

## Start now
Read every supplied reference, inspect the local environment and create the project structure. Run the asset converter and test suite first, then create the browser preview and minimal low-intensity hardware test. Stop at the physical wiring/power verification checkpoint, give me exact terminal/Thonny steps and a list of checks. Continue milestone by milestone with actual implementation, not just advice. Do not redesign the sheep.
