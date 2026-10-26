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

### 2.1 Why "no prior record found" is not "first on the internet"

The sentence above ("no prior record found") reads easily as "we were first". **Those are very
different claims**, and the gap is not one that more searching can close. Four kinds of record sit
structurally outside public search:

| # | Why it cannot be found | Can it ever be closed |
|---|---|---|
| 1 | **Work under NDA**: devkits go out to studios and accessory partners before launch, so the protocol has very likely been analysed already — just never published | structural, never |
| 2 | **Private communities**: mainboard and protocol talk in Discord / Telegram / small forums is not indexed, and can easily predate any public repo | structural, never |
| 3 | **Naming and PID differences**: the same analysis may live under another repo name, inside an issue or PR (`hid-nintendo`, SDL, Joy-Con RE branches), and engineering samples may use a **different PID** — searching `057E:2069` simply misses them | methodological; improvable, not guaranteed |
| 4 | **The boundary of our own search**: one pass on 2026-10-24, mostly English and Chinese, with terms built around `1,431,655` / `0x05` / `clock wrap`. Japanese blogs, unindexed forums, and write-ups that use completely different words (say, just "controller battery") are out of view | **our own shortcoming — must be stated** |

The first two are unfalsifiable, so they **cannot be used as evidence** — only as a reason not to
assert. The third is a search method that can be improved. The fourth is our own limit.

**So the policy does not change**: the repo writes "**no prior record found**", never "first
discovered". This is not politeness — the payoff of the "first" label is close to zero while the cost
is real: it ties a falsifiable factual claim to the whole document, and a single counterexample then
makes everything else read as suspect. What deserves citation is the method, the data and the
reproducibility, not a timestamp.

> If you know of an earlier public record, please open an issue. **Proving us wrong is more valuable
> than confirming we are right** — the former makes this document accurate, the latter only makes it
> look good.

### 2.2 Acknowledgements

The report ID and field offsets build on public reverse engineering by `ndeadly`, `kennethreitz` and
`darthcloud/BlueRetro #1249`; the clock wrap, status bitfields, full charging cycle, reading sawtooth
and the six-face IMU calibration were measured independently for this repo.

**Giving back**: `hid_reports.md` marks the IMU axis orientation and sign convention as "to be
determined empirically"; we determined it and submitted the result as
[`ndeadly/switch2_controller_research` issue #2](https://github.com/ndeadly/switch2_controller_research/issues/2)
with the raw six-face data. The activation command sequence is likewise read from that repo's
`commands.md` — we only verified it independently (capture + line-by-line cross-check), we did not
reinvent it.

### 2.3 A BLE-side implementation: complementary, and mutually verifiable

[`LeonChrome/XinHeLianSheng-Pro2-Bridge`](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge)
(C# / Apache-2.0, since 2026-05, ~78 stars) does the **other half**: it connects the Pro2 over **BLE**
to Windows and presents it as a virtual USB pad (Pro1 / Xbox / PS5). This repo does **USB read-only
observation**; the two do not overlap, yet its virtual Nintendo report layout matches our measurements
**field for field**.

**Three independent agreements** (they do not cite us, and they started earlier):

| Item | Their implementation | This repo, measured |
|---|---|---|
| Report layout | buttons `5/6/7/8`, left stick `11..13`, right stick `14..16` | identical ([Protocol §1.1](protocol.en.md)) |
| IMU sample | 12 bytes: accel first at `+0/+2/+4`, gyro at `+6/+8/+10`, int16 LE | identical (`0x31`–`0x3C`) |
| Timestamp | 4 bytes LE, **microseconds** | identical (`0x2B`–`0x2E`) |
| Button bit order | in their `fd2` bitmap `C=0x4000`, `GR` before `GL`, the four SL/SR bits skipped | bit-for-bit identical to §2.2 |

> **Why this matters here**: this repo measured the layout **first and found that project later**.
> The order is what counts — it means the agreement is not copying, but two measurements of the same
> hardware. It also confirms §2.1 again: we are not first; someone was already handling this same
> motion data in 2026-05.

**Two differences worth flagging** (not nitpicking — it saves the next reader some time):

1. **Stick normalisation**: they use `(value − 2048) / 16`, clamped to ±127, i.e. assume full scale
   `0..4095`. With our measured radius (1,765 / 1,810) full deflection only reaches **≈110/127**, i.e.
   **86 %**. That is exactly the trap [Protocol §2](protocol.en.md) describes; their v2.0 notes show
   they fixed "stick range" for Pro1 mode, in the same direction.
2. **Firmware version**: they can display it (read via the command channel). Which tells us something —
   the firmware version is **not unreadable, it is unreadable over the read-only HID channel**; sending
   subcommand `0x02` on the activation channel (`MI_01`) gets it. That is why
   [`data/DEVICE.md`](../data/DEVICE.md) uses `bcdDevice = 0x0201` as a *substitute*, worded as
   "readable read-only", never as "the only thing readable".

