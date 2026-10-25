# Gauge Reading · what the number means

> **English** · [中文](gauge.md)

> Why this field is not a voltage, how it oscillates with the chopping, and what you must not use it for.

> Back to [README](../README.en.md) · Chinese version [`gauge.md`](gauge.md)

---

## 1. Reading semantics

### 1.1 It is not a voltage

At full charge it reads only **≈3670–3728**, while a fully charged Li-ion cell should be 4.15–4.2 V.
The entire charge raises it by only **+190** (3,539 → 3,728). Therefore:

- **You cannot** convert it to a percentage with a generic Li-ion open-circuit-voltage curve
  (the `soc_percent` column in `data/sw2_charge.csv` is an early mistaken artefact and is **deprecated**);
- It behaves more like an **offset/scaled voltage sample**: on the same battery it can differ by
  **66 units** before and after a replug (3,616 ↔ 3,682);
- A real conversion needs an independent voltage reference (multimeter / USB power meter),
  which this repo does not have.

### 1.2 During maintenance it oscillates with the chopping

60 seconds / 15,001 frames, bucketed by "k-th frame after a transition":

| k-th frame after transition | → `0x24` | → `0x00` |
|---|---|---|
| 0 | 3,673 | 3,693 |
| 8 | 3,689 | 3,687 |
| 15 | 3,692 | 3,674 |
| 30 | 3,674 | 3,673 |

**The reading swings in sync with the chopping, amplitude ≈ ±10, lagging the status by 10–15 frames
(40–60 ms).**

⇒ **Implementation constraint**: during maintenance a single frame carries ±10 of noise; always
average over at least one chopping period (≈350 ms). A UI should use a ≥1 s window, otherwise the
number jitters at 2.9 Hz.

### 1.3 Prohibited uses

- ❌ Comparing charge level **across a replug** (66 units apart)
- ❌ Treating a **single frame** as a voltage (±10 chopping noise)
- ❌ Converting to a percentage with a Li-ion curve
- ❌ Treating the mean difference between `0x00` and `0x24` as a fixed offset to correct for
  (the sign flips depending on sampling phase)
