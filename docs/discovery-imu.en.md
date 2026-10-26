# Side discovery: the `0x05` report carries a full 6-axis IMU

> ✅ **Verified (2026-10-25 09:22): the `0x05` stream is independent of Steam. Conclusions stand.**
>
> The data here was first captured with Steam Input active, then briefly retracted over
> the suspicion that Steam might interfere. Retest result: with **Steam not running at all**
> (`steam.exe` / `steamwebhelper.exe` both absent), the device still pushes `0x05` at
> **250.1 Hz** (1501 frames / 6 s, 100 % of reports are `0x05`), and the IMU readings match
> this document (flat, raw magnitude `|a| = 1.025 g`; 1.0000 g after removing the +73 LSB
> Z-axis offset). A separate 40-second run gave 2000 samples with zero gaps.
>
> USBPcap further confirmed: report rate constant at **250 Hz, zero jitter**, across a 25 s
> window, with **no `SET_REPORT` at all** — the only HID class requests were two `SET_IDLE`
> calls 0.15 s before the stream started.
>
> Conclusion: **plain read-only USB polling gets you the IMU. No host software, no init
> command.** The earlier "0 frames" state was the device sitting in charge-only mode
> (red LED on, green LED off), unrelated to any control software.
> See [`data/steam_off_verify.csv`](../data/steam_off_verify.csv) and `tools/parse_usbpcap.py`.

> [中文](discovery-imu.md) · **English**

---

> **Not the original goal of this project.** This came out of a 2026-10-25 check meant to
> justify writing "these 29 bytes can be safely ignored" while wrapping up the charging
> protocol work. It is recorded because it changes what this report *is*: `0x05` is not
> "buttons + sticks + battery", it is a **standard 6-axis telemetry frame**.

> Back to [README](../README.en.md) · Protocol layout in [`protocol.en.md`](protocol.en.md)

---

## 0. In one line

Bytes `0x31`–`0x3C` of the `0x05` report are a **3-axis accelerometer + 3-axis gyroscope**,
ranges **±8 g** and **±2000 dps**, little-endian int16, in a right-handed frame shared with
the accelerometer. **Polling `0x05` over USB gets you the IMU — `0x09` is not required.**

---

## 1. Why these 29 bytes got looked at

This is the part most worth writing down — **it wasn't curiosity, it was that the process
wouldn't allow skipping it.**

While writing the protocol doc there is a section on "which fields can be ignored". That
conclusion looks harmless and is actually dangerous:

- If those 29 bytes really are padding, writing "ignore" is correct and saves the reader work;
- If they aren't, writing "ignore" tells everyone downstream to **throw away IMU data**,
  and says so in the tone of "we tested this".

An untested "ignore" and a wrong "ignore" look identical in a document.
So either prove it's blank, or don't write the word.

The check was cheap: **grab 501 frames, count distinct values per byte.** That's how this
started.

### Why "idle `0x20` state" was chosen as the observation condition

That's the device at its least busy: not charging, not rumbling, untouched, red LED off.

The reasoning is direct — **if there is variation even at rest, that's more suspicious, not
less**; conversely if everything is zero at rest, "ignore" has support. The sampling
condition was deliberately chosen to be maximally hostile to the conclusion being tested.

### Result: nearly every byte is moving

| Offset | Idle observation | What could be said at the time |
|---|---|---|
| `0x23`–`0x29` | constant `0x00` | looks like padding |
| `0x2A` | constant `0x01` | constant or flag |
| `0x2B` / `0x2C` | **124 / 244 distinct values** | high-frequency, definitely not padding |
| `0x2D` | `0x9B`–`0x9F` slow drift | slow variable |
| `0x2E` | 6 values (`0x21`–`0x26`) | high byte of a slow variable |
| `0x2F` / `0x30` | only `0x00` / `0xFF` | binary, suspected overflow/sign |
| `0x31`/`0x33`/`0x35`/`0x37`/`0x39`/`0x3B` | tens of values | **non-adjacent, regularly repeating** |
| `0x32`/`0x34`/`0x36`/`0x38`/`0x3A`/`0x3C` | barely change at rest | high bytes? |
| `0x3D`–`0x3F` | constant `0x00` | looks like padding |

The word "ignore" died on the spot.

---

## 2. The first inference, and why it wasn't enough

Seeing "6 odd offsets changing fast, 6 even offsets nearly frozen", the first guess is:
**six 16-bit little-endian readings** — exactly 3 accelerometer axes + 3 gyro axes.

But that inference **did not hold up** at the time, for two hard reasons:

1. **Sensors are noisy even at rest.** A truly stationary accelerometer still flips its
   lowest bit every frame. So "changing at rest" is equally well explained by "this is IMU
   noise floor" and by "this is a counter" — the two are indistinguishable on idle data.
2. **Counters look exactly the same.** Timestamp-like fields also change 100 % of the time
   at rest, and `0x2B`/`0x2C` behaved precisely like that — later confirmed to *not* be a sensor.

In other words: **idle data alone cannot separate "sensor" from "counter".** You need an
independent variable that is absent in the idle state.

That independent variable is **motion**.

---

