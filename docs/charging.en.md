# Charging · status bytes, full cycle and load

> **English** · [中文](charging.md)

> Bitfields of the six status values, the timeline of one full charge, the churn phase,
> LED semantics, replug behaviour and the load experiments.

> Back to [README](../README.en.md) · Chinese version [`charging.md`](charging.md)

---

## 1. Status byte and the full cycle

### 1.1 The six values and their bitfields

The complete set observed is **6 values, no unknowns**:

| Value | Binary | b5 power | b2 current | b4:b3 | Observed meaning |
|---|---|---|---|---|---|
| `0x2C` | `0010 1100` | 1 | 1 | 1 | Churn / intermediate (**not** a plug-in handshake) |
| `0x34` | `0011 0100` | 1 | 1 | 2 | **Real charging** (high current; red LED on) |
| `0x3C` | `0011 1100` | 1 | 1 | 3 | **Pre-completion transient, exactly 10.0 s** |
| `0x24` | `0010 0100` | 1 | 1 | 0 | Maintenance pulse (short on-time, LED stays off) |
| `0x20` | `0010 0000` | 1 | **0** | 0 | **Charge complete** (LED off) |
| `0x00` | `0000 0000` | 0 | 0 | — | External power path open (chopping OFF phase) |

- **The b5 / b2 flags hold** (no exception across all 6 samples).
- **b4:b3 cannot be read as a "stage counter"**: the insertion sequence was observed as
  `0→2→1→2`, i.e. **non-monotonic**. The stage hypothesis is downgraded.

### 1.2 The full cycle (two sessions stitched, with one manual replug)

> ⚠️ This table is **not a natural continuous cycle**. After entering `0x20` at 09:42 it sat still
> for 5 h 39 m and did **not** move into chopping by itself; a **manual replug at 15:21** is what
> triggered the later chopping. The two halves are stitched together.

| Phase | Status | Duration | Reading behaviour |
|---|---|---|---|
| Fast charge | `0x34` | ~39 min (starting from reading 3,539, ≈78 % on the empirical scale) | +7/min, rising to ≈3684 |
| Pre-completion transient | `0x3C` | **10.0 s** (n=2, identical) | ≈3727 |
| Complete / idle | `0x20` | **5 h 39 m** (09:42–15:21) | slow decay, −0.22 to −0.29/min |
| **[manual replug @ reading 3,616]** | — | — | **`0x20` did not exit by itself; the replug did it** |
| Maintenance (chopping) | `0x00`/`0x24` @2.9 Hz | **8 h 46 m** (15:23–00:09:45) | 3,677–3,689, stable |
| Churn | `0x2C` dominant (see §1.3) | ~7 min | 3,722–3,727 |
| Second real charge | `0x34` | ~10.5 min | 3,728 |
| Complete again | `0x3C` → `0x20` | 10 s | 3,715 |

**Get the arithmetic straight**: one round of "replug wake-up → maintenance → churn → full again" is
about **8.8 hours (8 h 46 m)**; it does **not** include the preceding 5 h 39 m of `0x20`. Whether
`0x20` ever exits by itself (and after how long) is **still unobserved**.

### 1.3 The churn phase — only a high sample rate can see it

For ~7 minutes before the maintenance phase ends, the status cycles through a fixed pattern
**38 times**:

```
0x24 (~28 ms) → 0x34 (typically 4 ms = exactly one frame) → 0x2C (median 440 ms) → back to 0x24
```

`0x34` exists for only **4 milliseconds**. **Anything polling at 1 Hz will never see this** —
it just sees `0x00`/`0x24` for hours and then, at some point, `0x20`.

### 1.4 What the red LED actually means

| Moment | Status | LED |
|---|---|---|
| Charging | `0x34` | **On** |
| Charge complete | `0x3C` → `0x20` | Off |
| Maintenance chopping (`0x24` at 10–12 %) | `0x00`/`0x24` | **Off, and steadily off** |

