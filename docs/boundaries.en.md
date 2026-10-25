# Boundaries · scope, open questions and prior art

> **English** · [中文](boundaries.md)

> Which layer of the protocol stack this covers, what is solved, what is still missing,
> and why these findings were not recorded before.

> Back to [README](../README.en.md) · Chinese version [`boundaries.md`](boundaries.md)

---

## 1. Boundaries and open questions

### 1.1 Which layer of the protocol stack this covers

```
L0  Report byte layout and field semantics   ← main battleground
L1  Report timing / hardware time base       ← touched (3 MHz / 2³² overflow, predicted and hit)
L2  Command-response protocol (bulk iface1)  ← untouched, requires writes
L3  SPI flash (calibration / serial)         ← untouched, requires writes
L4  Firmware / OTA                           ← untouched, requires writes and is irreversible
```

**If you have write access, go straight for `0x09`** (it has 0–9 battery levels, IMU, NFC) — do not
copy this repo's duty-cycle workaround. Every battery conclusion here is a **substitute solution
under the "must not write" constraint**.

### 1.2 Solved

| Question | Answer |
|---|---|
| Lost-frame count explodes on long runs | 1432 s clock wrap, not packet loss ([Protocol §1.2](protocol.en.md)) |
| How to judge "full" read-only | Only `0x20`; duty cycle can only judge "degree of maintenance" ([Implementation §1.1](implementation.en.md)) |
| Can the reading be used as a voltage | No ([Gauge §1.1](gauge.en.md)) |
| What is `0x3C` | Pre-completion transient, a stable 10.0 s ([Charging §1.2](charging.en.md)) |
| Does chopping maintenance end by itself | **Yes**, it wraps up after 8 h 46 m ([Charging §1.2](charging.en.md)) |
| Does restoring power start charging immediately | Depends on how depleted it is ([Charging §1.5](charging.en.md)) |
| Does high load affect charging decisions | No, and maintenance draws no battery ([Charging §1.6](charging.en.md)) |
| What are those 29 trailing bytes | Microsecond timestamp + temperature + **6-axis IMU** ([Protocol §1.4](protocol.en.md), [IMU](discovery-imu.en.md)) |
| Why does opening the device yield no frames | It needs **one host-side activation**; afterwards the stream survives software exit ([Protocol §1.5](protocol.en.md)) |
| Does the IMU require writing to the device | **No** — `0x05` carries all six axes ([IMU](discovery-imu.en.md)) |

### 1.3 Unsolved

| # | Question | What is needed |
|---|---|---|
| 1 | Is the wrap constant identical across devices / firmware | A second unit → see [`REPRODUCE.md`](../REPRODUCE.en.md) (30 min to decide) |
| 2 | Is 3 MHz really the hardware time base | Firmware dump / datasheet |
| 3 | Does chopping really correspond to current on/off | **USB power meter (sample rate ≥10 Hz)** |
| 4 | The scale between the reading and real voltage | Multimeter / power meter |
| 5 | What the gauge field actually is | `0x09` (write access) or the BLE channel |
| 6 | Is the `0x09` IMU timestamp on the same time base | Write access |
| 7 | Does `0x20` exist on other firmware | Multiple firmware samples |
| 8 | The recharge threshold (what reading triggers charging) | Keep it plugged in until it fires. **Load ruled out**: Apex at 47 % button activity plus continuous rumble, reading down to 3,550, still did not trigger ([Charging §1.7](charging.en.md)) |
| 9 | Is the full-deflection radius constant across devices (left 1,765 / right 1,810 — unit-specific or universal) | A second Pro 2 running `tools/stick_range.py` |
| 10 | Can rumble intensity be graded (only on/off was tested here) | A game with graded rumble + stepped tests |
| 11 | The **report ID** of the activation commands is unresolved | USBPcap 1.5.4 **does not record the SETUP stage**, where the report ID lives in `wValue`; needs Bus Hound or a newer USBPcap |
| 12 | Can activation be done in user space | Needs a WinUSB binding on `MI_01` (Zadig/libusb) — i.e. installing a driver, outside this repo's boundary. All three HID-layer attempts failed (see [`tools/write/`](../tools/write/)) |
| 13 | IMU chip model and mounting angle | Datasheet + a fixture; hand placement only resolves to 0.03°–3°, which cannot separate them |

> Item 3 is the best value for money: a cheap power meter upgrades "chopping = current on/off" from
> correlation to direct measurement, and simultaneously gives the reading a voltage scale —
> all without violating read-only.

### 1.4 Citation requirements

Conclusions come from **a single unit**; the firmware version must be copied by hand, see the record
sheet at [`data/DEVICE.md`](../data/DEVICE.md). When citing, include
**firmware version + topology + `data/sw2_charge.csv`**, not just the conclusion.

---

## 2. Prior art

Three communities have worked on this area, but **their capture durations** meant they could not see
several of the conclusions here:

| Community | Representative work | Typical duration | Could they see the 1432 s wrap? |
|---|---|---|---|
| Protocol RE | dekuNukem (gen 1), ndeadly (field tables), kennethreitz (init) | seconds to minutes | **No** (their USB sample is 499 report transitions ≈2 s) |
| Kernel drivers | `hid-nintendo`; the initial Switch 2 driver merged in Linux 7.4 | long-running, but timestamps come from host `ktime` | **No** (the device's millisecond field is not used as a time base) |
| Device emulation | HIDMaestro (firmware **1.1.5**), SDL/Steam side | 8-second smoke tests | **No** (they only need to emit a frame every 4 ms) |

**Search status (2026-10-24)**: queries combining `1,431,655` / `1431655` / "0x05 clock wrap" found
**no public source discussing this wrap or this constant**. This repo therefore consistently writes
"**no prior record found**" rather than "first discovered" — the latter is not falsifiable and should
not be asserted by the author.

**One public statement to reconcile**: `switch2bridge-macos` records "byte-0 counter increments by 1
per report". If that refers to `0x05` over USB, it conflicts with this repo's "the first 4 bytes are
a millisecond clock, +4 per frame". The likely explanation is that they counted the 8-bit counter of
`0x09` on the BLE side, but **this has not been confirmed with the author** and is listed as an open item.

### 2.1 Acknowledgements

The report ID and field offsets build on public reverse engineering by `ndeadly`, `kennethreitz` and
`darthcloud/BlueRetro #1249`; the clock wrap, status bitfields, full charging cycle, reading sawtooth
and the six-face IMU calibration were measured independently for this repo.

**Giving back**: `hid_reports.md` marks the IMU axis orientation and sign convention as "to be
determined empirically"; we determined it and submitted the result as
[`ndeadly/switch2_controller_research` issue #2](https://github.com/ndeadly/switch2_controller_research/issues/2)
with the raw six-face data. The activation command sequence is likewise read from that repo's
`commands.md` — we only verified it independently (capture + line-by-line cross-check), we did not
reinvent it.
