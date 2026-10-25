# Implementation · rules and defensive constraints

> **English** · [中文](implementation.md)

> State classifier pseudocode, seven defensive rules, and real frames you can use as unit-test fixtures.

> Back to [README](../README.en.md) · Chinese version [`implementation.md`](implementation.md)

---

## 1. Implementation rules

### 1.1 State classifier

The primary signal is the **windowed duty cycle** (a stable 0/1 statistic); the trend is only
auxiliary (the reading's jitter span is larger than the fast-charge signal).

> **Terminology**: `duty00` below means the **fraction of time in `0x00` (off / not charging)** — the
> *opposite* of the EE convention "duty cycle = ON fraction". The 82 %–90 % figures are `duty00`
> (off-duty); the corresponding ON duty is 18 %–10 %. Do not conflate the two.

```
enum State { Discharging, FastCharging, ToppingOff, Full, GenericCharging }
const KNOWN = { 0x00, 0x24, 0x2C, 0x34, 0x3C };   // 0x20 handled separately
const FULL  = 0x20

feed(raw, status, t):
    # 0x20 (complete) does not enter the duty window; return immediately. See below.
    if status == FULL:        return Full
    if status not in KNOWN:   return GenericCharging   # unknown byte → degrade, UI shows Raw
    push(t, raw, status);  drop_older_than(t - 600)
    if window < 60 s:         return current
    duty00 = fraction(status == 0x00, last 120 s)
    delta  = median(on-samples, second half) - median(on-samples, first half)
    if duty00 >= 0.15:        return ToppingOff        # 0.15~1.0 all just mean "degree of maintenance"
    # reached here: >85% of the time in the charging family (0x34/0x2C/0x24), i.e. really charging
    if delta  <= -8:          return Discharging       # charging yet the reading falls → abnormal/suspicious
    return FastCharging
```

Three notes:

- **`0x20` must return early and stay out of the window.** If `0x20` were pushed into the window,
  after hours of it the `0x00`/on-samples would be diluted, and once it returns to charging both
  `duty00` and `delta` would be badly distorted. The cost is that after `0x20 → other` the 60 s
  window must refill — negligible on an 8-hour cycle.
- **`duty00` uses a single `0.15` threshold.** It used to have two (0.75 / 0.15) that both returned
  `ToppingOff`, making the first a dead branch. The measured duty reached 90 % and still kept
  maintaining for hours before doing another real charge — **duty only measures "fraction of time not
  charging" (= how much more it wants), not "full"**. Only `0x20` can judge fullness.
- **`Discharging` is almost unreachable on this read-only USB channel**: while on USB the status is
  either in the charging family or `0x20` (already complete, already returned early) — there is no
  "really running on battery" status byte. It is kept for three reasons: ① defensive against unknown
  firmware; ② reserved for a future BLE channel; ③ `delta <= -8` at low duty means "charging yet the
  reading falls", which is worth flagging on its own (bad contact / insufficient power).
  **Known false-positive risk**: while charging-and-playing with rumble, a transient drop can briefly
  push `delta <= -8`. A production implementation should add a "sustained ≥30 s" hysteresis, or simply
  use the peak-to-trough depth to tell rumble apart (see [Charging §1.7](charging.en.md)).

### 1.2 Seven defensive rules

1. **`0x20` = complete**: `status == 0x20` → `Full` unconditionally. `0x3C` must be in the known set
   (otherwise every charge cycle reports 10 seconds of "unknown").
2. **Unknown byte degradation**: bytes outside the set must **not raise, and must not be treated as
   offline** — set `GenericCharging` and annotate `Raw: 0xNN`.
3. **Reading overflow/underflow**: if the UI wants a "relative progress bar", use an **empirical
   linear mapping** (`[3520, 3720]` → `[0,100]`), always `Clamp(p, 0, 100)`. ⚠️ Use the measured full
   value **3720–3728** as the upper bound, not the old 3680; and treat this as a **purely empirical
   mapping, not real SoC** (the reading is not a voltage, see [Gauge §1.1](gauge.en.md)); it is only
   meaningful on battery without rumble.
4. **Wrap protection**: `cur < last && last-cur > 1000` → increment epoch, reset the baseline; never
   subtract unsigned values directly. With sparse sampling use the gap-aware test in
   [Protocol §1.2](protocol.en.md).
5. **Link debounce**: a single read error or timeout keeps retrying for 1–2 s; only **3 consecutive
   failures** mark `Offline` and release the handle.
6. **Never drive the UI from an instantaneous value**: `0x24` occupies only 10–12 %, so 1 Hz polling
   flashes "charging" every ~8 seconds; use the windowed duty cycle. Likewise the reading must be
   smoothed ([Gauge §1.2](gauge.en.md)).
7. **Freeze the battery reading while rumbling**: if the window's reading spread (peak-to-trough
   depth) is > 15, mark `RumbleActive` and freeze the "progress/battery" update (or take only the
   window's P90 upper envelope). Otherwise the on-battery transient drop
   ([Charging §1.7](charging.en.md), depth 24–37) makes the UI battery **plunge ~20 % the moment the
   player fires**.

### 1.3 Unit-test fixtures (real frames)

```
# Ordinary frame (status=0x2C, reading 3539)
05 9B 22 00 00 …                      → clock=8859 (0x229B)
05 9F 22 00 00 …                      → clock=8863 (next frame, +4)
05 42 AD 00 00 … … D3 0D …            → clock=44354, gauge=3539, status=0x2C

# Wrap boundary (must be classified as wrap, not reset)
05 42 68 15 00 …                      → clock=1,431,650 (last frame before wrap)
05 01 00 00 00 …                      → clock=1 (first frame of the new epoch)

# Completion sequence (4 ms per frame; 0x3C lasts only 10 s)
… status=0x34 … → status=0x3C (10,004 ms) → status=0x20
```

Reference implementation: `tools/switch2_battery_state.py` (Python, with CSV replay).

### 1.4 Dynamic stick centre and radius calibration (read-only)

Without the SPI calibration block, use **runtime statistics** to cancel the per-unit centre offset:

```
# lock the initial centre (guarded, so "pushing the stick while plugging in" can't become the centre)
cx, cy = 2048, 2048        # fallback: ideal centre, until a still window is captured
buf = []
for each frame:
    if no buttons pressed (btn == 0):
        buf.append((x, y))
    else:
        buf.clear()          # any input resets the still window
    if len(buf) == 50:       # 50 frames = 200 ms
        if max(x)-min(x) < 10 and max(y)-min(y) < 10 \
           and 1800 <= mean(x) <= 2300 and 1800 <= mean(y) <= 2300:
            cx, cy = mean(x), mean(y)    # still + within the prior centre window → lock
            break
        else:
            buf.pop(0)        # not satisfied: slide on, never take it blindly
# once locked:
at runtime keep the max deflection radius r_max (sliding max of hypot(x-cx, y-cy))
normalize with r = min(r_max, 1780)     # 1780 = lower bound of the measured radius
out = clamp((x - cx) / r, -1, 1)
```

- **The "no-input sample" criterion**: it must satisfy **both** "consecutive 50 frames with
  range < 10 (truly still)" **and** "mean inside the [1800, 2300] prior window". Otherwise a user who
  plugs in while holding the stick (or pushes it during the first 200 ms) would have the deflected
  coordinate (e.g. 3,700) taken as the centre, permanently wrecking the whole session.
- **Why a runtime centre**: the right stick's resting centre was measured at `(2159,2152)` (up to +117
  off the ideal 2048). Using a fixed 2048 turns "not pushing" into a permanent offset; capturing a
  still window removes it.
- **Why `min(r_max, 1780)`**: the hardware radius measures 1765–1810 ([Protocol §2](protocol.en.md)).
  Early in a session `r_max` has not been pushed to its limit yet; using it directly would overstate
  the axis value. Capping at 1780 is the fallback. As the player pushes further, `r_max` catches up,
  so it never "fails to reach the edge".
- This is an **approximation**, less accurate than the SPI calibration block, but good enough for
  overlay UI / input mapping — and it never writes to the device.