Conclusions:

- **The LED follows `0x34`, not the `0x24` maintenance pulses.** The `0x24` current is too small
  to light it.
- **Steadily off, not blinking at 3 Hz**: if the LED were current-driven, a 12 %-duty pulse train
  would necessarily blink or glow dimly. ⇒ the LED is driven by **firmware state**
  ("charging ended" → light off), not by current.
- Signal hierarchy: `LED (firmware's opinion)` > `0x34 (real current)` > `0x24 (short pulses, invisible to the LED)`.

### 1.5 Replug behaviour depends on how depleted the battery is

| Reading at replug | First frame | Real charging? | Afterwards |
|---|---|---|---|
| 3,616 (already discharged) | `0x24` | **Yes** (~1 min of `0x34`) | the `0x00` off-duty starts at 82 % and creeps up to 90 % |
| 3,676 (already topped) | `0x00` | **No** | straight back to 90 % `0x00` off-duty chopping, no `0x34`/`0x2C` at all |

⇒ **"Plugging in always starts a charge cycle" is wrong.** Plugging in a full controller is only a
link rebuild and does not trigger charging.

### 1.6 Load does not affect charging decisions, and maintenance draws no battery

39 minutes of real gameplay (250 Hz throughout):

```
button activity   mean 11.6 %, peak 51 %, input in 39/39 minutes
status            only 0x00 / 0x24, never 0x34
reading           3,673–3,677 the whole time (range of 4)
active − idle     −0.35 (far below one unit)
```

- Without external power, the `0x20` segment's −0.22/min would have cost 8–9 units → **the
  maintenance phase is powered over USB**, so the 10 % `0x24` pulses are **genuine top-ups**, not probing.
- The effect of button load on the reading is **below the field's resolution** (−0.35).
  ⚠️ **But that only holds under USB power** — see §1.7, where the same effect is ~40× larger on battery.

### 1.7 Rumble is the only significant power draw (in-game A/B)

The §1.6 experiment ran in the **chopping state (USB powered)**, so it could not detect load.
On the morning of 2026-10-25 it was redone **on battery (`0x20`)**: four consecutive segments
formed a dose–response curve, then a strict A/B was performed by **toggling rumble inside one game**.

**First, clear up a counter-intuitive wording**: "on battery" sounds like "unplugged", but the cable
stays plugged in. The difference is in the `0x20` bitfield (§1.1) — **b5 = 1 (VBUS present),
b2 = 0 (no charging current)**:

> During `0x20` the USB +5 V rail is still live, but once full, the charging-management IC
> **shuts off the path that pushes current into the battery / system** (or enters a high-impedance
> state where the battery alone handles transient loads). The system and the rumble motor are then
> **powered entirely by the battery**; USB only carries data. That is why a rumble motor's transient
> current spike directly drags down the battery terminal voltage and exposes the internal-resistance
> drop (depth 24–37).
> During `0x00`/`0x24` maintenance, the rail is held up over USB, so the same load shows no drop
> (only 0.35).

This ties the bitfield `b5=1, b2=0` and the "two orders of magnitude between power modes" into a
single causal chain.

#### 1.7.1 Four-segment dose–response (same `0x20` segment, same power mode, 250 Hz)

| Segment | Duration | Button activity | Reading slope | Peak-to-trough depth (mean−min) |
|---|---|---|---|---|
| Idle (no input) | 2–5 min | 0.2 % | **−0.25 /min** | 0.9 |
| JSAB (rumble very sparse, only on hits) | 14 min | 5.2 % | **−0.23 /min** | 7.3 |
| Post Void (dense rumble, continuous shooting) | 5 min | 25.2 % | **−0.92 /min** | 12.8 (max 16.8) |
| Apex range (rumble on, highest input rate) | 5 min | 43.1 % | **−1.36 /min** | 24.3 (max 37.5) |

Both metrics rise monotonically with load. But **that is not causal yet** — button activity and
rumble intensity increased together.

