# Reproduction Guide

> **English** · [中文](REPRODUCE.md)

Every conclusion in this repo comes from **a single unit on a single firmware** (n=1). Upgrading
them from "one machine's observation" to "a protocol fact for this model" takes somebody else's
machine and 30 minutes.

**You do not need to open the device, flash anything, install a driver, or write anything to it.**
Entirely read-only.

---

## 1. The four hypotheses to test

| ID | Hypothesis | Condition needed | Covered by one run? |
|---|---|---|---|
| **H1** | Clock wrap point = `1,431,655.765 ms` (= 2³² ticks @ 3 MHz) | Continuous connection for **≥ 23.87 min** | ✅ a 30-minute window necessarily contains one wrap |
| **H2** | `0x05` runs at 250 Hz, clock +4 ms per frame | Any connected state | ✅ ditto |
| **H3** | The status byte is a **bitfield**: b5 = external power present, b2 = charging current flowing (**b4:b3 semantics unknown — do not read it as a stage counter**) | Let the status byte take several values | ✅ capture while charging |
| **H4** | The `0x20` (charge complete) reading sits on a plateau of **3663–3713** | Controller in the full/maintenance state | ⚠️ needs a full battery; otherwise recorded as INCONCLUSIVE |

H1 is the hard requirement: **under 24 minutes you might not encounter a wrap at all**. The script
will honestly write `INCONCLUSIVE` rather than guess.

---

## 2. Three steps

### 2.1 Install dependencies (only hidapi)

```bash
pip install hidapi          # Windows / macOS
# Linux: usually also needs read access to /dev/hidraw* (udev rule or the plugdev group)
```

### 2.2 Plug the controller in, confirm enumeration — **and confirm frames actually arrive**

```bash
python tools/probe_env.py 6
```

Seeing a collection with `usage=0x0005` means enumeration worked. If it is empty: try another cable /
port, or make sure the controller is not asleep.

**Enumeration succeeding does not mean you can read data.** The device must be **activated once** by
the host before it starts pushing `0x05`. While inactive, everything enumerates normally, PnP is all
green, and you read **0 frames**.

| Symptom | Meaning | Fix |
|---|---|---|
| `0 frames`, enumeration fine | Not activated | Launch Steam once (**the login screen is enough, no sign-in needed**), let it see the pad, then **quit it completely** |
| Still 0 frames after activating | The Switch 2 grabbed the controller (USB is charge-only) | **Power the Switch 2 fully off** (standby is not enough), then replug |
| 250 Hz after activating | Normal | Go to 2.3 |

Activation is a **one-shot switch**: afterwards the stream keeps running at 250 Hz even with Steam
closed. **Unplugging reverts it to inactive.**

> **Make sure Steam is really gone first.** On Windows, Steam by default "minimises to tray when
> closing the window", so clicking `X` only hides it; `steam.exe` / `steamwebhelper` keep running in
> the background, still holding the device and able to disturb your capture. Check Task Manager for
> any `steam` process, or right-click the tray icon → **Exit**.
> We hit this ourselves: we thought Steam was closed, but it re-activated the freshly plugged
> controller in the background — so a run that should have read 0 frames read 250 Hz instead.

> This was only established on 2026-10-25 (see [`docs/protocol.en.md`](docs/protocol.en.md) §1.5).
> Without it, anyone reproducing the work concludes the device or the code is broken.

### 2.3 Capture (30 minutes; do not unplug, do not let the PC sleep)

```bash
python tools/repro_capture.py --minutes 30 --fw "<version string you copied from the Switch>" --note "stock cable + official dock"
```

The firmware version is shown under **Switch 2 → Settings → Controllers and Sensors → Update
Controllers** (the read-only channel cannot read it, so copy it by hand). A version seen in public
material is **1.1.5** — **that is not this repo's baseline**: the main unit's firmware version was
never copied down at capture time, and the only read-only identifier we have is `bcdDevice = 0x0201`
(see [`data/DEVICE.md`](data/DEVICE.md)). That makes **any submission carrying an explicit version
number especially valuable** — version differences are the first variable we want to compare.

Example output (**the script prints Chinese; the block below is a translation**):