## 3. Designing an experiment that can falsify

### 3.1 Why "does it change when I shake it" isn't a test

Because "it changes" is not the criterion — a counter changes when you shake it too. The
criterion has to be **a pattern of change that only occurs under motion**.

### 3.2 The chosen criterion: high byte thaws from frozen

For a 16-bit little-endian sensor reading, the low byte is noise-dominated (always
twitching) and the high byte is signal-dominated (rock-steady at rest, only starts flipping
once the magnitude is large enough).

That yields three distinguishable patterns:

| Hypothesis | High byte at rest | High byte while shaking | Low byte at rest |
|---|---|---|---|
| **16-bit sensor** | **nearly frozen** (<5 %) | **flips constantly** (>50 %) | high-frequency |
| Two independent 8-bit fields | independent, no systematic difference | no systematic difference | — |
| 16-bit counter | 100 % changing | 100 % changing (motion-irrelevant) | 100 % changing |

The virtue of this criterion: **it is insensitive to "there is change", and sensitive only
to the distribution of that change.** A counter cannot masquerade as row one.

### 3.3 Protocol

```
0–8 s      controller on the desk, untouched (baseline)
8–61 s     pick up and shake hard (side to side, flip, jitter)
61–80 s    back on the desk, untouched (recovery)
```

Full 250 Hz sampling, **20,001 frames** over 80 s, recording all 29 bytes `0x23`–`0x3F` per frame.

Tools: [`tools/imu_tail_probe.py`](../tools/imu_tail_probe.py); analysis:
[`tools/analyze_imu_ab.py`](../tools/analyze_imu_ab.py), [`tools/imu_pairs.py`](../tools/imu_pairs.py).

---

## 4. Result: criterion holds, six channels hit at once

### 4.1 Per-byte inter-frame change rate (idle → shaking)

| Field | Low byte idle → shake | High byte idle → shake |
|---|---|---|
| ch1 `0x31:0x32` | 75.3 % → 99.7 % | **2.6 % → 53.1 %** |
| ch2 `0x33:0x34` | 75.6 % → 99.5 % | **2.5 % → 51.8 %** |
| ch3 `0x35:0x36` | 79.9 % → 99.6 % | **2.9 % → 51.9 %** |
| ch4 `0x37:0x38` | 65.9 % → 99.6 % | **3.6 % → 69.8 %** |
| ch5 `0x39:0x3A` | 56.6 % → 99.6 % | **3.0 % → 68.9 %** |
| ch6 `0x3B:0x3C` | 70.3 % → 99.6 % | **2.2 % → 70.1 %** |

High bytes sit at 2.2–3.6 % at rest ("essentially frozen") and jump to 52–70 % when shaking
("flips every frame"). **Six for six**, with low bytes twitching throughout — the signature
of a 16-bit sensor.

### 4.2 Standard-deviation amplification (independent second check)

| Channel | Idle σ | Shake σ | Gain |
|---|---|---|---|
| `0x31:0x32` | 448.8 | 2,680.3 | **6.0×** |
| `0x33:0x34` | 424.8 | 2,586.6 | **6.1×** |
| `0x35:0x36` | 622.9 | 3,236.1 | **5.2×** |
| `0x37:0x38` | 544.2 | 5,596.2 | **10.3×** |
| `0x39:0x3A` | 523.2 | 8,392.3 | **16.0×** |
| `0x3B:0x3C` | 320.2 | 6,607.4 | **20.6×** |

### 4.3 The negative control inside the same dataset

In the same capture, `0x2B:0x2C` gives idle σ vs shake σ of **18,910.9 vs 18,918.4 — 1.0×
amplification**. It changes 100 % of frames and does not respond to motion at all — **a
counter, not a sensor**.

That control matters: it shows "numbers move fast when you shake it" is meaningless on its
own, and **only change that responds specifically to motion counts**.

---

## 5. Per-axis calibration: treat it as a part, not a phenomenon

The criterion only answered "it is a sensor". It said nothing about range, axis mapping, or
units. Those need a known input.

### 5.1 Accelerometer: six faces, using gravity as the weight

Gravity is the only free, exact, always-available known quantity. Rest the controller on
each of its six faces in turn, and in each pose gravity lands exactly on ±1 g on one axis.

| Pose | ax | ay | az | \|a\| | measured tilt |
|---|---|---|---|---|---|
| Flat (face up) | +31 | −727 | **+4135** | 1.025 | 10.0° |
| Flat (face up, repeat) | +29 | −733 | **+4132** | 1.025 | 10.1° |
| Face down | −22 | +198 | **−3989** | 0.975 | 2.9° |
| Upright A (USB up) | +32 | **+4083** | +138 | 0.997 | 2.0° |
| Upright B (USB down) | +160 | **−4090** | −152 | 1.000 | 3.1° |
| On edge, +X face down | **+4100** | −101 | +4 | 1.001 | 1.4° |
| On edge, −X face down | **−4080** | +47 | +2 | 0.996 | 0.7° |

The tilt column isn't estimated — it's recovered from the data itself (the accelerometer is an
inclinometer: `acos(dominant / |g|)`), and it's what the gain calculation later divides by.

