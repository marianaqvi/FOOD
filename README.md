# FOOD / Two Little Sheep

Reception character habitat for FOOD Arts & Technology: two sheep on a 64 x 32 LED habitat (left panel of a 128 x 32 HUB75 pair, right panel reserved and always black), driven by an Interstate 75 W (RP2350, MicroPython), plus a separate web control room. Scope of this milestone: characters and control room only. No text, fonts, AI chat, camera or weather integrations yet.

Full brief: `CLAUDE.md`. Studio brief: `reference/reception-display-brief.pdf`.

## Status

| Milestone | State |
| --- | --- |
| 1. Asset pipeline, tests, CPU reference renderer, docs | done (software only) |
| 1. Next.js canvas preview | built in `web/`; typecheck, 5 parity tests and production build pass; **not yet looked at in a browser** (see docs/test-log.md) |
| 2. Hardware proof | pending your go-ahead; nothing has touched the board |
| 3 to 5. Web app, device link, production | not started |

## Layout

```
assets/food_sheep_animation_assets.json   canonical sprites (never edited)
reference/                                brief, photos, approved demos
scripts/pack_assets.py                    validate + convert JSON -> per-reaction binaries
scripts/reference_renderer.py             CPU reference renderer (spec for browser and firmware)
shared/limits.json                        versioned limits and defaults
firmware/assets/                          generated .bin files + manifest.json (480,480 bytes)
tests/                                    packing, parity, renderer golden tests
docs/hardware.md                          wiring observations and safety checklist
docs/test-log.md                          software vs hardware test record
```

## Commands

Run from the repo root with standard CPython 3.8+ (no extra packages):

```bash
python3 scripts/pack_assets.py          # validate source and write firmware/assets/
python3 scripts/pack_assets.py --check  # fail if firmware/assets/ is stale
python3 -m unittest discover -s tests   # 28 tests
```

## Binary format

One `<reaction_id>.bin` per reaction: fixed 770-byte records, `uint16 LE duration_ms` then three 256-byte masks (sheep A, sheep B, effects). A mask is 32 rows x 8 bytes, row-major, MSB-first: pixel (x, y) is lit when `mask[y*8 + (x>>3)] & (0x80 >> (x&7))`. Draw order A, B, effects; later layers overwrite earlier ones. `manifest.json` has frame counts, sizes, CRC32, SHA-256 and the `asset_version` (first 12 hex of the source SHA-256).

## Safety

The preview and tests cannot certify electrical safety. Read `docs/hardware.md` before connecting anything. Limits (RGB scale 0.10, 281 lit pixels, speed 0.5x to 1x) live in `shared/limits.json`. Never flash or overwrite the board without backing it up first.
