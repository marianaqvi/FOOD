# Hardware proof (milestone 2): exact steps

Status: **nothing here has been run on hardware.** I have not touched the board, downloaded firmware or flashed anything. Every step below is yours to run, and every result goes into `docs/test-log.md` as measured, never assumed.

Rules that apply to all of it:

- Never hot-plug the HUB75 ribbon or any power lead. Power off and unplug first, always.
- Do not flash or overwrite anything on the board until the backup in Part B exists.
- Never run full-white, flashing or full-panel patterns. The scripts here light at most 4 pixels.
- Software scale 0.10 is a conservative default, not a measured electrical limit.
- If anything looks wrong (more lit LEDs than expected, flicker, heat, smell, adapter noise, board resetting), unplug at the wall, not at the board.

I will not treat a physical step as cleared until you reply in chat with the confirmations listed at the end of each part.

## Part A: on the Mac, nothing connected to the board

1. **Install Thonny** from https://thonny.org (you install it; I have not downloaded anything). Optional later: `python3 -m pip install --user mpremote` if you want a command line copy tool. Not needed for these steps.
2. **Take photos** and keep them somewhere I can read (drop them into `reference/`):
   - the Raspberry Pi 27 W adapter label, readable, showing every output profile (V and A);
   - both sides of the Interstate 75 W, especially the screw terminals and their silkscreen (`+`/`-`, `VIN`, `5V`, `GND`);
   - where the red and black leads start and end, one clear photo per joint.
3. **Read** Pimoroni's page for the board: https://shop.pimoroni.com/products/interstate-75-w . It says the board is powered via USB-C, that USB-C "should also be able to power a few connected panels" if not very bright, and that the screw terminals are for powering panels. It does not tell me whether the terminals are tied to the USB-C rail, or what current is safe. I have not verified that, so use the schematic linked on that page, and tell me what you find.

## Part B: board alone on USB, panels disconnected (no lit LEDs possible)

Only the Mac's USB-C lead should reach the board. This stage cannot light a pixel, so the Mac USB port is fine here.

1. Unplug everything: USB, the adapter, any lead to the board. Photograph how the board is connected, then:
   - pull the board straight off the panel's HUB75 input header (no twisting, note which way round it was);
   - loosen the screw terminals and remove any red/black leads from the board, photograph them.
2. Plug a USB-C **data** cable from the Mac into the board. In Terminal:
   ```bash
   ls /dev/cu.usbmodem*
   ```
   A device should appear. If nothing does, the cable may be charge-only, or the board has no MicroPython running yet (that is fine, tell me).
3. Open Thonny, Tools > Options > Interpreter, choose **MicroPython (Raspberry Pi Pico)** (the RP2040 label also covers the RP2350 family), and pick the detected port. **If Thonny offers to install or update MicroPython, cancel.** Do not flash anything.
4. **Back up first.** In Thonny: View > Files. Under "MicroPython device" list what is on the board. Right-click each file or folder > Download to `backups/board-2026-11-25/` in this repo (`backups/` is git-ignored because backups can contain Wi-Fi passwords). If the board is empty, note that. This backs up files, not the firmware image. The firmware can be re-downloaded from Pimoroni, which is why I only need the file backup.
5. **Copy the three files** to the board's root. In Thonny: open the file from the Mac, File > Save as > "MicroPython device", same filename, no folder.
   - `firmware/power.py`
   - `firmware/hwtest_common.py`
   - `firmware/tools/hw00_inspect.py`
6. Open `hw00_inspect.py` on the board and press Run. It prints the MicroPython build, free RAM and flash, the file list, whether `import interstate75` works, which `DISPLAY_INTERSTATE75_*` constants exist, display bounds for single and chained, and the time of an all-black `update()`. It sends black frames only.
7. **Send me the whole printed output.** What I will check:
   - `import interstate75: ok`, and both `DISPLAY_INTERSTATE75_128X32` and `..._64X32` present;
   - `single bounds: (64, 32)` and `chained bounds: (128, 32)`;
   - free flash well above 480,480 bytes (Pimoroni lists 4 MB flash on this board);
   - free RAM, and the black-frame update time.

If `import interstate75` fails: stop. Do not download firmware yet. Send me the output. I will point you to the correct Pimoroni release and ask you before anything is downloaded or flashed.