**Raw magnitudes span 0.975–1.025; all of them return to 1.000 g once offset is removed.**

> **Why is Y ≈ −700 in the face-up row?**
>
> That is ≈ 0.17 g, about 10° of tilt. Six independent placements gave **9.0°, 9.7°, 10.8°,
> 10.9°, 9.98°, 10.07°**, with `ay` negative every single time — the same lean, not sloppy
> placement — so it is **rear housing geometry**: the grips and battery bay hold the PCB tilted
> when the controller rests face-up, whereas face-down it sits on the stick and D-pad and lands
> nearly level (2.9°).
>
> Without the correction the tilt pulls Z's gain ~1 % low (4062 instead of 4096); the table
> below divides it out, so the gains are unaffected. **Axis mapping and signs are never
> affected** — those come from which axis peaks and in which direction, not from magnitude.

This locks three things at once:

1. **Axis mapping**: `0x31:0x32`=X, `0x33:0x34`=Y, `0x35:0x36`=Z;
2. **Range**: at LSB=4096/g the readings land on 1 g; ±4 g (8192 LSB/g) would give 0.5 g
   and ±16 g (2048 LSB/g) would give 2 g — **only ±8 g is self-consistent**;
3. **Physical orientation**: flat gives +1 g on Z and connector-up gives +1 g on Y — both
   locked directly by gravity. X is *not* pinned by labelling a side "left" or "right", but by
   the right-handed constraint (`X = Y × Z`) — see the note below on single-unit ambiguity.

> **Why X is derived, not labelled**
>
> With one unit and no external reference, "which side did I put down" is the only part of the
> procedure that **cannot be checked against the data**. All the data says is: one side down
> reads `+4100` on X, the other `−4080`. Whether that side is physically "left" rests entirely
> on the operator's memory — and memory isn't evidence.
>
> So the X direction is left to the right-hand constraint instead. The cost: if the IMU were
> mounted mirrored on this board, the derivation would be wrong with it. But the three axes
> come out mutually orthogonal with unit magnitude, so a mirrored mount is unlikely.

Sensitivity, from six-face symmetry with offset removed:

| Axis | gain (LSB/g) | vs nominal 4095.875 | offset (LSB) | offset (mg) |
|---|---|---|---|---|
| X | 4090.8 | −0.12 % | +10.5 | +2.6 |
| Y | 4090.7 | −0.13 % | −5.2 | −1.3 |
| Z | 4096.3 | +0.01 % | +102.3 | +25.0 |

Mean **4092.6 LSB/g, 0.08 % below nominal**, inside the ±3 % initial tolerance of MEMS
accelerometers. Feeding the gain and offset back in, every face returns **1.000 g**.

> **Dividing by cos(tilt) is what makes this work.** The same data without that correction
> gives 4090 / 4085 / 4062 — Z drags low and the offset absorbs the difference as if it were
> bias. Corrected, the three axes agree to **0.14 %**, and Z's offset moves from +73 to
> **+102 LSB (25 mg)**. That looks large next to X's +2.6 mg and Y's −1.3 mg, but it is
> independently checkable: a pure zero offset pushes both faces the same way in raw counts, so
> 25 mg of offset should make face-up read 1.025 g and face-down 0.975 g — which is exactly
> what the table shows. So +102 is a real zero-g offset, not tilt folded into the zero point.

> **Independent check against prior work**: `hid_reports.md` gives the nominal
> `8.0/32767` = **4095.875 LSB/g**, derived from the chip datasheet. We hadn't seen that
> document when calibrating, and measured **4092.6** by using gravity on six faces as the
> reference weight — 0.08 % lower. Two unrelated paths landing in the same place means the
> method here is sound.

> **Error budget for hand-placed measurements**: no fixture was used. Residual tilt per pose
> ranged 0.03°–3° (recovered from the table above), and the desk itself reads **−1°** on an
> iPhone level app, so the flat and face-down readings carry an additional ~1° systematic bias.
> **0.14 % agreement is within one session**; expect a few tenths of a percent of
> session-to-session variation on the same unit. Treat the last digit as indicative, not spec.

> The table is a single 100 s session — seven poses at 50 Hz, with the flat pose repeated at the
> end so the repeatability is visible (4135 vs 4132 on Z, 0.07 %). Earlier sessions using the
> same protocol are still in `data/`; they agreed to within ~1 %, the gap coming from looser
> placement before the level app was used.

### 5.1b The same step rules out software interference

The whole six-face routine was repeated in an environment where **Steam was not running at
all**, and every parameter matched:

| Item | Steam on | Steam off |
|---|---|---|
| Flat \|a\| | 1.025 g | 1.025 g |
| ay positive / negative | +4016 / −4089 | +3960 / −4084 |
| az positive | +4138 | +4122 |
| gyro bias gx/gy/gz | 8 / 3 / 7 | 8 / 3 / 6 |

This control was necessary: the original data was captured with Steam Input active and was
briefly retracted over it. The retest shows the IMU fields in `0x05` are independent of host
software. (Bonus: two processes reading the same HID device concurrently do not drop frames —
6000 rows / 30001 frames with zero gaps.)

