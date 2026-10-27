# Changelog

> [中文](CHANGELOG.md) · **English**

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

---

## Unreleased · README above-the-fold rework

- **Added a "Quick reference" block** (both languages): a 9-row field table, two conversion
  formulas, and the two traps people hit first (sticks reach only 86 % of the range; the device
  must be activated once). The motivation was concrete: someone writing a bridge or a driver opens
  the repo wanting to know how to turn `0x31` into g, not how rigorous we are. The old first screen
  was all methodology — you had to scroll past eight "core facts" to reach a field table.
- The block **points rather than duplicates**: every row links to the matching section in
  `docs/protocol.en.md` or `docs/discovery-imu.en.md`.
- `0x11`–`0x1F` is now marked as not covered, rather than letting the table imply completeness.

## v1.0 · 2026-10-25

First proper release. Compared with the earlier drafts, **one core fact was overturned and one
boundary was redrawn.**

### New findings

- **All 29 trailing bytes of `0x05` are accounted for**: a 4-byte microsecond timestamp starting at
  `0x2B`, temperature at `0x2F` (`25 + raw/126.9` °C), and a 6-axis IMU at `0x31`–`0x3C`. `0x05` can
  now be read as a complete telemetry frame.
- **The built-in IMU is calibrated**: accel ±8 g, gyro ±2000 dps, right-handed, Z = face normal,
  Y along the long axis toward the USB connector. Six-face method gives per-axis gains of
  4090.8 / 4090.7 / 4096.3 LSB/g, mean **4092.6 (0.08 % below nominal)**; after tilt correction the
  three axes agree to **0.14 %**. Z's zero offset was cross-checked using the fact that an offset
  pushes both opposite faces the same way.
- **The IMU is available from `0x05` alone** — `0x09` is not required. This overturns the implicit
  premise that "IMU needs write access".
- **Activation mechanism decoded**: commands go over the `MI_01` vendor interface; activation is a
  one-shot switch. Software sends 19 subcommands; `0x0A`/`0x04` (report mode and feature mask) decide
  the content, `0x0D` initialises USB.
- **Host-side cross-check** ([Protocol §3](docs/protocol.en.md)): an SDL mapping string exported from
  Steam decodes into the GUID structure (bus / CRC16 / VID / PID / version / driver signature), and
  every button was cross-checked against our bitfield — `paddle1/paddle2` independently confirm the
  GL/GR back buttons exist; also confirms **ZL/ZR are axes, not buttons in SDL**, `back` is Minus
  (not Capture), and `SL/SR` are unmapped. Two exports are **byte-identical** (374 B / 30 fields) —
  but only because SDL normalises its output (canonical keys alphabetical, extension keys appended),
  not because the device is stable.
- **Steam normalises the sticks (measured)** ([Protocol §2.1](docs/protocol.en.md)): pushing the left
  stick in three stages gives raw travel 435 / 944 / 1605 → Steam displays ~10000 / ~20000 / 32767.
  A ×16 linear map is ruled out; normalisation holds (implied full travel ≈1696 counts, matching our
  measured 1605–1719). **This narrows our own claim**: 0.86 only affects raw 12-bit readers — through
  Steam Input, full deflection is 1.00. Also confirmed that page shows **pre-deadzone** values, so the
  8192 deadzone still cannot be verified from it.
- **Gyro integral vs accelerometer: flips about Y** ([IMU §5.2b](docs/discovery-imu.en.md)): four flips
  give ratios 1.080 / 0.995 / 1.027 / 1.029, weighted 1.028 → implied LSB 16.85; with §5.2's
  16.44/16.35 the four estimates span **16.35–16.85 (16.384 ±3 %)**. The honest reading: not off by a
  factor of two, but not pinned to 0.1 % either. Also confirms gyro Y and accelerometer Y are the same
  axis (ay net change ≤784 LSB vs ax/az 3,400–7,600 during flips).
- **External support for gyro noise and bias**: idle σ = 1.97 / 1.30 / 1.03 LSB (0.120 / 0.079 /
  0.063 dps), the same order as the ±0.1 dps Steam's "Gyro Calibration" page shows — independent support
  for LSB = 16.384. That page displays **residual after bias subtraction** (otherwise X would sit at
  +0.5 dps), i.e. Steam applies the same correction our table does. **This also retracts our own
  "bias is negligible"**: 0.49 dps integrates to 29.7 deg/min, so implementations must subtract it.
