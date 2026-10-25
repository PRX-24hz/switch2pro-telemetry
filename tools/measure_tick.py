#!/usr/bin/env python3
"""测量设备时基：把「0x05 的毫秒计数」与主机单调时钟做线性拟合，反推 tick 频率与真实回绕周期。

为什么需要它
------------
本仓库原先只验证了「回绕点落在 1,431,655.765（设备毫秒）」——那是**计数器自身的量程**，
不等于**物理周期**。若设备的 1 "ms" 比真毫秒略慢，物理回绕周期就会长于 1,431.6558 s，
长时间预测会漂。本工具直接测这个比值（ppm 级）。

用法
----
    python tools/measure_tick.py --minutes 10

输出
----
    Δ设备/Δ主机 = 0.99992   → -80 ppm
    反推 tick    = 2.99976 MHz
    物理回绕周期 = 1,431.77 s（设备毫秒量程 1,431.6558 s）

只读：仅 enumerate / open_path / read / close。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import statistics
import sys
import time

VID, PID = 0x057E, 0x2069
WRAP_MS = 2 ** 32 / 3e6 * 1000          # 1,431,655.765


def _hid():
    try:
        import hid
        return hid
    except ImportError:
        # 向上找 _pylibs（本文件可能在 tools/ 里，也可能被拷到别处）
        here = pathlib.Path(__file__).resolve()
        cand = [p / "_pylibs" for p in here.parents]
        lib = next((c for c in cand if c.is_dir()), None)
        if lib is None:
            raise
        sys.path.insert(0, str(lib / ("py%d%d" % sys.version_info[:2])))
        import hid
        return hid


def open_dev(hid):
    devs = [d for d in hid.enumerate(VID, PID)
            if (d.get("usage_page") or 0) == 0x01 and (d.get("usage") or 0) in (0x04, 0x05)]
    if not devs:
        return None
    h = hid.device()
    h.open_path(devs[0]["path"])
    return h


def sample(h, interval=5.0, minutes=10.0, out=None):
    """返回 [(host_perf, clock_unwrapped), ...]。自动处理回绕，绝不无符号相减。"""
    pts = []
    span = 0
    prev = None
    t_end = time.perf_counter() + minutes * 60
    while time.perf_counter() < t_end:
        b = h.read(64, 500)
        if not b:
            time.sleep(interval)
            continue
        c = int.from_bytes(b[1:5], "little")
        # 回绕处理：把当前 epoch 的 clock 折算成累计值
        if prev is not None and c < prev and prev - c > 1000:
            span += WRAP_MS
        prev = c
        t = time.perf_counter()
        pts.append((t, span + c))
        if out:
            out.write("%.3f,%d\n" % (t, int(span + c)))
            out.flush()
        time.sleep(interval)
    return pts


def fit(pts):
    """最小二乘斜率：Δclock / Δhost。返回 (slope, ppm, tick_hz, wrap_s)。"""
    n = len(pts)
    if n < 3:
        return None
    t0 = pts[0][0]
    xs = [(t - t0) for t, _ in pts]
    ys = [(c - pts[0][1]) / 1000.0 for _, c in pts]   # 设备毫秒 → 秒，与主机秒同量纲
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den
    ppm = (slope - 1.0) * 1e6
    tick = 3e6 * slope
    return slope, ppm, tick, 2 ** 32 / tick


def main():
    ap = argparse.ArgumentParser(description="测量 Switch 2 Pro 的时基频率（只读）")
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--interval", type=float, default=5.0, help="采样间隔（秒）")
    ap.add_argument("--csv", help="原始 (perf, clock) 落盘路径")
    a = ap.parse_args()

    hid = _hid()
    h = open_dev(hid)
    if not h:
        print("[FAIL] 未发现 0x057E:0x2069")
        return 2
    out = open(a.csv, "w", encoding="utf-8") if a.csv else None
    if out:
        out.write("host_perf,clock_unwrapped\n")
    print("采样 %g 分钟（每 %gs 一点）…" % (a.minutes, a.interval), flush=True)
    try:
        pts = sample(h, a.interval, a.minutes, out)
    finally:
        try:
            h.close()
        except Exception:
            pass
        if out:
            out.close()

    r = fit(pts)
    if not r:
        print("[FAIL] 样本过少")
        return 1
    slope, ppm, tick, wrap_s = r
    span = pts[-1][0] - pts[0][0]
    print("-" * 56)
    print("采样 %d 点 / %.1f 秒" % (len(pts), span))
    print("Δ设备/Δ主机 = %.7f   → %+.0f ppm" % (slope, ppm))
    print("反推 tick   = %.5f MHz" % (tick / 1e6))
    print("物理回绕周期 = %.3f s   （设备毫秒量程 1431.656 s）" % wrap_s)
    print("每 epoch 相对预测漂移 = %+.0f ms" % ((wrap_s - WRAP_MS / 1000) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
