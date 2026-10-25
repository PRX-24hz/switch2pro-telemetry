#!/usr/bin/env python3
"""摇杆行程与限位探针：抓取各轴极值、最大偏转半径，判断是否触及 12 bit 端点。

用途：区分「硬件/机械限位」与「游戏死区」——必须在**裸 HID、无游戏运行**时使用，
因为游戏会施加自己的死区与输入缩放。

用法：
    python tools/stick_range.py --secs 35
    然后按提示：先静止 3 秒（取中点），再把每个摇杆推到底并绕圈。

只读：enumerate / open_path / read / close。
"""
from __future__ import annotations

import argparse
import math
import pathlib
import statistics
import sys
import time

VID, PID = 0x057E, 0x2069
FULL = 4095          # 12 bit 满量程


def _hid():
    try:
        import hid
        return hid
    except ImportError:
        here = pathlib.Path(__file__).resolve()
        lib = next((p / "_pylibs" for p in here.parents if (p / "_pylibs").is_dir()), None)
        if lib is None:
            raise
        sys.path.insert(0, str(lib / ("py%d%d" % sys.version_info[:2])))
        import hid
        return hid


def unpack(b):
    """12 bit 双摇杆解包（偏移按含报告 ID 的 buffer 计）。"""
    lx = b[11] | ((b[12] & 0x0F) << 8)
    ly = (b[12] >> 4) | (b[13] << 4)
    rx = b[14] | ((b[15] & 0x0F) << 8)
    ry = (b[15] >> 4) | (b[16] << 4)
    return lx, ly, rx, ry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=35.0)
    ap.add_argument("--rest", type=float, default=3.0, help="开头取中点的静止时长")
    a = ap.parse_args()

    hid = _hid()
    devs = [d for d in hid.enumerate(VID, PID)
            if (d.get("usage_page") or 0) == 0x01 and (d.get("usage") or 0) in (0x04, 0x05)]
    if not devs:
        print("[FAIL] 未发现设备")
        return 2
    h = hid.device()
    h.open_path(devs[0]["path"])

    print("阶段 1：请松手静止 %.0f 秒（取中点）…" % a.rest, flush=True)
    t0 = time.time()
    rest = []
    while time.time() - t0 < a.rest:
        b = h.read(64, 200)
        if b and b[0] == 0x05:
            rest.append(unpack(b))

    if not rest:
        print("[FAIL] 静止段没读到帧")
        h.close()
        return 2
    cx = statistics.median(p[0] for p in rest)
    cy = statistics.median(p[1] for p in rest)
    cx2 = statistics.median(p[2] for p in rest)
    cy2 = statistics.median(p[3] for p in rest)
    print("  中点（中位数）：左(%d, %d)   右(%d, %d)" % (cx, cy, cx2, cy2), flush=True)

    print("\n阶段 2：把左摇杆推到底并绕一圈，再对右摇杆做同样动作（%.0f 秒）…"
          % (a.secs - a.rest), flush=True)
    t1 = time.time()
    ext = {"lx": [FULL, 0], "ly": [FULL, 0], "rx": [FULL, 0], "ry": [FULL, 0]}
    rmax = {"L": 0.0, "R": 0.0}
    n = 0
    ang_hist = {"L": 0, "R": 0}
    while time.time() - t1 < a.secs - a.rest:
        b = h.read(64, 200)
        if not b or b[0] != 0x05:
            continue
        n += 1
        lx, ly, rx, ry = unpack(b)
        for k, v in (("lx", lx), ("ly", ly), ("rx", rx), ("ry", ry)):
            if v < ext[k][0]:
                ext[k][0] = v
            if v > ext[k][1]:
                ext[k][1] = v
        rl = math.hypot(lx - cx, ly - cy)
        rr = math.hypot(rx - cx2, ry - cy2)
        if rl > rmax["L"]:
            rmax["L"] = rl
        if rr > rmax["R"]:
            rmax["R"] = rr
        if rl > 1500:
            ang_hist["L"] += 1
        if rr > 1500:
            ang_hist["R"] += 1
    h.close()

    print("\n" + "=" * 66)
    print("采样 %d 帧" % n)
    print("%-6s %10s %10s %8s %8s" % ("轴", "最小", "最大", "跨度", "中点"))
    for k, label in (("lx", "左 X"), ("ly", "左 Y"), ("rx", "右 X"), ("ry", "右 Y")):
        lo, hi = ext[k]
        print("%-6s %10d %10d %8d %8d" % (label, lo, hi, hi - lo, (lo + hi) // 2))
    print("\n最大偏转半径（相对中点，理论满偏 %d）：" % (FULL // 2))
    for side in ("L", "R"):
        r = rmax[side]
        print("  %s: %7.0f counts   = %5.1f%% 满量程" % (side, r, r / (FULL / 2) * 100))
    print("\n触及端点判断：")
    for k, label in (("lx", "左X"), ("ly", "左Y"), ("rx", "右X"), ("ry", "右Y")):
        lo, hi = ext[k]
        print("  %s  低端 %4d %s   高端 %4d %s"
              % (label, lo, "← 触 0" if lo <= 8 else "        ",
                 hi, "← 触 4095" if hi >= FULL - 8 else ""))
    print("=" * 66)
    print("说明：若各轴都到不了 0/4095 且半径 ≈ 同一值，则摇杆做的是**圆周运动**，")
    print("      单轴极值天然小于 2048（几何限制，不是故障）。")
    print("      若半径明显 < 2048，才说明是机械限位或固件缩放。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
