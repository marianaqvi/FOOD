# Test log

Software tests and hardware tests are kept separate. A hardware row stays **PENDING** until you run it and enter the measured result.

## Software tests

| Date | Test | Result |
| --- | --- | --- |
| 2026-11-24 | `python3 scripts/pack_assets.py` validates source: 18 reactions, 624 frames, all 150 ms, reactions 4.8 s or 6 s, max union coverage 281/2048 | pass |
| 2026-11-24 | Packed size 480,480 bytes in 18 files plus manifest; every frame round-trips byte for byte against the source JSON | pass |
| 2026-11-24 | `python3 -m unittest discover -s tests`: 28 tests (packing, parity, corruption detection, renderer golden pixels, both origins, single-panel mode, layer overwrite order, hard scale clamp, no pixel in reserved half across all 624 frames x 2 origins) | pass |

| 2026-11-24 | `python3 scripts/export_golden.py` then `cd web && npm test`: TypeScript compositor vs Python reference renderer, all 624 frames x 3 modes (origin 0, origin 64, single panel) hash-identical; reserved half black for every frame; hard scale clamp; blackout; bad origins rejected (5 tests) | pass |
| 2026-11-24 | `cd web && npm run typecheck` and `npm run build` (Next.js 16.4.6, Node v24.22.3) | pass |
| 2026-11-25 | Preview served with `next start` and checked in the built-in browser pane: library loads (asset 200), idle animates, Birthday selected (275 unique lit), 128 x 32 view shows right half black with seam overlay, Sheep B colour preset applies, "as scaled for hardware" intensity renders very dim as expected, no console errors | pass (visual, manual) |
| 2026-11-25 | `npm run dev` (Next 16.4.6, Turbopack) | pass after retest: banner prints, `GET /` 200, warm requests ~13 ms on localhost, 127.0.0.1 and ::1, page renders in the browser pane with no console errors |
| 2026-11-25 | Earlier `npm run dev` hang (no banner, or listening but never answering; same with `--webpack`) | **Cause not proven.** It coincided with a period of severe slowness on this Mac: load average above 200 from macOS system processes, then plain `cat` of 584 small files taking 2m41s at ~0% CPU. The same read took 0.06s minutes later with no project change. Treat as an environment stall. If it recurs, try `WATCHPACK_POLLING=true npm run dev -- --webpack` and check `uptime` first |

Not yet written or run: firmware scheduler tests, web validator/API tests, Playwright control tests, integration tests.

Note: Node 24.22.3 is installed at `~/.local/node` (official tarball, SHA-256 checked), not via Homebrew, because Homebrew has no prebuilt packages for this macOS and would have compiled OpenSSL and Node from source. Add `export PATH="$HOME/.local/node/bin:$PATH"` to `~/.zshrc` to use it in new terminals.

## Hardware tests (all PENDING)

| Test | Result | Measured current / notes |
| --- | --- | --- |
| Identify RP2350, back up files | PENDING | |
| Sparse pixel at 0.10 | PENDING | |
| Colour order | PENDING | |
| Panel order and habitat origin | PENDING | |
| Reserved half stays black | PENDING | |
| Idle clip, then sleep and morph | PENDING | |
| Free flash and RAM | PENDING | |
| Upload all packed assets | PENDING | |
| One-hour soak | PENDING | |
| Reception-distance readability | PENDING | |
