# Protocol · `0x05` frame layout, clock and input

> **English** · [中文](protocol.md)

> Frame structure, Session Clock and its wrap, button bitfield, stick travel and range.

> Back to [README](../README.en.md) · Chinese version [`protocol.md`](protocol.md)

---

## 1. Frame layout, clock and buttons

### 1.1 Frame layout

Fixed 64 bytes; `buffer[0]` is report ID `0x05` followed by a 63-byte body; **250 Hz (4 ms/frame)**.

> **But "opening the device" is not "receiving data".** Open a HID handle and you get zero frames; the
> device must first be **activated once** by the host. After that the stream keeps running at 250 Hz
> even if the activating software has exited — see §1.5. This was only nailed down on 2026-10-25; the
> earlier "streams on plug-in" wording was wrong.

> ⚠️ Offsets are counted on the **buffer including the report ID**, i.e. **+1** compared to the
> body offsets used in community docs. This is the easiest place to be off by one.

| Offset | Len | Type | Field | Notes |
|---|---|---|---|---|
| `0` | 1 | u8 | Report ID | Always `0x05`; drop the whole frame otherwise |
| `1` | 4 | u32 **LE** | Session Clock | Link millisecond counter, +4 per frame; **wraps every 1432 s** (§1.2) |
| `5` | 4 | u8×4 | Buttons | Bitfield, see §1.3 |
| `11` | 3 | 12bit×2 | Left Stick | `LX=b0\|((b1&0x0F)<<8)`; `LY=(b1>>4)\|(b2<<4)` |
| `14` | 3 | 12bit×2 | Right Stick | Same packing; **resting centre ≠ 2048** (observed up to +117 off) |
| `0x20` | 2 | u16 **LE** | Gauge Reading | **Dimensionless gauge value** (≈3670–3728 when full, not a voltage) |
| `0x22` | 1 | u8 | Charge Status | See [Charging §1.1](charging.en.md) |
| `0x23+` | 29 | — | **Trailing telemetry**: timestamp + temperature + 6-axis IMU | see §1.4 |

### 1.2 Clock: 250 Hz, wrap, and distinguishing a "reset"

- **Semantics**: milliseconds since this USB link was established; returns to zero across replug.
- **Wrap constant**: `2³² ticks @ 3 MHz = 1,431,655.765 ms` (23.86 minutes).
  It is not any 2ⁿ milliseconds (2³² ms = 49.7 days, 2²¹ ms = 35 minutes — neither fits).
- **Time-base accuracy**: least squares over 658 s / 330 points → `Δdevice/Δhost = 1.0000101`,
  i.e. **+10 ppm**; physical period 1,431.641 s. Crystal-grade, ruling out "period drift".

**Predictability**: the constant was used to make a prediction first, then a 250 Hz watcher was
parked on the wrap point —

```
predicted  1,431,655.765 ms
observed   1,431,650 / 1,431,652 / 1,431,651 …   error −5.8 / −3.8 / −4.8 ms
one full night: 22 wraps, 0 resets
```

**But the absolute instant drifts**: the epoch zero can be reset by a non-wrap event. Observed once:
the counter returned to zero at `12:44:10.6` while the predicted point was `12:44:09.39` (**+1.2 s**),
with the time base already verified at ±10 ppm — so it cannot be a frequency error.

**Mandatory implementation rules**:

1. Always treat `clock <= prevClock` as an epoch boundary; **never** extrapolate from
   "wall clock + period".
2. **Never subtract unsigned values directly** — after a few hours the lost-frame count explodes.
3. The discriminator depends on **sampling density**:

```
per-frame (250 Hz):   wrap zero-point deviates from 1,431,65x by >1 s  →  reset
sparse (30 s beat):   prev_clock + interval ≥ 1,431,655.765  →  wrap fell inside the gap (normal)
                      otherwise, if the clock shrank      →  a real reset
```