```
  duration 30.0 min / 449,812 frames / device clock 250.0 Hz (host throughput 249.3 Hz) / lost 0
  status census:
    0x20   39210 frames  reading 3668~3713 (median 3670)  09:42:08→10:12:30
    0x34   401122 frames reading 3539~3727 (median 3601)  09:12:00→09:42:00
    0x3C      9 frames   reading 3727~3727 (median 3727)  09:41:58→09:42:08
  verdicts:
    [PASS        ] clock wrap point = 1,431,655.765 ms (2^32 @ 3 MHz)
                  1 wrap detected, error -3.8 ms (last frame vs theoretical point)
    [PASS        ] status byte is a bitfield: b5=power present, b2=charging current
                  3 non-zero values seen 0x20, 0x34, 0x3C, all consistent
                  note: the "b4:b3 = stage index" hypothesis was refuted by our own data
    [PASS        ] 0x20 (charge complete) reading on the ≈3670 plateau (3663~3713)
```

It also writes `repro_report.json` (device fingerprint hash, two-way wrap timing, status census,
verdicts) to the current directory.

---

## 3. Three capture scenarios (pick by what you want to verify)

| Scenario | How | Verifies | Duration |
|---|---|---|---|
| **A. Leave it charging** (default, easiest) | Plug in USB at any level (below 80 % is better), run the script | H1 + H2 + H3 | 30 min |
| **B. Full, idle** | Confirm full on the console first, plug into the PC, start after the LED goes out | H4 (+ H1 incidentally) | 30 min |
| **C. Charge from empty** (most valuable) | Drain to 1 bar or until it powers off → plug into the PC → run the script | low-end reading anchor + full charge curve | 2–3 h |

**C matters most because the low end is completely blank**: every data point in this repo lies
between readings 3,539 and 3,728 — we never actually measured a depleted battery. This run yields
"what the reading is when the battery is nearly empty", the one missing piece for percentage calibration.

It also checks whether two known behaviours reproduce:
① "plugging in only starts charging if depleted" (a full controller just rebuilds the link);
② charging from empty goes through the full `0x34` → `0x3C` (10 s) → `0x20` sequence rather than
landing directly on `0x00`.

---

## 4. Reading your results

| Your result | What it means for this repo |
|---|---|
| H1 `PASS` with error within ±10 ms | The wrap point is a **firmware-level constant**, safe to use for prediction anywhere |
| H1 `PASS` but a clearly different value (e.g. 1,398,101 ms) | The time base is not 3 MHz → our `2³²@3MHz` inference needs revising |
| H1 `FAIL` with the wrap point far below the theoretical value | The counter is not 32-bit, or the divider is not 3000 |
| H2 `FAIL` (e.g. 125 Hz / +8 per frame) | That firmware lowered the report rate; the lost-frame maths must be recalibrated |
| H3 `FAIL` (a non-zero value with b5 = 0, or b2 set on `0x20`) | The bitfield hypothesis is wrong; fall back to "independent enumeration" |
| H4 `FAIL` (e.g. 3900 when full) | The gauge scale varies by batch; the calibration table cannot be hard-coded |
| All `INCONCLUSIVE` | Capture too short or wrong state coverage — rerun and extend |

**A valid result is not "it matches ours", it is "it clearly supports or refutes one claim."**
Refutation is just as valuable; we will change the docs accordingly — this repo has already
self-retracted twice on new data (that `0x20` does not exist, and an exponential-relaxation model).

---

## 5. Please also provide

The script records the device fingerprint automatically (VID/PID/usage, first 12 hex of the SHA1 of
the path). **Please additionally fill in by hand**:

- **Controller firmware version** (`--fw`, required) — Settings → Controllers and Sensors → Update Controllers
- **Console system version** (optional, but helps tell host-side from controller-side changes)
- **Batch / purchase date** (optional, for hardware revisions)
- **Cable + dock model** (`--note`, e.g. "stock cable + official dock", "third-party cable direct to motherboard")
- **Starting battery bars** (0–4, only you can see this)
- Whether any software (Steam / an SDL game) has the controller open and may be claiming it

> Privacy: the script collects **no** system information, makes no network calls and uploads nothing.
> Device paths are stored only as a hash, with no machine name, username or serial number.
> All code can be audited with `python tools/audit_readonly.py`.

---

## 6. What this kit does not do

- ❌ Send any byte to the device (no init commands, no report-mode switching, no rumble)
- ❌ Open `iface1` (vendor bulk), and therefore **cannot** get `0x09`'s 0–9 battery levels / NFC
- ✅ **The IMU is still available**: `0x05` carries all six axes (±8 g / ±2000 dps); `0x09` is not needed
- ❌ Read firmware, or read the SPI calibration block

The cost is clear: **we only have this one public broadcast, `0x05`.** If you have write access,
go for `0x09` to get the battery levels — but for the IMU, `0x05` is already enough.