#### 1.7.2 The decisive A/B: same game, same actions, rumble toggled

Rumble was switched **off** in the Apex range while the same actions (move / aim / shoot) continued:

| Metric | Rumble on (5 min) | Rumble off (8 min) | Ratio |
|---|---|---|---|
| **Button activity** | 43.1 % | **47.2 %** | *more* active with rumble off |
| **Reading slope** | **−1.360 /min** | **−0.200 /min** | **6.8×** |
| **Peak-to-trough depth** | **24.3** (max 37.5) | **0.8** (max 1.1) | **30×** |
| Reading range | 3,550 ~ 3,589 | 3,582 ~ 3,585 | — |
| Status byte | `0x20` 100 % | `0x20` 100 % | zero transitions |

**Turning rumble off cut the discharge rate by 85 %, and the reading immediately rose by 4 units.**

The key is that **button activity was *higher* with rumble off** (47.2 % vs 43.1 %). If the power
came from input, the rumble-off segment should be steeper; it measured flatter.
**The direction is opposite, so the only remaining explanation is rumble.**

#### 1.7.3 Conclusions and magnitudes

```
idle / input-only, no rumble   ≈ −0.20 to −0.25 /min   (baseline, indistinguishable)
continuous rumble              ≈ −0.92 to −1.36 /min   (scales with rumble density)
```

- **The sticks and buttons themselves draw less than the field's resolution**: 5.2 % vs 0 %
  button activity differ by only +0.05 in slope (within noise).
- **Peak-to-trough depth is a binary feature**: a ~5× difference in button rate (5.2 % → 25.2 %)
  only gives 1.75× more depth (7.3 → 12.8); but once rumble starts, depth jumps to 24–37.
  **Depth mostly indicates "is rumble active", not load magnitude.**
- **The instantaneous drop is ≈24–37 units and is only visible on battery** — roughly **70–100×**
  the 0.35 seen under USB power. Reason: with USB power the rail holds the voltage, the battery is
  not in the discharge loop, and the internal-resistance drop never shows.
  **The same physical quantity differs by two orders of magnitude between power modes — the easiest
  place to misjudge.**
- **The status byte stayed `0x20` with zero transitions**, even at 47 % button activity plus
  continuous rumble. Consistent with §1.6 / §1.2: **recharge decisions ignore load**.
- **Zero dropped frames**: 15,000 frames per 60 s throughout. The host writing rumble to EP2 does
  **not** conflict with the input report.

> **Implementation implication**: to estimate power or remaining time from the reading you must
> **first determine the power mode** (whether the status byte is in the charging family
> `0x2C/0x34/0x3C/0x24`). On battery the reading is polluted by both "charge level" and
> "rumble state": during rumble a single frame can swing **40 units**.
> Conversely, this can be exploited — **the reading's spread is a reliable proxy for "is it rumbling"**
> (depth <2 = no rumble; >20 = rumbling).
>
> **Known confound (largely excluded)**: the A/B used the same game, same time window and same host
> load, removing the "3D rendering load" variable that cross-game comparisons cannot exclude.
> Remaining gap: rumble intensity was only on/off, so no linear model can be given.

### 1.8 One maintenance round, in one place

```
0x34 fast charge → 0x3C (10 s) → 0x20 (hours, slow decay, does not exit by itself)
   │
   │   ← a manual replug (or some not-yet-observed natural trigger) is what leaves 0x20
   ↓
0x00/0x24 chopping (hours, `0x00` off-duty climbing to ~90 %)
   → churn (~7 min, 38 cycles) → 0x34 full-power (~10 min) → 0x3C → 0x20 → …
```

**One round of "replug wake-up → maintenance → churn → full again" is ~8.8 h (8 h 46 m)**; it does
not include the preceding `0x20` idle stretch. Whether `0x20` can exit by itself, and after how long,
remains an open question (see [boundaries §1.3](boundaries.en.md)).