### 5.2 Gyroscope: integrate angular rate, compare to pose angle

A gyro has no free reference like gravity, but there is a stronger constraint: **the time
integral of angular rate must equal the angle the pose actually turned through.**

So: record pose A → rotate → pose B, compute the true angle θ from the accelerometer, and
integrate the gyro over the same interval. The ratio is the sensitivity.

| Event (first session) | Measured θ | ∫gx·dt | LSB/(°/s) |
|---|---|---|---|
| Flat → face down | 170.7° | +3017 | **17.67** |
| Flip back | 120.9° | −1992 | **16.48** |
| Upright flip | 165.7° | −2716 | **16.39** |
| Fast flip | 91.6° | +1470 | **16.06** |
| **first-session median (n=4)** | | | **16.44** |
| **retest median (n=6)** | 55.3°–149.3° | | **16.35** |

**A ±2000 dps range implies 32768/2000 = 16.384.** The two independent medians, 16.44 and
16.35, are off by 0.3 % and 0.2 % — that level of agreement is not something you get by fitting.

> `hid_reports.md` gives the nominal `2000.0/32767` = **16.3835 LSB/(°/s)**. It lines up too.

**Method note**: no external calibration equipment was used. The only thing relied on is the
physical constraint that the integral of angular rate must equal the pose angle actually
turned through — with the accelerometer's already-calibrated angles as the reference. So the
gyro calibration is built on top of the gravity calibration.

The retest also produced a **29046 LSB** peak, 88.7 % of full scale. At ±2000 dps that is
1773 dps, which a quick hand flip can reach; at ±1000 dps it would only be 886 dps, which
does not match the observed motion. Independent support for the range.

Bias (median over 411 idle bins): gx=8, gy=3, gz=7 LSB = **0.49 / 0.18 / 0.43 dps**.

> **Don't wave that away as "negligible".** For reading instantaneous angular rate, 0.5 dps is indeed
> small. But **integrated into an angle** it keeps accumulating: 0.49 dps = **29.7 °/min**. Attitude
> estimation without bias subtraction drifts off completely within minutes. The conversion in §6 already
> subtracts these values — use the formulas as given and you won't trip.

**Idle noise, plus one external cross-check** (`imu_formal_2026-10-25.csv`, flat segment, 650 samples /
13 s):

| Axis | Mean (LSB) | Noise σ (LSB) | σ in dps | Bias drift |
|---|---|---|---|---|
| gx | 8.11 | 1.97 | **0.120 dps** | 29.7 °/min |
| gy | 3.30 | 1.30 | 0.079 dps | 12.1 °/min |
| gz | 6.47 | 1.03 | 0.063 dps | 23.7 °/min |

Steam's "Gyro Calibration" page shows all three axes wandering between **−0.1 and +0.1 dps** at rest
(observed by the user, 2026-10-25). Converting our raw noise with 16.384 gives **σ ≈ 0.12 dps** — same
order, same scale.

That comparison means two things:

