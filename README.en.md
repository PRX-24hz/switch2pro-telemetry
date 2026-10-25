# Switch 2 Pro Controller (`0x057E:0x2069`) · USB `0x05` Report Field Notes

**Read-only reverse engineering: frame layout · time base · full charging cycle · gauge semantics · built-in 6-axis IMU**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Read-only](https://img.shields.io/badge/access-read--only-brightgreen.svg)](#read-only-guarantee)
[![Device](https://img.shields.io/badge/device-057E%3A2069-blue.svg)](#)
[![Version](https://img.shields.io/badge/version-v1.0-informational.svg)](CHANGELOG.md)

> [中文](README.md) · **English** · **v1.0 (2026-10-25)**

Every conclusion below comes from **captures on real hardware** (20+ hours, 400k+ frames),
not from second-hand documentation.

The probes under `tools/` are **read-only, non-exclusive, and never send a single byte to the
device** — verifiable with `tools/audit_readonly.py`. The few experimental scripts that *do* write
are quarantined in [`tools/write/`](tools/write/) and reported separately by the audit — mix them in
and "read-only" becomes a slogan nobody can check.

Scope: **a single unit, Hong Kong model `BBE-008`, firmware as of 2026-10-25 (build number not
recorded)** (see [`data/DEVICE.md`](data/DEVICE.md)), stock cable + two chained external hubs +
Windows 11. Behaviour may differ across firmware or hardware revisions.

---

## What this is

How far the `0x05` report can be pushed **without writing to the device**. The short answer:
**this one frame is enough for most purposes.**

- **Quantified**: link clock (including the 23.86-minute wrap constant), six charge-status values,
  the full charging cycle timeline, actual stick travel range, the power cost of rumble, and the
  **built-in 6-axis IMU's range / axis mapping / zero offsets**
- **Refuted**: the widely-repeated three-stage charging state machine, converting the gauge field into
  a percentage via a Li-ion curve, "`0x05` only carries buttons/sticks/battery", and "it streams on
  plug-in with no handshake"
- **Still not achievable**: a real battery percentage (the field is not a voltage), the `0x09` report's
  0–9 battery levels, NFC, the SPI calibration block

---

## Eight core facts

| # | Fact | Strength |
|---|---|---|
| 1 | `0x05` is **64 bytes at 250 Hz (4 ms)**; one frame carries buttons / sticks / gauge / microsecond timestamp / temperature / **6-axis IMU** | Solid |
| 2 | **Opening the device ≠ receiving data**: **0 frames** while inactive; after host activation it goes **straight to 250 Hz** with no ramp, and keeps streaming after the activating software exits | Solid (hotplug + process A/B) |
| 3 | Clock = **32-bit millisecond counter**, wraps at **1,431,655.765 ms** (= 2³² ticks @ 3 MHz); time base measured at **+10 ppm** | **Strongest** (10+ predictions hit, error ≤12 ms) |
| 4 | Status byte is a **bitfield**: b5 = external power present, b2 = charging current flowing, b4:b3 is **not** a monotonic stage index | Medium (all 6 values covered; the stage hypothesis was refuted by our own data) |
| 5 | Charging does not end in a static state: **8.8 h of "2.9 Hz chopping maintenance" → 10 min of real charging → done** | Solid (9 consecutive hours overnight) |
| 6 | The reading is **not a voltage** (only ≈3670–3728 when full) and oscillates **±10 with a 40–60 ms lag** behind the chopping | Solid (15,001-frame lag experiment) |
| 7 | **The sticks only use ~86–88 % of the 12-bit range** (radius 1,765 / 1,810; raw HID cannot reach 0 or 4095). **Steam/SDL normalises this to full scale**, so it only affects those decoding raw bytes | Solid (7,750 frames + a 3-point Steam cross-check) |
| 8 | The trailing 12 bytes are a **complete 6-axis IMU**: accel **±8 g**, gyro **±2000 dps**; after six-face calibration the three axes agree to **0.14 %** | Solid (six faces + angular-rate integration, independently matching the upstream nominal) |

> Fact 2 was only nailed down on 2026-10-25, and it overturns our own earlier "streams on power-up".
> Fact 8 likewise kills the premise that "IMU requires `0x09`" — **plain read-only polling of `0x05`
> gives you the IMU.**

## One-line model

```
plug in → 0x34 fast charge ──→ 0x3C (10 s) ──→ 0x20 idle / slow decay (hours)
                                                   │
                                                   ↓ ~8.8 h
                                       0x00/0x24 chopping (2.9 Hz, duty → 90%)
                                                   │
                                         ┌─────────┘
                                         ↓ 7 min "churn"
                          0x24 → 0x34 (4 ms) → 0x2C (440 ms), 38 cycles
                                         ↓
                          0x34 full-power recharge ~10 min → 0x3C → 0x20
```

**The red LED follows `0x34` only.** It is **off** during both `0x20` and the chopping maintenance
phase — so the LED does *not* indicate "is external power connected".

---

## Retracted conclusions (if you read an older version)

| Former claim | Status |
|---|---|
| `0x20` never occurs / the second-hand docs are wrong | **Wrong.** `0x20` = charge complete, observed many times |
| `0x20` is an absorbing state, only discharge exits it | **Wrong.** Unplugging exits it immediately |
| `0x2C` = initial plug-in handshake | **Wrong.** It appears third in the insertion sequence |
| b4:b3 is a monotonic stage counter | **Does not hold.** Observed `0→2→1→2` |
| The reading is systematically ~20 lower while `0x00` | **Does not hold.** It is a sawtooth; the sign flips with sampling phase |
| Chopping converges to 100 % and becomes `0x20` | **Wrong direction.** It reverses into a full-power recharge |
| `0x00` duty ≥ 75 % means "full" | **Downgraded.** It measures "fraction of time not charging", not fullness |

Evidence for each retraction, and why we got it wrong at the time, is in
[`docs/daylog-2026-10-24.md`](docs/daylog-2026-10-24.md) (Chinese; English summary in §A).

---

## Who this is useful for

| Your situation | Value |
|---|---|
| Long-running HID reader (driver, overlay, pad tester, latency measurement) | **Essential**: without wrap handling you will report ≈**357,900 lost frames** every 23.86 min |
| Stick input mapping / deadzone / response curve | **Essential**: normalizing by 4,095 leaves the stick at **0.86** at full deflection — "it never reaches the edge" |
| Motion / orientation / shake detection, without installing a driver | **Usable**: `0x05` carries the full 6 axes (±8 g / ±2000 dps); read-only polling is enough, **no `0x09` needed** |
| Battery display, but you **cannot or will not write** to the device | **Usable**: four states + raw reading; no real percentage |
| You already write to `iface1` for `0x09` | **Low**: `0x09` gives 0–9 levels directly; just tolerate the `0x3C` transient |
| You only want a battery percentage | **Not possible**: the field isn't millivolts, and the low end is unanchored |
| Reverse-engineering methodology / continuing the work | **High**: the layer breakdown and open questions are a roadmap |

> Premise: **nothing here is "better" — it is "what you can still get when you must not write".**

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/protocol.md`](docs/protocol.md) · [EN](docs/protocol.en.md) | Frame layout, Session Clock and wrap discriminator, button bitfield, stick range, activation, SDL mapping cross-check |
| [`docs/charging.md`](docs/charging.md) · [EN](docs/charging.en.md) | Six status values, full cycle timeline, churn, LED semantics, replug, rumble A/B |
| [`docs/gauge.md`](docs/gauge.md) · [EN](docs/gauge.en.md) | Why the reading is not a voltage, the chopping sawtooth, prohibited uses |
| [`docs/implementation.md`](docs/implementation.md) · [EN](docs/implementation.en.md) | State classifier pseudocode, six defensive rules, unit-test fixtures |
| [`docs/boundaries.md`](docs/boundaries.md) · [EN](docs/boundaries.en.md) | Protocol-stack layers, solved / open questions, prior art, citation rules |
| [`docs/discovery-imu.md`](docs/discovery-imu.md) · [EN](docs/discovery-imu.en.md) | **Side discovery**: `0x05` carries a full 6-axis IMU (±8 g / ±2000 dps); calibration and the activation caveat |
| [`REPRODUCE.md`](REPRODUCE.md) · [EN](REPRODUCE.en.md) | Cross-device reproduction guide (4 hypotheses in 30 minutes) |
| [`docs/daylog-2026-10-24.md`](docs/daylog-2026-10-24.md) | Research log: 7 self-retractions, 7 tool bugs, evidence per claim |

---

## Quick start

```bash
pip install hidapi

# 0. Prerequisite: the device must have been "activated" once, or you read 0 frames (protocol §1.5)
#    Quickest way: launch Steam once (the login screen is enough), let it see the controller,
#    then quit it completely. The stream does NOT stop when Steam exits — activation is one-shot.
python tools/probe_env.py 6                # self-check: only 0x05, 250 Hz, az ≈ +1 g

# 1. Grab 4 frames and dump the fields
python tools/probe_switch_pro.py

# 2. Sample continuously to CSV (one row per second)
python tools/probe_switch_pro.py --watch 600 --csv sw2.csv

# 3. IMU: six-face calibration + segmentation + gyro integration
python tools/imu_calib.py 100 --csv imu_calib.csv
python tools/imu_segments.py  imu_calib.csv    # split idle platforms vs motion events
python tools/imu_gyro_fit.py  imu_calib.csv    # integrate angular rate -> range and sign

# 4. Let another device reproduce it (judges 4 hypotheses, emits JSON)
python tools/repro_capture.py --minutes 30 --fw "<firmware version>"

# 5. Prove read-only access
python tools/audit_readonly.py
```

Tools fall back to a local `_pylibs` directory if present, but the repo ships **no prebuilt binaries**.

---

## Read-only guarantee

Avoiding writes is not fastidiousness — every write path has an **irreversible failure mode**:

| If we wrote | Consequence |
|---|---|
| SPI commands | A bad write to the stick calibration block → permanent drift |
| Firmware / OTA | Bricked device in the worst case |
| `0x09` init sequence | Changes the report mode, and fights Steam/SDL for the same device |
| Rumble / LED output | Overrides whatever the user currently has |

```bash
python tools/audit_readonly.py
# read-only zone: 21 Python files
# -- write zone (quarantined, informational) --
#   tools\write\replay_activation.py  -> 5 write calls
#   tools\write\send_activation.py    -> 1 write call
#   tools\write\send_ctrl.py          -> 8 write calls
# [PASS] no write-to-device API found in the read-only zone.
# [NOTE] 14 write calls live in tools/write/, quarantined, excluded from the verdict.
# interfaces used (read-only zone): h.close, h.open_path, h.read, hid.device, hid.enumerate
```

The audit **judges by zone**: any write call in the read-only zone fails the check; `tools/write/`
is listed but not judged. That makes "read-only" an executable check rather than a self-declaration.

**The boundary has three layers:**

| Layer | Writes? | Note |
|---|---|---|
| this repo, `tools/` | no | pure read-only probes, auditable |
| this repo, `tools/write/` | **yes** | 3 experimental scripts that tried to activate the controller themselves; all failed; quarantined |
| Steam client | **yes** | it performs the activation (**the login screen is enough, no sign-in**); we also observed Steam Input rewriting the player LED |

So the accurate statement is: **the data here was obtained read-only, but the "device was activated"
step was not ours.** When the LED changes, the user cannot tell which piece of software did it.

---

## Data and tools

```
data/
├── DEVICE.md                            # device, firmware, topology, capture timeline
├── sw2_charge.csv                       # first full charging cycle (4,918 rows)
├── apex_ab_2026-10-25.csv               # rumble on/off A/B (per-minute metrics)
├── loadtest_2026-10-25.csv              # four-game load segments
├── wrap_capture_2026-10-24.txt          # wrap captures + the 1.2 s anomaly experiment
├── imu_ab_2026-10-25_static_shake_static.csv   # still/shake A/B (20,001 frames; establishes the IMU)
├── imu_calib_2026-10-25.csv             # first six-face calibration (Steam on)
├── imu_calib_2026-10-25_steam_off.csv   # retest (Steam off)
├── imu_ax_faces.csv                     # both X faces, re-measured
├── imu_spin_2026-10-25.csv              # slow spin about vertical (first try, messy segmentation)
├── imu_spin2_2026-10-25.csv             # four flips about Y, gyro vs accelerometer
├── stick_full_right_2026-10-25.csv      # stick pushed in 3 stages (raw vs Steam display)
├── imu_formal_2026-10-25.csv            # formal run (100 s / 7 poses; source of the README and the issue)
├── steam_off_verify.csv                 # continuous check that the stream survives Steam exiting
└── hotplug_steam_off.csv                # full hotplug (unplug / replug / 63 s of silence / activation)
```

```
tools/                                  # all read-only
├── probe_switch_pro.py                 # read-only probe (250 Hz / CSV / sampling)
├── probe_env.py                        # environment gate: interface, report IDs, rate, az≈1 g
├── play_monitor.py                     # during-gameplay monitor (input rate / duty / slope / stick travel)
├── replug_probe.py                     # first-frame capture on replug + duty tracking
├── stick_range.py                      # full stick travel (hardware limit vs in-game deadzone)
├── measure_tick.py                     # time-base regression (ppm / tick frequency)
├── wrap_watch.py                       # sit-and-wait wrap capture (250 Hz, two-way cross-check)
├── repro_capture.py                    # cross-device reproduction: 4 hypotheses in one run
├── log_status_transitions.py           # status transitions + heartbeat (duty, cumulative skew)
├── switch2_battery_state.py            # state classifier (with CSV replay)
├── imu_tail_probe.py                   # per-frame capture of the trailing 29 bytes
├── analyze_imu_ab.py / imu_pairs.py    # still/shake statistics (16-bit pair decomposition)
├── imu_calib.py                        # long pose captures (absolute wall clock, line-buffered)
├── imu_segments.py                     # 0.25 s median binning -> idle platforms / motion events
├── imu_events.py                       # per-event extremes + cross-product rotation axis
├── imu_gyro_fit.py                     # integrate angular rate / rotation angle -> range and sign
├── imu_hotplug_watch.py                # hotplug watcher (reconnects on disconnect)
├── parse_usbpcap.py                    # DLT_USBPCAP parser (no Wireshark needed)
├── hid_caps.py / hid_descriptor.py     # report lengths and descriptor (opened read-only)
└── audit_readonly.py                   # read-only audit (zone-based, CI-friendly)

tools/write/                            # WARNING: writes to the device; quarantined, don't run
├── send_ctrl.py                        # one report via control transfer (all rejected)
├── send_activation.py                  # one report via hid.write (returns -1)
└── replay_activation.py                # replay the activation sequence over 16 report IDs (all failed)
```

---

## Status and limitations

- **Single unit, single firmware** (Hong Kong `BBE-008`, build number not recorded). Every "constant
  across devices" claim is unverified.
- **The reading's unit is undetermined**: we only proved it is *not* a voltage, not *what* it is.
  An external voltage reference is required.
- **The 86 % stick figure may be unit-specific**: read it as "you must calibrate, never assume full
  scale", not as a model spec.
- **3 MHz is a numerical fit**, not firmware evidence; strictly speaking only the *ratio*
  of modulus to divider is pinned.
- **All captures come from an already-activated device**: activation was done by the **Steam client**
  (the login screen suffices, no sign-in needed, and the stream survives quitting it); this repo does
  not implement activation (see [`tools/write/`](tools/write/)). Unplugging reverts to the inactive state.
- **IMU figures come from hand-placed poses**: no fixture, residual tilt 0.03°–3° per pose; the gyro is
  only calibrated at ±2000 dps (**no saturation test**); mounting angle cannot be separated from
  placement error.
- **Untouched**: command/response protocol, SPI calibration block, firmware OTA — all require writes.

---

## Acknowledgements, limitations and collaboration

**Prior work**: the report ID and field offsets build on the following public reverse-engineering
efforts. Without them we would not even know which bytes to read:

- `ndeadly` (`switch2_controller_research`) — field tables for `0x05` / `0x09` and the first read on the status byte;
- `kennethreitz` (`switch2bridge-macos`) — USB/BLE init sequences and `PROTOCOL.md`;
- `dekuNukem` (the gen-1 Pro protocol) — pioneer on report layout and button bitfields;
- `darthcloud/BlueRetro #1249` — cross-check on composite interfaces and enumeration;
- the Linux `hid-nintendo` driver and the initial Switch 2 driver merged in 7.4, plus `HIDMaestro`
  and the SDL/Steam implementations — the "official path via `0x09`" against which this repo's
  read-only substitute is bounded.

The clock-wrap constant, status bitfields, full charging cycle, reading sawtooth, stick range,
the rumble A/B and the six-face IMU calibration were measured independently for this repo.

**Giving back upstream**: `hid_reports.md` marks the IMU axis orientation and sign convention as
"to be determined empirically". We determined it, and submitted the result to
[`ndeadly/switch2_controller_research` issue #2](https://github.com/ndeadly/switch2_controller_research/issues/2)
with the six-face raw data for cross-checking. That thread also records how we briefly retracted the
conclusion and then restored it through controlled experiments.

**On "who was first"**: we **cannot confirm, and do not claim**, that we are the first to record
these phenomena. This repo consistently writes "**no prior record found**", never "first discovered"
— the latter is not falsifiable and should not be asserted by the author.
This **cannot be settled by searching harder**: NDA-bound internal work, private-community discussion,
and the same analysis filed under a different repo name or PID all sit structurally outside public
search; our own pass covered only English/Chinese and a limited set of terms.
Full note in [`docs/boundaries.en.md` §2.1](docs/boundaries.en.md); if you know of an earlier public
record, please open an issue and we will add the citation.

**Known engineering limitations** (these narrow the conclusions' scope — please read):

- **n=1**: a single unit on a single firmware (version TBD). Every "constant across devices" claim is unverified;
- **the reading's unit is undetermined**: we only proved it is *not* a voltage, not *what* it is;
- **the 86 % stick figure may be unit-specific**: read it as "you must calibrate", not a model spec;
- **3 MHz is a numerical fit**: strictly, only the *modulus/divider ratio* is pinned;
- **no firmware read, no SPI read, no `0x09`**: all of those require writes, outside the read-only boundary.

**We welcome help**: a second unit to reproduce (30 minutes, see [`REPRODUCE.en.md`](REPRODUCE.en.md)),
data from a USB power meter, a sample on a different firmware, or any improvement to the docs or the
algorithms — please open an issue or send a PR. That is the only way to upgrade n=1 into a
"model-level fact".

---

## Citation and license

Conclusions come from a single unit. When citing, please include **firmware version + topology +
the raw CSV**, not just the conclusion. See the citation rules in
[`docs/boundaries.en.md`](docs/boundaries.en.md); machine-readable metadata is in
[`CITATION.cff`](CITATION.cff).

© 2026 **PRX-24hz** · Licensed under the [MIT License](LICENSE).
Version history in [`CHANGELOG.md`](CHANGELOG.md).

> Disclaimer: independent reverse-engineering research, not affiliated with Nintendo.
> All trademarks belong to their respective owners. The data is a snapshot of one device on one
> firmware revision and may change across revisions.
