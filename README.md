# FOOD / Two Little Sheep

Reception character habitat for FOOD Arts & Technology: two sheep on a 64 x 32 LED habitat (left panel of a 128 x 32 HUB75 pair, right panel reserved and always black), driven by an Interstate 75 W (RP2350, MicroPython), plus a separate web control room. Scope of this milestone: characters and control room only. No text, fonts, AI chat, camera or weather integrations yet.

Full brief: `CLAUDE.md`. Studio brief: `reference/reception-display-brief.pdf`.

## Status

| Milestone | State |
| --- | --- |
| 1. Asset pipeline, tests, CPU reference renderer, docs | done (software only) |
| 1. Next.js canvas preview | built in `web/`; typecheck, 5 parity tests and production build pass; checked by eye in the browser pane with `next start` and `npm run dev` (see docs/test-log.md) |
| 2. Hardware proof | scripts and step-by-step guide written and tested against a fake board only (`docs/hardware-proof.md`); stages 1 and 2 passed on a real panel; two panels together on the one adapter collapse the board's power (see docs/test-log.md); **single-panel mode is the interim plan**. Renderer, player and clip stages 5-6 are written and host-tested (116 tests) but **not yet installed or run on the board** |
| 3. Web control room and mock API | built in `web/` (UI, settings with history and undo, commands with acks, mock mode, device simulator); 66 web tests plus a manual browser pass; see `docs/api.md` |
| 4. Firmware link to the backend | firmware written and host-tested (173 tests plus an end-to-end run against the real server); deploy tooling ready; **not yet run on the board** (`docs/hardware-proof.md` Part F) |
| 5. Production | not started |

## Layout

```
assets/food_sheep_animation_assets.json   canonical sprites (never edited)
reference/                                brief, photos, approved demos
scripts/pack_assets.py                    validate + convert JSON -> per-reaction binaries
scripts/reference_renderer.py             CPU reference renderer (spec for browser and firmware)
shared/limits.json                        versioned limits and defaults
firmware/assets/                          generated .bin files + manifest.json (480,480 bytes)
firmware/power.py                         hard limits on the device (RGB clamp, lit-pixel cap)
firmware/hwtest_common.py                 strict helpers for the sparse hardware tests
firmware/renderer.py                      composes a packed frame into the display (clip, origin, clamps, caps)
firmware/player.py                        non-blocking streaming player with fallback (one frame in RAM)
firmware/network_client.py                non-blocking HTTP, Wi-Fi manager, poll/heartbeat scheduler with backoff
firmware/config_store.py                  strict config validation, atomic last-known-good cache
firmware/isotime.py                       UTC timestamp parsing without an RTC
firmware/app.py                           the networked player (config, commands, blackout, ambient rotation)
firmware/secrets.example.py               template; real secrets.py is git-ignored (scripts/make_secrets.py)
scripts/deploy_board.py, boardlink.py     verified USB deploy of the firmware (never flashes)
tests/e2e_device_vs_server.py             real firmware modules vs the real server (run by hand)
firmware/fallback.py                      GENERATED: idle record 0, shown only if animation files are bad
scripts/make_fallback.py                  regenerates/checks firmware/fallback.py
firmware/tools/hw*.py                     stage 0 to 3 board scripts (gated, at most 4 pixels)
firmware/tools/stage_runner_main.py       button-armed stage runner, installed on the board as main.py
tests/                                    packing, parity, renderer golden tests, fake-board script tests
docs/hardware-proof.md                    exact Mac/Thonny steps for the hardware proof
docs/hardware.md                          wiring observations and safety checklist
docs/test-log.md                          software vs hardware test record
docs/api.md                               control room API, device contract, run commands
web/                                      Next.js control room (UI, API routes, file-backed dev repository, device simulator)
```

## Commands

Run from the repo root with standard CPython 3.8+ (no extra packages):

```bash
python3 scripts/pack_assets.py          # validate source and write firmware/assets/
python3 scripts/pack_assets.py --check  # fail if firmware/assets/ is stale
python3 -m unittest discover -s tests   # 173 tests
```

## Binary format

One `<reaction_id>.bin` per reaction: fixed 770-byte records, `uint16 LE duration_ms` then three 256-byte masks (sheep A, sheep B, effects). A mask is 32 rows x 8 bytes, row-major, MSB-first: pixel (x, y) is lit when `mask[y*8 + (x>>3)] & (0x80 >> (x&7))`. Draw order A, B, effects; later layers overwrite earlier ones. `manifest.json` has frame counts, sizes, CRC32, SHA-256 and the `asset_version` (first 12 hex of the source SHA-256).

## Safety

The preview and tests cannot certify electrical safety. Read `docs/hardware.md` before connecting anything. Limits (RGB scale hard max 0.20 since 2026-11-26, 281 lit pixels, speed 0.5x to 1x) live in `shared/limits.json`. Never flash or overwrite the board without backing it up first.
