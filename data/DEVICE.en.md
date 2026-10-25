# Device & Conditions

> **English** · [中文](DEVICE.md)

> Recorded by **PRX-24hz**

Every conclusion in this repo depends on the conditions below. **If any one is missing, the
comparability of the conclusions degrades.**

---

## 1. Device

| Item | Value | Status |
|---|---|---|
| Model | Nintendo Switch 2 Pro Controller, Hong Kong region **`BBE-008`** | confirmed (label + VID/PID) |
| VID:PID | `0x057E:0x2069` | confirmed |
| Product String | `If_Hid` | confirmed |
| **Controller firmware version** | **Switch reported "up to date" on 2026-10-25; build number not recorded** | ⚠️ partial (see §4) |
| **USB `bcdDevice`** | **`0x0201`** (hidapi `release_number`; readable without sending a command) | ✅ confirmed |
| Hardware batch / origin | `BEE-A-FKC-JXE-C0` / MADE IN CHINA | confirmed (label) |
| Serial number | not collected, not published | readable over the channel, but **deliberately kept out of the repo** |

## 2. Host side (for comparison)

| Item | Value | Status |
|---|---|---|
| Switch 2 system version | TBD | ⬜ optional |
| **Last controller firmware update** | **TBD** | ⬜ to fill (the user recalls an update around mid-October 2026) |
| Behaviour difference before/after that update | unknown | ⬜ cannot downgrade; we can only record that "all observations happened after it" |

> **Why the firmware version matters**: this repo's conclusions (the `0x20` semantics, the 2.9 Hz
> chopping, the 1432 s wrap constant) all come from **one device on one firmware**. If a firmware
> changed the charging strategy, these numbers may not hold on older builds. With a version number,
> others can judge whether their device is covered.

## 3. Topology (as measured)

| Item | Value |
|---|---|
| Cable | stock USB-C data cable |
| Intermediary | **two chained Genesys Logic external hubs** (`VID_05E3 PID_0608` ×2) |
| Host | Windows 11 PC (USB HID, shared non-exclusive handle) |
| Concurrent software | see §6 "Activation" — captures are **independent** of whether software runs, but the **activation step** was done by the **Steam client** (the login screen is enough; no sign-in required) |

**Full device tree** (walked up with `Get-PnpDevice`):

```
Intel USB 3.20 controller (PCI\VEN_8086&DEV_7A60)
└─ USB root hub  (4&2f9de05b&0&0)
   └─ Generic USB hub  VID_05E3 PID_0608 (Genesys Logic)
      └─ Generic USB hub  VID_05E3 PID_0608 (same model again)
         └─ Switch 2 Pro Controller
```

LocationInfo = `0000.0014.0000.003.002.003.000.000.000` (port chain 3.2.3).

> **Why this must be stated**: every capture was taken through **two chained external hubs**. It does
> not affect 250 Hz itself (a USB frame is 1 ms, four times slower than the report rate), but hub
> forwarding adds buffering, so **microsecond-level timing judgements are affected**; a constantly-on
> red LED may also just reflect hub power delivery rather than a direct connection.
> A "direct to motherboard vs through hubs" comparison has not been done — an undeclared timing
> premise of this repo.

**Measured link quality**: 250 Hz with zero dropped frames over 200+ consecutive seconds;
cumulative dropped frames over long monitoring ≈ 0.0006 %.

## 4. How to read the controller firmware version (not available over the read-only channel)

On the Switch 2 console:

```
Settings → Controllers and Sensors → Update Controllers
```

The page shows the current controller firmware version. Copy it into the table above.

(Reading it programmatically requires sending a command, which violates this repo's read-only rule,
so it has to be copied by hand.)

**There is a read-only substitute though: `bcdDevice = 0x0201`.** It comes from the USB device
descriptor and hidapi hands it over as `release_number` — **no command required**:

```python
import hid
for d in hid.enumerate(0x057E, 0x2069):
    print(hex(d["release_number"]))      # 0x201
```

It is **not** the firmware version string shown in the Switch UI, but it is enough to tell whether two
units are the same build. Corroboration: the SDL GUID generated for this device has `01 02` at bytes
`[12:14]` (see [`docs/protocol.md`](../docs/protocol.en.md) §3.1). Public records note HIDMaestro
tagging firmware `1.1.5`, which differs from this unit's `0x0201` — exactly why the distinction needs
spelling out.

