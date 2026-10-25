# `tools/write/` — scripts that DO write to the device (don't run by default)

> **中文** · [Chinese](README.md)

---

## Why this directory exists

This repo's main line is **read-only capture**: every script under `tools/`, and **every conclusion**,
works without sending a single byte to the device.

The three scripts here **do write**. They exist to answer one specific question:

> With Steam closed, why does the controller send zero `0x05` frames?

Because the device needs to be **activated once** (see
[`docs/discovery-imu.en.md` §8.1](../../docs/discovery-imu.en.md)). To confirm that — and to try
reproducing the activation ourselves — we sent reports to the device. **Everything sent is a byte-for-byte
replay of what USBPcap captured**; no new commands were constructed. It is still a write.

By this repo's own rule, such code cannot sit next to the read-only tools — **mix them together and
"read-only" becomes a slogan nobody can check.** So they live here, isolated, and
`tools/audit_readonly.py` lists them separately.

## Inventory

| Script | What it does | Outcome |
|---|---|---|
| `send_ctrl.py` | Sends one output report via control transfer (`HidD_SetOutputReport`) | Rejected by the OS layer every time (`err=87` / `err=31`) |
| `send_activation.py` | Sends one report via `hid.write()` | Returns `-1` (interrupt OUT demands a full 64-byte packet) |
| `replay_activation.py` | Replays the full 19-command activation sequence, trying each candidate report ID | All 16 candidate IDs failed |

**None of the three managed to activate the device.** The conclusion: the command channel is the `MI_01`
vendor interface, and HID-level writes can't reach it; doing it yourself needs a WinUSB binding (Zadig).
This repo **does not** provide that path — the cost outweighs the benefit. Activate once with existing
software, close it, and the stream keeps running.

## If you really want to run them

```bash
cd tools/write
python replay_activation.py            # try each report ID in turn
```

Read the header comment first. Known risk: a wrong packet can make the controller unresponsive until you
**unplug and replug** (this was tested). It will not brick the device, touch firmware, or persist any
setting — but **do not** edit the packet contents without understanding them.

## Why not just delete them

Because the failures are part of the finding. "You can't get in through the HID layer" and "it has to go
through the vendor interface" cost us hours to establish. Deleting the scripts deletes the evidence.
Keeping them here, clearly labelled and separately audited, is more honest than pretending we never tried.

---

> Audit: `python tools/audit_readonly.py` prints the write-call inventory for this directory and applies a
> strict verdict to the read-only area.