> Our own audit script once applied the first rule to 30-second heartbeats and misclassified a
> normal wrap as a reset. Sparse sampling must use the second rule.

### 1.3 Button bitfield (1 = pressed)

| byte | 0x80 | 0x40 | 0x20 | 0x10 | 0x08 | 0x04 | 0x02 | 0x01 |
|---|---|---|---|---|---|---|---|---|
| `[5]` | ZR | R | SL-R | SR-R | A | B | X | Y |
| `[6]` | — | C | Capture | Home | LS | RS | Plus | Minus |
| `[7]` | ZL | L | SL-L | SR-L | Left | Right | Up | Down |
| `[8]` | — | — | — | Headset | — | — | GL | GR |

Sticks **must not be normalized by an assumed full scale**: measured resting centres are
`(2040,2048)` / `(2127,2163)`. Accurate calibration requires the SPI calibration block
(which means writing to the device). **Use the raw 12-bit values plus a deadzone in your UI, and
do not claim "calibrated".** See §2 for how much of the range is actually reachable.

### 1.4 The trailing 29 bytes: timestamp, temperature, 6-axis IMU

These 29 bytes were once labelled "unparsed / safe to ignore". On 2026-10-25 a **still-vs-shake A/B**
plus a **six-face calibration** accounted for every one of them:

| Offset | Len | Type | Field | Conversion / note |
|---|---|---|---|---|
| `0x23`–`0x29` | 7 | u8 | Reserved | constant `0x00` |
| `0x2A` | 1 | u8 | Flag | constant `0x01`, meaning unknown |
| `0x2B` | 4 | u32 **LE** | Timestamp | **microseconds**; independent of host clock, +3750 or +5000 per frame |
| `0x2F` | 2 | int16 **LE** | Temperature | `T[°C] = 25 + raw / 126.9` |
| `0x31` | 12 | int16×6 **LE** | Accel X/Y/Z + Gyro X/Y/Z | see below |
| `0x3D`–`0x3F` | 3 | u8 | Reserved | constant `0x00` |

IMU conversion uses the **measured** calibration, not nominal values:

```
0x31:0x32  ax   a[g]   = (raw - 10.5)  / 4090.8
0x33:0x34  ay   a[g]   = (raw +  5.2)  / 4090.7
0x35:0x36  az   a[g]   = (raw - 102.3) / 4096.3     <- face normal
0x37:0x38  gx   w[dps] = (raw - 8)     / 16.384
0x39:0x3A  gy   w[dps] = (raw - 3)     / 16.384
0x3B:0x3C  gz   w[dps] = (raw - 7)     / 16.384

Range: accel +/-8 g      gyro +/-2000 dps
Bias: **do subtract it**. Left in, gx accumulates at 0.49 dps = **29.7 deg/min** (axes: 29.7 / 12.1 / 23.7)
Frame: right-handed; Z = face normal (+1 g lying face up); Y along the long axis, toward USB
```

**So `0x05` is a complete 6-axis telemetry frame** — buttons, sticks, gauge, timestamp, temperature and
IMU all in one report, all reachable by read-only polling. `0x09` is not required.

