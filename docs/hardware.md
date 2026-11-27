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

## What the manufacturer says (read 2026-11-25 from the Pimoroni product page, not independently verified)

- RP2350A, 4 MB QSPI flash, 520 KB SRAM, Wi-Fi/Bluetooth module; screw terminals for powering the LED panels; USB-C for programming and power.
- "It's powered via USB-C, which should also be able to power a few connected panels happily, assuming you're not planning anything too eye-bleedingly bright." That is a qualitative claim, not a current rating. The page does not say whether the screw terminals share the USB-C rail or what current is safe.
- Source: https://shop.pimoroni.com/products/interstate-75-w . API reference used for the scripts: `micropython/modules_py/interstate75.md` in pimoroni-pico (`Interstate75(display=...)`, `.display`, `.update()`, `DISPLAY_INTERSTATE75_64X32`, `DISPLAY_INTERSTATE75_128X32`).

## Facts established from your photos (2026-11-25)

- **Adapter:** the black cube is the Raspberry Pi 27 W USB-C Power Supply UK (model label, P2525), captive USB-C cable. Label outputs: 5.1 V 5.0 A (25.5 W), 9 V 3.0 A, 12 V 2.25 A, 15 V 1.8 A. It will only leave 5.1 V if the load does not negotiate a higher PD voltage; the Interstate 75 W is not documented as a PD device, so I expect 5 V, but I have not measured it. A 5 A rating is what the supply can offer into a fault, not what the board or its wiring is rated for.
- **Board terminals:** two screw terminals; the top one is silkscreened `5V` and carries both red leads, the other carries both black leads. Its label is hidden by the lugs, but as the second terminal of the pair it is ground. Ring lugs are stacked two per screw.
- **Wiring as found:** one red/black pair per panel, ending in each panel's white 4-pin power connector. After your change the connectors are unplugged from the panels and the board is detached from the HUB75 header, so the leads are live at the free connector ends whenever the board is powered.
- **HUB75 chain:** ribbon joins the two panels; the unused header on the end panel is silkscreened `JOUT_HUB75B`, so the board belongs on the other panel's free (input) header, where it originally sat.
- **Still unconfirmed:** red lands on `VCC` and black on `GND` at each panel's 4-pin header (needs a legible close-up of each header's silkscreen), the current the panels draw, and whether the board's 5 V rail is isolated from USB VBUS.

## Observations from the powered-up photos (2026-11-25, still not electrical proof)

- **Panel 1 power plug:** the white 4-pin plug sits on the header silkscreened `VCC VCC GND GND`, with red on the two `VCC` positions and black on the two `GND` positions, so polarity looks right. Whether the plug is fully seated cannot be judged from the angle of the photo.
- **HUB75:** you report the board is on `JIN`. Photo shows the panel's other header, silkscreened `JOUT`, empty, which is consistent.
- **Driver chips:** the small chips near the power header (`UR5`/`UR6`/`UB6`) carry what looks like an `FM` logo, which would be Fuman Microelectronics, but the part number is not readable in the photo. Some Fuman drivers (FM6126A) need an initialisation step that the default Interstate 75 setup skips, leaving the panel black. **Not confirmed.**
- **Outcome so far:** stage 1 (value 24) and stage 4 (2 x 2 block at 96) were run on adapter power and **nothing visible was seen on the panel**. The board's status LED worked throughout.
- **What stage 4 actually showed (chained config, one panel):** two white dots low on the panel, and, after another attempt, a full-length green line along one long edge, i.e. a whole row of pixels at the panel's edge, lasting about 5 s (phone photo). Not the 2 x 2 block I intended. My explanation, not yet confirmed: a 128-wide chain into a 64-pixel panel. The panel does respond, so power, the HUB75 link and the data path work at some level.
- **Resolved:** single-panel variant 1 (official default, no FM6126A init) shows the stage 4 block in the middle of panel 1, so the earlier stray dots and green row came from the 128-wide config on one panel, not a bad panel or wiring.
- **Housekeeping:** panel 2's unplugged power connector was lying live on panel 1's back; keep it clear of everything.

## Powering two panels: research (2026-11-26, vendor pages and forums, not measured here)

- Pimoroni's original Interstate 75 page says USB-C gives up to 3 A, enough for one 64x64 panel or smaller, and that for more power you inject 5 V at the screw terminals. The I75 W page is looser ("a few panels", "not eye-bleedingly bright"). https://shop.pimoroni.com/en-ch/products/interstate-75
- Pimoroni's panel listing rates a 64x32 panel at 5 V, 4 A maximum with all LEDs on. https://shop.pimoroni.com/products/rgb-led-matrix-panel
- Forum builders with two panels use an external 5 V 4 A supply for the panels and the board, cutting the +5 V wire in the USB cable so USB carries data only. https://forums.pimoroni.com/t/interstate-75-with-multiple-hub-75-led-matrix-panels/21397/18
- A forum answer attributed to Pimoroni engineers: power the matrix from the external supply and leave the board's 5 V disconnected from the matrix; ground is shared through the HUB75 cable. This is forum advice, not product documentation, so the brief's "two supplies only if the manufacturer explicitly permits" still needs the owner's decision. https://forums.pimoroni.com/t/interstate-75-power-supply-question/18422
- HUB75 current is spiky and displays get erratic below about 4.5 V (hzeller wiring guide). https://raw.githubusercontent.com/hzeller/rpi-rgb-led-matrix/master/wiring.md
- A software colour or brightness limit cannot help with the power-up surge, because it happens before any code runs.

## Comparison with Pimoroni's "Getting started with Interstate 75" tutorial (2026-11-26, text pasted by the owner)

- **Same as ours:** board on the first panel's data-in, grey ribbon from that panel's data-out to the second panel's data-in, one red/black 4-pin lead per panel (red VCC, black GND) landing on the board's screw terminals (red +, black -), USB-C to the board. Display configuration follows the default `Interstate75(display=...)`, with `stb_invert=True`, `panel_type=PANEL_FM6126A` and `color_order=...` only as troubleshooting options.
- **Not the same:** the tutorial's starter kit uses two 128 x 64 panels; these are marked 64 x 32 (P6). Same chain, smaller panels.
- **The tutorial's own warning matches the symptom:** "If your panels are in need of a power supply upgrade you might see dimness, glitching, flickering or find your Interstate 75 is constantly rebooting." Its remedy: power the board and panels from an external 5 V supply on the screw terminals (it suggests a barrel-jack supply with a screw-terminal adapter). It also says USB powers "a couple of panels" for modest draw and that panels "can consume up to 4 amps". It advises an external supply, or disconnecting panel power, while programming from a computer.
- **Cheapest test before buying anything:** a different USB-C charger (5 V 3 A or better) with both panels, cold start. Recorded as a hardware test in `docs/test-log.md`.

## Before the first power-up

Step-by-step instructions are in `docs/hardware-proof.md`.


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
| RGB scale (hard max) | 0.20 (200 permille, max channel 51 of 255); was 0.10 until 2026-11-26. Proof stages 1 to 3 keep their own fixed ceiling of 26 | clamped in firmware, not raisable remotely; the 2x step has no current measurement behind it |
| Speed range | 0.5x to 1.0x | `shared/limits.json` |
| Reserved panel | always black | renderer tests, all frames, both origins |

The channel-weighted aggregate frame budget will be calibrated against your measured current. Until you provide measurements the firmware budget stays at the conservative default and is documented as uncalibrated.