## 5. Capture timeline

| Date | Contents |
|---|---|
| 2026-10-24 05:57–07:30 | Full charging cycle, `data/sw2_charge.csv` (4,918 rows) |
| 2026-10-24 all day | State observations: the complete set of six values `0x2C/0x34/0x3C/0x20/0x24/0x00` |
| 2026-10-24 08:27–15:07 | Multiple clock-wrap captures (including one non-wrap reset) |
| 2026-10-24 15:23– | 2.9 Hz chopping maintenance (duty locked at 89–90 %) |
| 2026-10-25 00:09 | Chopping wrapped up by itself: `0x2C` → `0x34` (10 min) → `0x3C` → `0x20` |
| 2026-10-25 07:00–08:00 | Battery-powered load experiments: `data/apex_ab_2026-10-25.csv` / `data/loadtest_2026-10-25.csv` |
| 2026-10-25 07:53 | Raw-HID full stick travel (7,750 frames, radius 1,765 / 1,810) |
| 2026-10-25 08:20 | Trailing 29 bytes characterised: still/shake A/B (20,001 frames) → confirmed IMU |
| 2026-10-25 08:40 | First six-face calibration (127 s, Steam on) → `data/imu_calib_2026-10-25.csv` |
| 2026-10-25 09:20 | Retest with Steam closed (120 s) → `data/imu_calib_2026-10-25_steam_off.csv` |
| 2026-10-25 09:23 | Full hotplug: **63 s of zero data** after replug, then 250 Hz once activated → `data/hotplug_steam_off.csv` |
| 2026-10-25 09:5x | USBPcap capture: all 19 activation commands inside 107 ms → `activate_capture.pcap` (**contains the serial number, not published**) |
| 2026-10-25 10:27 | Formal six-face calibration (100 s / 7 poses, phone level app as reference) → `data/imu_formal_2026-10-25.csv` |

## 6. Activation precondition (the easiest thing to misdiagnose)

The device does **not** start sending just because it is plugged in. While inactive: enumeration is
normal, PnP is all green, and you read **0 frames**.

| State | Behaviour |
|---|---|
| Inactive (fresh plug-in, or after a replug) | 0 frames; buttons do not wake it |
| After host-side activation | **Straight to 250 Hz**, no ramp |
| Activating software closed afterwards | **Stream continues** (250.2 Hz measured after Steam fully exited) |
| Unplug and replug | Back to inactive |

Activation commands go over the **`MI_01` vendor interface**, not the HID interface `MI_00` — which is
why nothing written at the HID layer gets through. Sequence and semantics:
[`docs/discovery-imu.en.md`](../docs/discovery-imu.en.md) §8.1.

> This repo **does not implement activation**. Every capture comes from a device that Steam had
> already activated. That has to be stated in the method, or anyone reproducing the work gets
> 0 frames and blames the hardware.

**Activation path (measured)**: launching Steam is enough to take the controller over —
**sitting on the login screen, not signed in, works**; and the stream survives quitting Steam.
"Taken over before sign-in" means the acting party is Steam's local controller service, not account
settings.

**Untested**: whether other software (SDL games, HIDMaestro, the Linux `hid-nintendo` driver) can also
activate it; whether disabling "controller support" in Steam still results in a takeover (**that toggle
was not found in the current Steam build** — possibly removed, or hidden per device); whether different
Steam versions behave the same. **The activation step hangs off a self-updating third-party client —
that is the ceiling on this repo's reproducibility.**

> **A corroborating observation**: Steam's "Controller → Controller Layouts → Test Input" page responds
> to button presses in real time, which shows Steam really has the device open and reading it. That page
> also displays the **serial number** — **do not screenshot it publicly**; it is the same class of risk
> as the serial number in the pcap's device descriptor.

## 7. Citation requirements

When citing this repo, include **firmware version + topology + the CSVs above**, not just the
conclusions. If your firmware differs, run `tools/repro_capture.py` first
(see [`REPRODUCE.en.md`](../REPRODUCE.en.md)) before comparing.