> How this was established, the six-face calibration, and why the data was briefly retracted and then
> restored: [`discovery-imu.en.md`](discovery-imu.en.md).
> The axis-orientation item is not recorded upstream (only the data type and range are); our result was submitted
> to `ndeadly/switch2_controller_research` (issue #2) for cross-checking.

### 1.5 Activation: why "opening the device" is not enough

`open` the device and `read`, and you get **0 frames**. Not packet loss, not rate negotiation — the
device simply never started sending.

| Observation | Result |
|---|---|
| Enumerate while inactive | Normal: Windows sees a game controller, PnP all green |
| `read` while inactive | **0 frames**, no report ID at all |
| Press buttons while inactive | Does not wake it; still 0 frames |
| After being activated by a host | **Straight to 250 Hz**, no ramp, no intermediate state |
| Close the activating software afterwards | **Stream continues** (250.2 Hz measured after Steam fully exited) |
| Unplug and replug | Back to inactive; needs activating again |

So activation is a **one-shot switch**, not an ongoing negotiation. The commands go over the `MI_01`
**vendor** interface, **not** the HID interface `MI_00` — which is why nothing sent at the HID layer gets
through. Command sequence and semantics: [`discovery-imu.en.md` §8.1](discovery-imu.en.md).

> **Constraint this puts on the repo**: every capture here comes from an already-activated device; the
> activation was done by external software (Steam, as measured) and the tools only read. That is not a
> defect, it is a **stated precondition** — without it, anyone reproducing the work gets 0 frames and
> concludes the device or the code is broken.

**The activation path we actually measured is Steam — and it does not need a login:**

| Step | Result |
|---|---|
| Steam fully exited + replug the controller | **0 frames** |
| Launch Steam, **sit on the login screen, do not sign in** | The controller is taken over (LED on), **stream jumps straight to 250 Hz** |
| Quit Steam | Stream continues, still 250.2 Hz |

"Taken over at the login screen" narrows it down by half: the takeover happens **before** any sign-in,
so what drives it is Steam's **local HID / controller service**, not the account-level Steam Input
configuration.

State what was **not** tested too, so this doesn't get read as "only Steam can activate":

- **Untested**: whether other software (SDL games, `HIDMaestro`, the Linux `hid-nintendo` driver) can
  activate it. Upstream notes say SDL's Switch 2 driver also sends the start-up commands on `iface1`,
  so claiming Steam is the *only* activator would be an overreach;
- **Untested**: whether disabling "controller support / Steam Input" in Steam's settings still results
  in a takeover. **That toggle was not found in the current Steam build** (possibly removed, or hidden
  per device), so this one cannot be verified for now;
- **Untested**: whether behaviour differs across Steam versions. **This is the ceiling on
  reproducibility** — the activation step hangs off a self-updating third-party client.

---

## 2. Sticks: measured travel and range (12-bit unpacking verified)

The Apex firing range was the first time the sticks left the centre (all earlier data hovered
between 2040 and 2168):

| Axis | Observed range | Span | Midpoint |
|---|---|---|---|
| LX | 390 ~ 3,719 | 3,329 | 2,054 |
| LY | 563 ~ 3,582 | 3,019 | 2,072 |
| RX | 568 ~ 3,722 | 3,154 | 2,145 |
| RY | 616 ~ 3,797 | 3,181 | 2,206 |

- **Positive result**: across a span of 390–3,800 the values are **continuous, jump-free,
  left/right symmetric and axis-independent** → the 12-bit unpacking in §1.1
  (`x = b0 | ((b1 & 0x0F) << 8)`, `y = (b1 >> 4) | (b2 << 4)`) is **verified correct**.
- **But 0 / 4,095 were never reached.** To separate "hardware limit" from "in-game deadzone",
  a full-travel capture was then taken in **raw HID with no game running**
  (`tools/stick_range.py`, 7,750 frames; resting midpoints L(2061,2068) / R(2159,2152)):

| Axis | Min | Max | Span |
|---|---|---|---|
| Left X | 431 | 3,780 | 3,349 |
| Left Y | 571 | 3,581 | 3,010 |
| Right X | 558 | 3,674 | 3,116 |
| Right Y | 386 | 3,762 | 3,376 |

  **Maximum deflection radius** (relative to the measured midpoint): left **1,765**,
  right **1,810** counts — i.e. **86.2 % / 88.4 %** of the theoretical 2,047 radius,
  with **no axis reaching an endpoint**.

- **Conclusion: this is a real mechanical/firmware limit, not an in-game deadzone.** Three reasons:
  1. In raw HID (no game involved) full physical deflection still cannot reach the endpoints;
  2. The in-game range (390–3,722) and the raw-HID limit (431–3,780) are **almost identical**,
     so the game was not compressing travel — the earlier "81.3 %" figure *is* the hardware limit;
  3. Left and right radii are close (1,765 vs 1,810, 2.5 % apart), consistent with a
     **circular trajectory of uniform radius**, rather than per-axis deadzone anisotropy
     (left Y spans only 3,010 yet its composite radius is still 1,765).

- **Engineering implication (important)**: **never normalize by 0–4,095 or ±2,048.**
  With full-scale mapping, a user pushing the stick all the way only reaches **0.86**, which shows
  up as "the stick never reaches the edge / turning feels sluggish".
  Calibrate the measured **radius** instead (1,770–1,810 here, left and right may differ),
  or read the SPI calibration block (requires writes, outside the read-only boundary).
  **Use the radius rather than per-axis span for normalization**: per-axis span is affected by
  mechanical tolerances (left X 3,349 vs left Y 3,010), while the radius is the stick's true
  reachable distance.

---

### 2.1 Steam / SDL normalises the sticks (measured)

Pushing the left stick right in three stages while recording both the raw value and Steam's
"Test Input" readout (`data/stick_full_right_2026-10-25.csv`, resting centre `LX=2065`):

| Raw travel (LX−2065) | Steam display | Counts per unit |
|---|---|---|
| 435 | ~10000 | 23.0 |
| 944 | ~20000 | 21.2 |
| 1605 (full) | **32767 (max)** | 20.4 |

**A plain ×16 linear map is ruled out**: `(raw−2048)×16` would give 7232 / 15376 / 25952 at those
points, nowhere near the readings. **The normalisation hypothesis holds**: Steam maps "fully
deflected" onto full scale, implying it assumes a full-scale travel of ≈ **1696** counts — consistent
with our measured 1605 (this run) / 1719 (earlier `stick_range` runs).

**This narrows the scope of §2:**

| Reader | Value at full deflection |
|---|---|
| raw 12-bit `0x05` (this repo's warning applies here) | **0.86** |
| through Steam Input / SDL | **1.00** (normalised to the measured maximum) |

So "the stick never reaches the edge" only bites when you decode the bytes yourself; Steam users never
see it. The docs previously omitted this layer, which invites reading 0.86 as universal.

> **On Steam's default deadzone of 8192**: if that page showed post-deadzone values, 27 % travel
> (435/1605) minus 25 % (8192/32767) would leave 2.8 %, i.e. a reading near 900 — but the measured
> value was 10000, about 27 % of full scale. So **the page shows pre-deadzone values**, the deadzone
> cannot be verified from it, and it stays an open item.

---

## 3. The host's view: what an SDL / Steam mapping string tells you

Steam's "Controller Layouts" UI can export an SDL mapping string (captured from a Steam user on
2026-10-25). It is not documentation — but it *is* a **machine-readable assertion written by the driver
authors**, and it cross-checks our bitfield reading.

### 3.1 The GUID carries more than VID/PID

```
030056fb7e0500006920000001026800
```

| Bytes | Value | Meaning |
|---|---|---|
| `[0:2]` | `03 00` | bus = **0x0003 = USB** (Bluetooth would be 0x0005) |
| `[2:4]` | `56 fb` | CRC16 of the device name = `0xfb56` (self-consistent with the trailing `crc:fb56`) |
| `[4:6]` | `7e 05` | vendor = **0x057E** |
| `[6:8]` | `00 00` | — |
| `[8:10]` | `69 20` | product = **0x2069** |
| `[10:12]` | `00 00` | — |
| `[12:14]` | `01 02` | **version = 0x0201** |
| `[14]` | `68` | driver signature `'h'` (HIDAPI) |
| `[15]` | `00` | driver data |

The `0x0201` at `[12:14]` is not noise: reading the same device's `release_number` via
`hid.enumerate()` gives **0x0201** — the `bcdDevice` in the USB descriptor. Two independent paths agree.

> **Why it matters**: `bcdDevice` is a **read-only version identifier** (hidapi exposes it as
> `release_number`), available without sending any command. It is not the same as the "controller
> firmware version" string shown in the Switch UI, but it is enough to tell whether two units are the
> same build. Recorded in [`../data/DEVICE.md`](../data/DEVICE.md).

**Determinism**: two exports from the same device (2026-10-25, ~6 minutes apart) are **byte-identical** —
374 bytes, 30 fields.

Note *why* they match: **SDL normalises its output**; it is not that the device reports in a stable
order. The 20 canonical keys are strictly alphabetical (`a, b, back, dpdown, …, x, y`), with the four
extension keys `misc1/misc2/paddle1/paddle2` appended at the end.

So the string works as a **device fingerprint** (Steam keys controller layouts by this GUID, so the same
unit on another machine still hits the same config) and as a **golden value for regression tests**
(change the driver and the string changes). But it must **not** be read backwards as "the device behaves
very stably" — that is a question about frame data, not about this line of text.

### 3.2 Button cross-check: what lines up, what does not

| SDL mapping | SDL's name | Our bitfield | Note |
|---|---|---|---|
| `a:b0` `b:b1` `x:b2` `y:b3` | face buttons | `[5]` 0x08/0x04/0x02/0x01 | all four present |
| `leftshoulder:b9` `rightshoulder:b10` | L / R | `[7]` 0x40 / `[5]` 0x40 | — |
| `lefttrigger:a4` `righttrigger:a5` | **ZL / ZR** | `[7]` 0x80 / `[5]` 0x80 | **SDL treats them as axes, not buttons** |
| `back:b4` `start:b6` | **− / +** | `[6]` 0x01 / 0x02 | SDL's `back` is Minus, not Capture |
| `guide:b5` | Home | `[6]` 0x10 | — |
| `leftstick:b7` `rightstick:b8` | stick click | `[6]` 0x08 / 0x04 | — |
| `paddle1:b13` `paddle2:b14` | **back paddles** | `[8]` 0x02 / 0x01 = **GL / GR** | independent confirmation these two exist and work |
| `misc1:b11` `misc2:b12` | unnamed | candidates: `[6]` 0x40 (C), `[6]` 0x20 (Capture), `[8]` 0x10 (Headset) | **untested** — needs one-press-per-button |
| `dpup:h0.1` `dpdown:h0.4` `dpleft:h0.8` `dpright:h0.2` | D-pad | `[7]` 0x02/0x01/0x08/0x04 | different bit order; the driver reorders |

**Three traps:**

1. **ZL / ZR are axes, not buttons.** They map to `a4`/`a5`, i.e. SDL treats them as analog. In our
   `0x05` bitfield they are two bits (0x80). We *infer* the driver synthesises a 0 / full axis pair from
   the digital value — unverified.
2. **`back` is Minus, not Capture.** By SDL convention `back` usually means Select/View; here it is `−`.
3. **`SL` / `SR` (rail buttons) are not mapped at all.** They occupy four bits in our bitfield
   (0x20/0x10 in `[5]` and `[7]`), but in the Pro Controller form factor SDL ignores them — suggesting
   those bits only matter in rail/detached mode.

Also `hint:!SDL_GAMECONTROLLER_USE_BUTTON_LABELS:=1` is the Nintendo-specific **label-inversion** fix:
the physically bottom-right button is printed "A", but positionally it is the "confirm on the right"
slot. The hint makes SDL map by **position**, not by the printed letter.

### 3.3 What this string does **not** contain

It describes buttons and axes only — **no gyroscope or accelerometer**. SDL exposes sensors through a
separate API that never appears in the mapping string.

So it cannot replace the IMU fields in `0x05` (§1.4): for motion, you still decode `0x31`–`0x3C` yourself.