**Result (2026-11-25):** Part B is done and logged in `docs/test-log.md`. The board is the Pimoroni build (MicroPython 1.25.0-preview), the backup of all 20 files is verified, and both display sizes exist. Two things learned: open only **one** display per run, and do a soft reset (Ctrl-D at the REPL, or Thonny's Stop) between runs, because a second `Interstate75()` in the same session hung the board until RST. `hw00_inspect.py` now has a `MODE` line (`chained` or `single`) and opens one display per run.

**Confirm in chat before Part C:** backup done (where), hw00 output pasted, board photographed before disconnecting.

## Part C: decide the power arrangement (no panel is powered until this is settled)

Open questions from `docs/hardware.md`, which only you can answer with the unplugged hardware in front of you:

- What do the adapter label and the board's terminals say, exactly?
- Will the panel be powered from the board's USB-C, from the screw terminals fed by the adapter, or some other way? I will not suggest connecting two supplies to one rail unless Pimoroni's documentation explicitly allows that exact arrangement.
- Is red = +5 V and black = GND at every connector, and is ground common between board and panel? Check with a multimeter's continuity/polarity mode only if you have one; otherwise tell me and we will rely on labels and visual inspection, and I will say so in the log.

**Current measurement.** You told me you have no measuring gear, and I am not asking you to buy anything yet. The brief wants measured current, and a single pixel is a negligible extra load, so stages 1 to 3 below do not need it. Before the idle clip and the one-hour soak (hundreds of lit pixels, hours long) I will ask you to decide about an inline USB-C power meter, because at that point the requirement is real. Until then every current cell in the log stays empty, not estimated.

**Confirm in chat before Part D:** adapter label (photo), the power route you intend, polarity checked (how), and which single panel you will connect first.

## Part D: stage runner on adapter power (one panel, then two)

The board has one USB-C port for both power and data, and the panels are powered through its terminals. So tests run on the wall adapter with the Mac unplugged, started by the board's own buttons. On 2026-11-25 three **new** files were written to the board's root (nothing existing was overwritten; names were checked first and SHA-256 verified after): `main.py` (the stage runner, `firmware/tools/stage_runner_main.py`), `power.py` and `hwtest_common.py`. To return the board to stock, delete those three files (I can do that over serial, or Thonny's file view can).

The runner is **not** the player and not the final autoboot. It opens the display once, keeps it black, and does nothing until you do all of this on purpose:

| Gesture | Effect |
| --- | --- |
| Tap **B** | Choose stage 1, 2 or 3 (status LED flashes amber that many times) |
| Hold **A + B** for 3 s | **Arm** (status LED green). Disarms after 60 s, and after every run |
| Hold **A** for 1 s, then release | **Run** the chosen stage, only while armed |
| Any button during a run | **Abort**: panel goes black immediately |
| Hold **B** for 3 s, then release | **Next display variant**, 1 to 8, wrapping. Variants **1-4 are for ONE panel** (single 64x32): 1 generic, 2 FM6126A panel init, 3 inverted strobe, 4 both. Variants **5-8** are the same four setups chained for TWO panels (128x32). Saved to `/panel_variant`, then the board reboots; the LED flashes cyan once per variant number. Default is variant 1. Nothing is lit by this. |

Status LED (on the board, not the panels): dim blue disarmed, green armed, white running, red refused or error. Stages: 1 = one pixel at (32,16), 2 = red/green/blue pixels, 3 = four marker pixels (needs two panels, variants 5-8), 4 = visibility check (below). Stages 1 to 3 use at most 8 pixels with every channel at most 26 of 255 (the 0.10 clamp); the panel is blanked afterwards.

**Stage 4, visibility check (added 2026-11-25).** Stage 1 (channel value 24 of 255) could not be seen on the real panel. At your explicit request stage 4 lights a 2 x 2 block at (31..32, 15..16) with every channel at 96 of 255 for 8 s. It is the only thing above the 0.10 clamp and is bounded separately: at most 4 pixels, each channel at most 96, total of all channel values at most 1200, at most 8 s, only after arming. A 2 x 2 block at 96 is roughly 0.1 A of LED current by my estimate (4 pixels x 3 LEDs x about 7 mA at that duty, assuming about 20 mA per LED at full), trivial next to the supply, but not measured. `power.py` still hard-clamps everything the player will ever draw at 0.10; stage 4 does not change that.

**D0. Dry run with the Mac attached and both panels disconnected (cannot light anything).** Plug the Mac into the board, tell me, and I will watch the serial output while you tap B, hold A+B for 3 s, hold A for 1 s and release, and press a button mid-run. This proves the gestures on the real buttons before any panel is connected.

**D0 result (2026-11-25): done and passed.** Refuse, stage change, arm, run, re-arm and abort all behaved as listed; the status LED needed brighter levels, now fixed. The 60 s arm expiry was not tried on hardware.

**D1. First power-up on the adapter, panel 1 only, nothing lit.**

1. Everything unplugged. **Never connect the Mac and the adapter to the board at the same time.**
2. Plug the board onto panel 1's free HUB75 input header, where it originally sat (the header labelled `JOUT` is an output, not that one). Do not hot-plug it.
3. Plug **panel 1's** 4-pin power connector in, checking red on `VCC` and black on `GND` against that header's silkscreen (send me the close-up photo first). Leave panel 2's connector and the ribbon to panel 2 **unplugged**, and keep panel 2's live connector end on the carpet, apart from everything metal.
4. Wall adapter in the **switched socket, switch OFF**. Plug its cable into the board's USB-C. Then switch ON.
5. Expect: dim blue status LED, panel dark. Keep a hand near the switch. After 30 s, feel the board and panel for warmth. Any heat, smell, buzz or flicker: switch off.

**D1b. Why variant 1 is single-panel (2026-11-25).** The first stage 4 run used a two-panel (128 wide) display on one panel. A chain sends 128 pixels per row; a lone 64-pixel panel keeps only the last 64, so the left-half block never reached it, and stray bits made two dots and a lit edge row. One panel must use variants 1-4.

**D2. Stage 1.** Arm (A+B, 3 s, LED green), then hold A for 1 s and release. Expect exactly ONE dim white LED near the middle of the panel for 10 s, then black. More than one LED, flicker, heat or smell: switch off at the wall. Then stage 2: tap B once, arm, run. Expect red, green, blue left to right. Record what you actually see.

**D3. Both panels.** Switch **off** first, then connect panel 2's power connector and the ribbon (check IN/OUT, see `docs/hardware.md`), switch on. Stage 3: tap B twice, arm, run. Expect 4 pixels in total, a vertical pair in one panel's top-left corner and a horizontal pair in the other's.
   - Panel showing the **vertical** pair is the one you want the sheep on: habitat origin **0**.
   - Panel showing the **horizontal** pair is the one you want the sheep on: habitat origin **64**.
   - A pair in a corner other than top-left means that panel is mirrored or rotated. Tell me; do not try to fix it in the scripts.
   - More than one LED per pixel, or pixels in the wrong rows, suggests a wrong scan configuration. Stop and tell me.

**Send me after Part D:** what you saw per stage, the origin you choose, and anything that felt warm. I record it in `docs/test-log.md` and then write the renderer and player (reserved half black, idle clip, sleep and morph) for the next round.

**D4. If the board's power LED goes dark when both panels are attached (seen 2026-11-26).** Stop retrying. Repeated attempts into a possible short or overload only stress the adapter.
   1. Unplug the adapter from the wall for at least 30 s (a protected supply may stay latched off).
   2. With everything unplugged, photograph both panels' 4-pin plugs on their headers, and the board's two screw terminals with the lugs. Check that red sits on the `VCC VCC` pins and black on `GND GND` on **both** panels, that the plug is not shifted by one position or reversed, and that no strand or lug edge bridges 5V and GND.
   3. Only after that, one single-variable test at a time, always plugging connectors in while the wall switch is **off** and watching the board's PWR LED: (a) board with panel 2 only (panel 1's connector unplugged); (b) panel 1 only again; (c) both. Switch off at the wall at once if the LED goes dark.
   4. A basic multimeter on continuity (nothing powered): `VCC` to `GND` at each panel plug should not beep. Optional.
   5. If panel 2 alone, or both together, still kills the supply while panel 1 alone is fine, that is a measured requirement for a different arrangement (a proper 5 V supply for the panels). Do not buy anything until we have narrowed it down here.

## Part E: animation clips on ONE panel (interim plan while the two-panel power problem is open)

Only panel 1 is connected (power plug and HUB75 on `JIN`); panel 2 is fully disconnected (power plug AND ribbon). Single-panel mode, habitat origin 0, variant 1. First full-frame run: up to 281 lit pixels. The first run was at 0.10 (channel value 24 to 26 of 255); the clip stages now run at 0.20 (channel up to 51), still dimmer than stage 4's 96 but only for a handful of pixels there. Current is still not measured.

1. **Install (Mac attached, panel power plug UNPLUGGED, adapter not connected).** The install adds `/renderer.py`, `/player.py`, `/fallback.py`, replaces `/power.py` and `/main.py` (only after matching the SHA-256 of my earlier installs) and creates `/assets/` with the 18 `.bin` files and `manifest.json` (480,480 bytes, 1,966,080 free). Nothing existing is overwritten without a hash match, and every file is read back and verified. I run this for you from the Mac once you say the board is attached with panel power off.
2. **Power up on the adapter only** (Mac unplugged), board on panel 1's `JIN`. Cyan flashes = variant (expect 1).
3. **Stage 5**: tap B five times (five amber flashes), arm (A + B 3 s, green), hold A 1 s and release. Expect the idle sheep animating for 30 s, then black. Any button aborts.
4. **Stage 6**: tap B once more (six amber flashes), arm, run. Expect sleep once, morph once, then idle, about 20 s.
5. Watch for: heat, smell, flicker, the board's PWR LED dipping, picture tearing, a faint ghost image, wrong orientation. Tell me which way is "up" for the sheep on the panel as it sits.
6. Timing and memory numbers (frames drawn, average and worst draw time, free RAM before and after) are printed on the serial port; I read them if you attach the Mac afterwards with panel power unplugged, and record them in `docs/test-log.md`.

Stop at once and switch off at the wall if anything feels warm or smells.

## Not done yet in this milestone

- `firmware/renderer.py`, `firmware/player.py`, on-device asset upload, memory and timing measurement.
- The aggregate frame budget calibration (needs measured current).
- The one-hour soak.
