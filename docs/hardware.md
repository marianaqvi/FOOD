# Hardware notes and safety checklist

Status: **nothing physical has been tested.** Every item below is pending until you do it and record the result in `docs/test-log.md`. The software limits in `shared/limits.json` are conservative defaults, not measured electrical limits.

## What the photos show (not a verified wiring diagram)

Read from `reference/IMG_9883–9887.jpeg`. Treat as observations to confirm with everything unplugged.

- Two 64 x 32 HUB75 panels, back silkscreen `P6-3528-64X32-16S-HL1.1` (so 1/16 scan is plausible, still to verify). Each panel has a `POWER` header (VCC, VCC, GND, GND) fed by a red/black lead set, and a second small white connector with red/black leads.
- The grey ribbon runs between the panels' HUB75 sockets (`JOUT`/input labels; confirm which socket is IN and which is OUT with a close photo).
- An Interstate 75 W sits on the back of one panel, with red/black leads soldered or screwed to its power terminals.
- A UK-plug adapter and a black USB-C cable are on the desk. **It is not clear from the photos whether the USB-C cable plugs into the Interstate 75, or whether the adapter output feeds the red/black leads.** You answered "not sure / not connected yet", so we start from zero below.

## Open questions to settle with power OFF and unplugged

1. Adapter label: exact V and A output, and the PD/negotiation profile. A "5 V / 5 A" claim from the brief is unverified. Delivering 5 A over USB-C needs the right cable and a PD-capable load or breakout, so a bare USB-C lead to red/black wires may only give a lower default current. I believe the Raspberry Pi 27 W supply lists 5.1 V / 5 A among its PD profiles, but verify that from the label rather than trusting my memory.
2. How does 5 V reach the panels: via the adapter's USB-C (cut or breakout board), or some other route? Where do the leads join?
3. Does the Interstate 75 W receive power from the same rail as the panels (the board's own 5 V terminal), and is anything also plugged into its USB-C? Never connect two supplies to one rail unless Pimoroni's documentation explicitly allows it.
4. Polarity: red = +5 V, black = GND at every connector, checked with a multimeter (continuity/polarity) before first power.
5. Which physical panel is on the board's output side and which is chained. The firmware habitat origin (0 or 64) is chosen from the panel-order test, never from a guess.

## Before the first power-up

- [ ] Read the adapter label and the Interstate 75 W product page for its power limits and recommended power arrangement.
- [ ] Photograph the adapter label and the board's terminal labels (VIN/5V, GND).
- [ ] Everything unplugged; check red/black polarity and a common ground across both panels and the board.
- [ ] Inspect leads for exposed copper, loose strands, and crossed joints.
- [ ] Do not hot-plug HUB75 ribbons or power leads. Power down first, always.
- [ ] Back up whatever is on the board (milestone 2, Thonny steps) before changing any file or firmware.
- [ ] Do not drive two panels from the Mac's USB port. A MacBook port can supply the board for programming only, with the panel power rail disconnected from it. Confirm the arrangement for this before you plug the Mac in.
- [ ] Second panel black still draws standby current: include both panels in every current reading.
- [ ] Have a way to cut power instantly (switched socket or unplugging at the wall, not at the board).

## Test order (milestone 2, each step needs your go-ahead)

1. Board alone over USB: identify the RP2350, back up files, verify `import interstate75` and display dimensions.
2. One sparse pixel at 0.10 software scale, one panel connected.
3. Sparse panel-order markers; choose habitat origin.
4. Black reserved half confirmed; one short idle clip.
5. Idle, then sleep and morph locally; record current at each step.
6. All packed assets uploaded if free space allows (480,480 bytes needed plus headroom).
7. One-hour soak at the approved limits.

Never run full-white, strobing, or full-panel test patterns.

## Software limits in force

| Limit | Value | Source |
| --- | --- | --- |
| Habitat size | 64 x 32 at origin 0 or 64 | `shared/limits.json` |
| Max distinct lit habitat pixels | 281 | enforced by packer, tests, firmware |
| RGB scale (hard max) | 0.10 (100 permille) | clamped in firmware, not raisable remotely |
| Speed range | 0.5x to 1.0x | `shared/limits.json` |
| Reserved panel | always black | renderer tests, all frames, both origins |

The channel-weighted aggregate frame budget will be calibrated against your measured current. Until you provide measurements the firmware budget stays at the conservative default and is documented as uncalibrated.