- **A read-only version identifier**: `bcdDevice = 0x0201` (hidapi `release_number`), corroborated by
  bytes `[12:14]` of the SDL GUID. It is **not** the firmware version string shown in the Switch UI
  (public notes tag HIDMaestro's unit as `1.1.5`), and `data/DEVICE.md` spells out the difference.

### Corrections (including retractions)

| Former claim | Status |
|---|---|
| `0x05` **streams on power-up with no handshake** | **Wrong.** Opening a HID handle yields 0 frames; the device must be activated once by the host, after which it runs at 250 Hz |
| "The read-only probe works standalone" | **Incomplete.** Reading is genuinely zero-write, but the **trigger** depends on the Steam client activating the device (login screen suffices, no sign-in needed) |
| "The `0x09` IMU needs write access" | **Wrong.** The IMU is right there in `0x05` |
| "`0x23+` is unresolved / safe to ignore" | Fully resolved, see above |
| "Z's +73 offset is tilt folded into the zero point" | **Wrong** (a draft-era error). Corrected it grows to +102, and it predicts the six-face magnitudes 1.025 / 0.975 g |

### Engineering

- **Read-only boundary redrawn**: the 3 experimental scripts that do write are quarantined in
  [`tools/write/`](tools/write/); `audit_readonly.py` now judges **by zone** — a write call in the
  read-only zone fails the check, the write zone is listed but not judged. `hid_caps.py` and
  `hid_descriptor.py` now open handles **read-only** instead of read+write.
- 11 new tools (7 for the IMU pipeline, plus a USBPcap parser, an environment gate, a hotplug watcher
  and a HID descriptor reader).
- 7 new data files (including a 20,001-frame A/B, a 5,000-row formal calibration, and a full hotplug
  trace).

### Documentation

- `docs/protocol.md` §1.4 rewritten from "suspected IMU" into a field table; new §1.5 "Activation".
- New `docs/discovery-imu.md` (zh/en): how the discovery happened, the method, and a post-mortem of
  three wrong attributions.
- `data/DEVICE.md`: Hong Kong model, two-hub topology, 2026-10-25 timeline, activation precondition.
- **Fixed a post-hoc attribution**: `docs/discovery-imu.md` §8.4 used to say "the reason we started at
  all" was ndeadly's field table marking everything after `0x23` as unknown — which contradicts §5.1
  ("we had not seen that document when we did the calibration"). The real order: internal process
  (you may not write "ignore" without falsifying it) drove the work to completion, and `hid_reports.md`
  was read afterwards, when preparing the issue. Rewritten, with the contradiction spelled out.
  This matters because "independent verification" is one of the few load-bearing claims here; getting
  the order backwards voids it.
- **Dependency boundary made explicit**: `docs/boundaries.md` §2.2 now states that what came from prior
  work is only *where the fields are* (structure), while *how they behave over time* is all measured.
- **`commands.md` re-checked verbatim**: the 8-byte command header and the four key subcommands all
  match — `0x03/0x0A`=Select input report, `0x0C/0x02`=Set feature mask, `0x0C/0x04`=Enable features,
  `0x03/0x0D`=Initialise USB (annotated "Required before the controller will send input reports over
  USB"). Three places stated more than the source does and were tightened: the Command ID range is now
  "enumerated in the doc", `0x5` regained its `/ACK` half, and `63 bytes` is marked as **our
  arithmetic** (the document states no length).
- **Wrong labels in the capture timeline fixed**: names like "handshake" and "HOME LED" came from the
  **Switch 1** protocol and do not apply here (`data[0]` is a Command ID, not a Switch 1 report ID).
  All entries now read `cmd 0x0X / sub 0x0Y` with the document's own name; where the doc says
  `Unknown`, we leave it blank.
- **New counter-evidence from our capture**: `commands.md` lists `0x03/0x03 = Enable USB HID reports`,
  which by name looks like the master switch — but **it never appears in our capture**. Steam sends
  only `0x03/0x0A` and `0x03/0x0D`, and the stream starts anyway. So it is not a necessary condition;
  `0x03/0x0D` is, matching the document's own note.
- **Retracted a fabricated quotation (important)**: eight places (4 Chinese, 4 English) described
  `hid_reports.md` as marking the IMU axis orientation and sign convention "to be determined
  empirically" — two of them in quotation marks or blockquotes. Checking the source: **that document
  contains no sentence about axis orientation or sign conventions at all**; the line was a retrieval
  summary mistaken for a quotation. All eight now make a plain statement ("gives only the data type
  and range ... does not record which direction each axis points or what the sign means") without
  quote marks. The conclusion — that this is our increment — still holds, but the argument now rests
  on our own observation rather than on an alleged gap in their text. The same error is in the already
  published upstream issue #2 and must be fixed by hand.
- **§2.3 now states which code is being compared**: `firmware/esp32s3_switch2_bridge/` is marked by its
  author as historical reference only, and the shipping product is the pure-software v2.0. The text
  read as a comparison against "their current implementation" when it actually compares the 2026-05
  ESP32 firmware. The stick-normalisation item moved from "difference flagged" to "suggestion
  withdrawn" — v2.0 fixed it independently (keeping the controller's own calibration), and our quote
  came from archived code. The unverified escape hatch is recorded as well.
- `docs/boundaries.md` gains §2.3: field-by-field comparison with the BLE-side project
  `XinHeLianSheng-Pro2-Bridge` (report layout / IMU sample order / microsecond timestamp / button bit
  order all match), plus a note on its 4095-based stick normalisation; also rewords one claim — the
  firmware version is not "unreadable", it is "unreadable over the read-only HID channel".
- `docs/boundaries.md` gains §2.1 "Why 'no prior record found' is not 'first on the internet'":
  four structural blind spots (NDA work, private communities, naming/PID differences, and the limits
  of our own search), plus why the repo refuses to write "first discovered".
- New `CITATION.cff` and this changelog.
- All relative links and bilingual pairs verified (the counts change as content is added; check the
  numbers at the time of your own run).

### Upstream

- IMU axis mapping and sign convention submitted to
  [`ndeadly/switch2_controller_research` issue #2](https://github.com/ndeadly/switch2_controller_research/issues/2).

---

## Early drafts (2026-10-24 and before, unpublished)

The bulk of the charging-protocol work (clock wrap constant, status bitfield, full charging cycle,
reading semantics, stick range, rumble A/B) was produced here, with 7 self-retractions along the way.
Evidence for each is in [`docs/daylog-2026-10-24.md`](docs/daylog-2026-10-24.md).