1. **The range constant gets external support.** If the LSB were off by a factor of two, the noise would
   read 0.24 or 0.06 dps — obvious at a glance. Two fully independent paths (our angular-rate
   integration / Valve's implementation) land on the same number.
2. **That page is showing residual after bias subtraction.** If it showed raw values, X would sit at
   **+0.5 dps**, not near zero. So Steam performs a per-device gyro calibration — **the same correction
   our table applies with 8/3/7**.

> To be explicit: **our data does not go through Steam's calibration.** The probe reads raw `0x05` bytes
> and applies its own measured offsets. Steam's page is merely an external implementation that happens
> to be comparable — not the source of our numbers.

### 5.2b Gyro vs accelerometer: an independent cross-check around the long axis

Two sensors in the same recording check each other (`data/imu_spin2_2026-10-25.csv`, 26 s, four
consecutive flips about the **Y axis**):

| # | Duration | Gyro integral | Accelerometer angle | Ratio |
|---|---|---|---|---|
| 1 | 3.00 s | 183.5° | 169.9° | 1.080 |
| 2 | 4.70 s | 257.0° | 258.3°* | 0.995 |
| 3 | 3.02 s | 177.9° | 173.3° | 1.027 |
| 4 | 3.38 s | 157.6° | 153.1° | 1.029 |

\* `acos` returns the shortest angle, so anything past 180° folds back (257° → 103°); corrected here
as 360−θ.

**Weighted ratio 1.028 → implies `LSB = 16.85` (nominal 16.384, +2.8%).**

Together with the 16.44 / 16.35 in §5.2, four independent estimates land in **16.35 – 16.85**, i.e.
`16.384 ± 3%`. The conclusion is deliberately modest: **the constant is not off by a factor of two**
(a factor-of-two error would show ratios of 0.5 or 2.0), but it is **not pinned to 0.1 %** either —
the remaining few percent come from segment boundaries and hand tilt, and are not worth "tuning away".
Use the nominal 16.384.

**Axis consistency**: during the flips `ay` changes by at most 784 LSB net, while `ax`/`az` swing
3,400–7,600 LSB — exactly what "gravity rotating in the XZ plane" looks like, i.e. **gyro Y and
accelerometer Y are the same physical axis**.

> **We walked into §7.2 again here**: trying to recover the rotation axis via `a0×a1` fails for
> near-180° flips, because `a0` and `a1` are almost antiparallel and the cross product is
> noise-dominated — two of the four estimates pointed away from Y, one even at X. Only the 157.6°
> flip gave a trustworthy `(0.27, 0.96, 0.07)`. **The cross-product method only works for small
> angles** — not a new finding, a lesson we had already written down, and hit again.

---

## 6. Full parameter table

```
Offset      Field  Type        Conversion (measured calibration)
──────────────────────────────────────────────────────────────
0x31:0x32   ax     int16 LE    a[g]   = (raw - 10.5) / 4090.8
0x33:0x34   ay     int16 LE    a[g]   = (raw + 5.2)  / 4090.7
0x35:0x36   az     int16 LE    a[g]   = (raw − 71.0) / 4067.0    <- face normal
0x37:0x38   gx     int16 LE    w[dps] = (raw − 8)    / 16.384
0x39:0x3A   gy     int16 LE    w[dps] = (raw − 3)    / 16.384
0x3B:0x3C   gz     int16 LE    w[dps] = (raw − 7)    / 16.384

Range: accelerometer ±8 g  (nominal 4095.875 LSB/g, measured 4092.6, −0.08%)
       gyroscope     ±2000 dps (16.384 LSB/(°/s), medians 16.44 / 16.35)
Frame:  +Z = face normal, out of the front face   (reads +1 g lying face up)
        +Y = along the long axis, toward the USB connector   (reads +1 g connector up)
        +X = Y x Z  (right-handed; points to the player's right when facing the front)
Radians: w[rad/s] = raw / 938.7
```

> If you don't want to calibrate, `a[g] = raw / 4096` is fine — about 1 % error.
> Use the measured gain/offset above only when you need better. Those numbers come from a
> single unit; recalibrate per controller (MEMS gain and offset vary unit to unit).

### 6.1 Whole-frame layout (corrected against prior work)

**Watch the offset base — they differ by one byte, and this is easy to trip over:**

| Base | Length | Meaning |
|---|---|---|
| `ndeadly`'s `hid_reports.md` | 63 bytes | HID **payload**, `0x00` is the first byte of the counter |
| This document / hidapi | 64 bytes | includes the report ID, `buf[0]` = `0x05` |

**Conversion: offset here = offset in that document + 1.**

| Offset here | Offset there | Field | Status |
|---|---|---|---|
| `0x01`–`0x04` | `0x00` | Counter (32-bit, +1 per packet) | documented, not re-verified |
| `0x05`–`0x08` | `0x04` | Button bitfield | see [`protocol.en.md`](protocol.en.md) |
| `0x0B`–`0x0D` | `0x0A` | Left stick (12-bit packed) | see [`protocol.en.md`](protocol.en.md) |
| `0x0E`–`0x10` | `0x0D` | Right stick (12-bit packed) | see [`protocol.en.md`](protocol.en.md) |
| `0x20`–`0x21` | `0x1F` | Battery voltage (mV) | see [`gauge.en.md`](gauge.en.md) |
| `0x22` | `0x21` | Charging state | see [`charging.en.md`](charging.en.md) |
| **`0x2B`–`0x2E`** | **`0x2A`** | **Timestamp, microseconds** | **confirmed here** |
| **`0x2F:0x30`** | **`0x2E`** | **Temperature (deviation from 25 °C)** | **confirmed here** |
| `0x31`–`0x3C` | `0x30`–`0x3B` | 6-axis IMU | see section 5 |
| `0x3D`–`0x3F` | `0x3C`–`0x3E` | Stick triggers (NSO GC only) / reserved | — |

### 6.2 Three fields we had judged wrong

Early on, three fields were marked "unknown". All three resolved once the layout in
`hid_reports.md` was taken into account. The failure mode is worth recording: **not knowing
the offset base was off by one byte made us slice a whole run of fields at the wrong
boundary.**

#### `0x2B`–`0x2E`: a 4-byte microsecond timestamp

We had split it on 16-bit boundaries, calling the low half `0x2B:0x2C` a "counter" and the
high half `0x2D:0x2E` an "unknown slow variable". It is a single **uint32 microsecond
timestamp**.

Every observation we had made fits:

- `0x2B:0x2C` increments by 3750 or 5000 per frame, 93.9 % monotonic, wraps every 16 bits —
  that is exactly how a **low 16 bits** behaves, with a 65.536 ms wrap period;
- `0x2D:0x2E` "drifts slowly and is *more* stable while shaking" — it is the **high 16 bits**,
  which only advance every 65.5 ms.

Read as microseconds: adjacent frames are 3.75 ms or 5 ms apart. Measured frame rate is
250.0 Hz (4 ms period); the weighted average of the two intervals is ~3.97 ms, a 0.7 %
deviation well inside measurement error.

> When we earlier guessed "the timebase is about 1 MHz" we didn't dare commit to it, and the
> ±1 offset kept steering us wrong. The unit is microseconds. There is no other reading.

#### `0x2F:0x30`: temperature

The documentation gives `Temperature deviation from 25 °C, sensitivity = 1/126.9 °C/LSB`.

In practice this 16-bit pair only ever flips between `0` and `−1`:

| raw | temperature |
|---|---|
| `0` | 25.000 °C |
| `−1` | 24.992 °C |

So **at rest the chip sits at 25 °C and varies by less than 0.01 °C**.

We had recorded it as "unknown binary, gets *more* active during the idle stretch". That
"more active" was the value dithering across the 25 °C boundary — more dither means it's
closer to the boundary, which on reflection indicates stability rather than a problem.

#### `0x23`–`0x2A`, `0x3D`–`0x3F`

The former is documented as constant 0 (with `0x01` at offset `0x29`); the latter is the GC
controller's trigger fields plus reserved bytes. Both are constant 0 on this device, matching
the documentation.

---

## 7. Three methodological lessons

### 7.1 "Changes at rest" doesn't prove a sensor; "responds only to motion" does

The initial wrong turn was treating `0x2B:0x2C` as a sensor candidate too — it changed the
most violently of all. What finally ruled it out wasn't "the change is too small", it was
**it doesn't respond to motion**.

A field can flap as hard as it likes; if it is uncorrelated with the independent variable,
it's noise or a clock. Build the criterion on **correlation**, not on **amplitude**.

### 7.2 A cross product gives the rotation axis, not the direction

Deriving the rotation axis from `a₁×a₂` produced mixed sign results (4 samples, 1 agreeing,
3 opposite). At first this looked like a sign-convention bug. It isn't —

**a cross product gives the same direction for θ and for 360°−θ**, and those two cases spin
opposite ways. So the cross product yields the *axis*, not *which way*. Sign must come from
**integration**, never from the cross product.

This one will get stepped on again, so it went straight into the comments of
[`tools/imu_gyro_fit.py`](../tools/imu_gyro_fit.py).

### 7.3 Compound motion contaminates single-axis calibration

The four Z-axis samples spread 14.8–21.4 LSB/(°/s), far wider than X's 16.1–17.7. The cause
isn't Z being bad — those events involved compound hand rotation, so the angle got split
across axes, the net-rotation θ came out low, and the resulting sensitivity came out high.

**Calibrate with clean motions.** Purity is judged not by the peak angular rate but by
whether the integral vector is significant on only one axis (in the X events here, ∫gy and
∫gz stayed under 200 while ∫gx ran 2000–3000).

---

## 8. Impact and boundaries

### 8.1 What this changes about the report

| Before | Now |
|---|---|
| `0x05` = buttons + sticks + battery | `0x05` = **full 6-axis telemetry frame** + buttons + sticks + battery |
| IMU required `0x09` (writes to the device, fights Steam for it) | **read-only USB polling suffices** (one caveat below) |
| `0x23+` marked "unresolved / safe to ignore" | all 29 bytes accounted for: 12 IMU + 4 timestamp + 2 temperature + counter and reserved |

**"Read-only suffices" has a caveat — don't miss it: the device must be activated once.**

Measured: a freshly plugged controller does not enter report mode on its own. USB
enumeration succeeds, `open_path` succeeds, the handle opens — and 25 seconds of reads yield
nothing. Once activated it runs at full rate indefinitely, and **fully quitting Steam does
not affect it** (1251 frames / 5.00 s = 250.2 Hz with neither `steam.exe` nor
`steamwebhelper.exe` in the process table).

So the accurate statement is: **activation is needed exactly once; after that it is pure
read-only with zero application dependency.** The activation trigger is "launch Steam", and
**what it actually sends has since been identified** — see the next section.

### 8.1b What activation actually does (cross-checked against prior work)

This section is not original reverse engineering on our part — it is our own capture
cross-checked against existing public documentation. Primary source:
[`ndeadly/switch2_controller_research`](https://github.com/ndeadly/switch2_controller_research),
file `commands.md` (updated 2026-04).

#### The device is composite, with three interfaces

| Interface | Windows class | Purpose |
|---|---|---|
| `MI_00` | HIDClass | input reports such as `0x05` — **all capture in this project uses this one** |
| `MI_01` | USBDevice (vendor) | **initialisation command channel** |
| `MI_02` | MEDIA | 3.5 mm headset audio |

**The key point: commands do not go through the HID interface.** That explains a very
typical failure: sending commands to `MI_00` with `hid.write()` or `HidD_SetOutputReport`
only ever returns `err=87` (invalid parameter) or `err=31` (device rejects) — that interface
isn't wired to that channel at all.

#### Command frame (8-byte header + optional data)

| Offset | Field | Value |
|---|---|---|
| 0x0 | Command ID | `0x01`–`0x18` |
| 0x1 | Direction | **`0x91` = host→device**, `0x01` = device→host |
| 0x2 | Transport | **`0x00` = USB**, `0x01` = Bluetooth |
| 0x3 | Subcommand | |
| 0x4 | Unknown | |
| 0x5 | Data Length | |
| 0x6–7 | Reserved | `00 00` |

#### Four commands that matter

| Command | Effect |
|---|---|
| `03 91 00 0A 00 04 00 00 \| 05 00 00 00` | **select input report `0x05`** |
| `0C 91 00 02 00 04 00 00 \| 27 00 00 00` | **set feature mask** (`0x27` = buttons + sticks + **IMU** + rumble) |
| `0C 91 00 04 00 04 00 00 \| 27 00 00 00` | **enable the masked features** (incl. IMU) |
| `03 91 00 0D 00 08 00 00 \| 01 00 + 6-byte host address` | **initialise USB** (required before streaming) |

**Two separate things here, easy to conflate:**

- `0x0A` selecting `0x05` decides **which report the device sends**
- `0x0C/0x02` + `0x0C/0x04` with mask `0x27` decides **which fields that report contains**

In other words, `0x0A` alone will make `0x05` appear but with an empty IMU block.
Both are needed to get the full 64-byte telemetry frame this project relies on.

> One trap worth recording: `0x0D` is often read as "enable IMU". It is actually
> "initialise USB". We made exactly that mistake early on and only corrected it against
> the documentation.

#### Our capture matches the documentation command for command

USBPcap captured 19 commands (`activate_capture.pcap`), all within `t=17.222–17.329`
— 107 ms — with the first `0x05` at `t=17.333` (4 ms later):

```
02 91 00 01 …  ×7           handshake / polling
07 91 00 01 …               first init command
0c 91 00 02 | 27 00 00 00   set feature mask
0a 91 00 08 …               rumble enable
0c 91 00 04 | 27 00 00 00   enable features
01 91 00 0c …               HOME LED
01 91 00 01 …               handshake
08 91 00 02 …               subcommand
03 91 00 0a | 05 00 00 00   select report 0x05   <- stream starts here
03 91 00 0d | 01 00 ff…     initialise USB
──────────────────────────  4 ms later
05 8e 3b 00 …               first 0x05
```

Order, lengths and subcommands all line up with `commands.md`. **This capture can serve as
an independent verification of that document** — it was taken on Windows 11 with Steam
running, i.e. under different observation conditions.

#### Why this project does not implement activation itself

It is technically feasible: bind WinUSB to `MI_01` (Zadig or libusb) and send the commands
above. But the trade-off doesn't pay:

| | Own activation | Activate once with existing software |
|---|---|---|
| Host-side dependency | needs a WinUSB driver bound | none (Steam can be uninstalled after) |
| Capture phase | read-only | read-only |
| Reproduction effort | moderate (driver install) | low |
| Risk | rebinding a driver may affect other HID behaviour | zero |

Note that **installing a driver is not the same as writing to the device** — Zadig only
changes the binding on the host side and sends the device nothing. But its entire purpose is
"so that we can send commands next", so it does nothing for a read-only posture.

**This project's position is therefore fixed: activation is done once by existing software;
the capture phase stays strictly read-only.**

### 8.2 Practical value

- **Third-party receivers / DIY bridges**: no init sequence needed to read the IMU, a large drop in complexity;
- **Controller test tools / overlays**: pose display, joint diagnosis of stick drift and IMU drift;
- **Latency measurement**: IMU and buttons share one frame, so alignment is exact to 4 ms for free.

### 8.3 Boundaries (don't treat this as a datasheet)

- **n=1**: one device, one firmware. Range and axis mapping are **chip-level constants** and
  very likely consistent across units; but bias, sensitivity error and axis non-orthogonality
  **are per-unit**. Don't copy the numbers blindly;
- **±2000 dps is inferred from sensitivity**: no chip ID was read and no saturation test was
  run. 16.384 points hard at that setting, and the retest peak reached 88.7 % of full scale,
  but **clipping was never observed**;
- **±8 g likewise**: locked by six-face gravity magnitude (all six faces return to 1.0000 g),
  which is solid — but no shock test verified the upper limit;
- **Gyro Y axis is not independently calibrated**: `gy` samples came from compound motions
  with too little net rotation; it is assumed to match the other two axes;
- **The activation sequence is identified, but this project does not implement it**: full
  command table in 8.1b, sourced from `ndeadly/switch2_controller_research` (`commands.md`)
  and independently corroborated by our own USBPcap capture. It isn't implemented because of
  the minimal-dependency stance — doing so requires binding a WinUSB driver on the host,
  while "activate once with existing software" costs essentially nothing;
- **USBPcap 1.5.4 does not record the SETUP stage of control transfers**: the capture only
  holds DATA, so the `wValue` of `SET_REPORT` (the report ID) is unavailable. That is a
  limitation of the capture tool, **not a protocol gap** — the command channel itself is
  known (`MI_01`, vendor interface). Closing it would need Bus Hound or a newer USBPcap;
- **No temperature-drift testing**: short observations only, cannot be extrapolated to
  cold or heat-soaked states.

### 8.4 What we add on top of prior work

**Bottom line first: the IMU finding in this document is not a first.** When wrapping up
(2026-10-25) we confirmed that `ndeadly`'s
[`hid_reports.md`](https://github.com/ndeadly/switch2_controller_research) had already
documented the types and ranges of the `0x05` motion data on 2026-09-08 — earlier than us.

What is still new here:

| Increment | Detail |
|---|---|
| **Axis mapping and sign** | `hid_reports.md` gives only the data type and range (`Signed 16-bit LE`, ±8 G / ±2000 dps); it **does not record which direction each axis points or what the sign means**. This document supplies the X/Y/Z orientation and signs from six-face calibration (5.1) |
| **Measured sensitivity and bias** | The documentation gives nominal values (4095.875 LSB/g / 16.3835 LSB/dps); this document gives measured values from one unit (−1.0 % / +0.3 %) |
| **Offset-base correction for the whole frame** | The ±1 offset caused by the report ID, and the re-identification of three previously misjudged fields (6.1, 6.2) |
| **Independent verification of the activation sequence** | Captured on Windows 11 with Steam, matching `commands.md` command for command (8.1b) |

**The order of events needs to be stated precisely**: when we started, we had **not** read
`hid_reports.md` — otherwise the "two independent paths" claim in 5.1 would not hold. What started it
was internal process: the protocol doc was going to say "these 29 bytes can be ignored", and the word
"ignore" has to be falsified before it may be written.

Reading `ndeadly`'s field table happened **after every calibration was finished, while preparing the
issue**. Its role was to **confirm we were not first** (and incidentally explain why three fields had
been sliced at the wrong offset) — not to point us anywhere. Getting that order backwards would void
the "independent verification" claim, which is one of the few genuinely load-bearing arguments here.

---

## Appendix: reproducing this

```bash
# 0. Activate the device once: launch Steam, wait for the green LED, then fully quit Steam.
#    The device stays activated for as long as it remains plugged in, so read-only works.
python tools/probe_env.py 6                         # expect: only 0x05, 250Hz, az ~ +4100

# 1. 80-second A/B capture (idle 8s -> shake 53s -> idle 19s)
python tools/imu_tail_probe.py 80 --csv imu_ab.csv
python tools/imu_pairs.py imu_ab.csv        # check whether high bytes "thaw"

# 2. Long calibration (six faces + axis rotations + translation, default 900s / 50Hz)
python tools/imu_calib.py 900 --csv imu_calib.csv
python tools/imu_segments.py imu_calib.csv  # split idle platforms vs motion events
python tools/imu_events.py   imu_calib.csv  # per-event extremes and rotation axis
python tools/imu_gyro_fit.py imu_calib.csv  # integrate angular rate to fit the range

# 3. For "0 frames" debugging, the hotplug watcher (auto-reconnect, logs unplug/replug/recovery)
python tools/imu_hotplug_watch.py 150 --csv hotplug.csv

# 4. To capture the USB layer yourself (needs USBPcap, admin). pcap is DLT_USBPCAP(249),
#    parseable without Wireshark:
python tools/parse_usbpcap.py capture.pcap summary|ctrl|timeline
```

Raw data from this session:

| File | Contents |
|---|---|
| [`imu_ab_..._static_shake_static.csv`](../data/imu_ab_2026-10-25_static_shake_static.csv) | 80 s / 20,001 frames, idle→shake→idle |
| [`imu_calib_2026-10-25.csv`](../data/imu_calib_2026-10-25.csv) | 127 s / 6,368 rows, first six-face run (Steam on) |
| [`imu_calib_2026-10-25_steam_off.csv`](../data/imu_calib_2026-10-25_steam_off.csv) | 120 s / 6,000 rows, retest (Steam off) |
| [`imu_ax_faces.csv`](../data/imu_ax_faces.csv) | 55 s / 2,750 rows, X-axis both faces |
| [`imu_spin2_2026-10-25.csv`](../data/imu_spin2_2026-10-25.csv) | 26 s / 1,300 rows, four flips about Y (gyro vs accel) |
| [`steam_off_verify.csv`](../data/steam_off_verify.csv) | 40 s / 2,000 rows, continuity check without Steam |
| [`hotplug_steam_off.csv`](../data/hotplug_steam_off.csv) | full unplug→replug, including the 63 s zero-frame gap |

---

## References

The field layout, command protocol and nominal scale factors here rest mainly on the
following public work. If you cite this document, please cite the original sources too.

| Source | What it provides |
|---|---|
| [`ndeadly/switch2_controller_research`](https://github.com/ndeadly/switch2_controller_research) | **Primary source.** `commands.md` for the command frame and subcommand table; `hid_reports.md` for the `0x05` layout, ranges and sensitivity; `datasheets/` includes the ICM-42607-P datasheet |
| `kennethreitz`'s `PROTOCOL.md` | Early field table, marking everything after `0x23` unknown |
| [`hifihedgehog/HIDMaestro`](https://github.com/hifihedgehog/HIDMaestro) | Identifies 057E:2069 as HID@interface0 + vendor@interface1 |
| [`Altureus/Windows-Switch2-Pro-Controller`](https://github.com/Altureus/Windows-Switch2-Pro-Controller) | Practical WinUSB-vendor-interface wake implementation |

For what this document adds beyond those sources, see 8.4.

---

> Every number here comes from the raw CSVs of a single device, with no smoothing or manual
> correction. Please cite the raw data alongside it.
