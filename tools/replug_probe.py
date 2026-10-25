#!/usr/bin/env python3
"""重新插拔捕获：记录插回瞬间的 250Hz 原始帧，判定设备进入哪个状态。

用途：回答「拔插能否退出 0x20 维持态」「满电重插会不会再充一轮」。

用法：
    python tools/replug_probe.py            # 若已插着，会先等你拔掉
    python tools/replug_probe.py --secs 6   # 插回后录 6 秒

只读：仅 enumerate / open_path / read / close，不发送任何字节。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from datetime import datetime

VID, PID = 0x057E, 0x2069
NAMES = {0x00: "无外部供电", 0x20: "充电完成(维持态)", 0x24: "收尾涓流",
         0x2C: "插上初期握手", 0x34: "充电中(有电流)", 0x3C: "完成前瞬态"}


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


def find(hid):
    for d in hid.enumerate(VID, PID):
        if (d.get("usage_page") or 0) == 0x01 and (d.get("usage") or 0) in (0x04, 0x05):
            return d
    return None


def wait_for(hid, want_present: bool, timeout: float):
    """返回 (ok, dev)。ok 表示状态已达期望——注意「等待消失」时 dev 就是 None，
    不能拿返回值本身当真假判断（这里踩过一次）。"""
    t_end = time.time() + timeout
    while time.time() < t_end:
        d = find(hid)
        if (d is not None) == want_present:
            return True, d
        time.sleep(0.05)
    return False, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=4.0, help="插回后录制秒数")
    ap.add_argument("--wait", type=float, default=120.0, help="等待拔/插的超时")
    ap.add_argument("--follow", type=float, default=0.0, help="抓完首帧后继续跟踪 N 分钟占空比")
    a = ap.parse_args()

    hid = _hid()
    dev = find(hid)
    if dev:
        print("[1] 设备当前在位，请现在拔掉 USB 线…", flush=True)
        ok, _ = wait_for(hid, False, a.wait)
        if not ok:
            print("[FAIL] 等不到拔出（超时）")
            return 2
        print("    已确认拔出 %s" % datetime.now().strftime("%H:%M:%S.%f")[:-3], flush=True)

    print("[2] 现在插回…（每 50ms 轮询）", flush=True)
    t_before = time.time()
    ok, dev = wait_for(hid, True, a.wait)
    t_appear = time.time()
    if not ok or dev is None:
        print("[FAIL] 等不到设备出现（超时）")
        return 2
    print("    已重新出现 %s（枚举耗时 %.0f ms）"
          % (datetime.now().strftime("%H:%M:%S.%f")[:-3], (t_appear - t_before) * 1000), flush=True)

    h = None
    for _ in range(80):                                   # 刚枚举完可能尚不可打开，重试
        try:
            h = hid.device()
            h.open_path(dev["path"])
            break
        except Exception:
            h = None
            time.sleep(0.05)
    if h is None:
        print("[FAIL] 打不开句柄（可能被其他软件独占）")
        return 2

    t0 = time.perf_counter()
    frames = []
    while time.perf_counter() - t0 < a.secs:
        b = h.read(64, 200)
        if not b:
            continue
        frames.append((time.perf_counter() - t0,
                       int.from_bytes(b[1:5], "little"),
                       int.from_bytes(b[0x20:0x22], "little"),
                       b[0x22]))
    # ---- 可选：继续跟踪占空比，看这轮顶充从多少开始、怎么爬 ----
    if a.follow > 0:
        print("-" * 58)
        print("继续跟踪 %.0f 分钟占空比（每 30s 一行）…" % a.follow, flush=True)
        t_f = time.perf_counter()
        win = {}
        nxt = t_f + 30
        while time.perf_counter() - t_f < a.follow * 60:
            b = h.read(64, 200)
            if not b:
                continue
            win[b[0x22]] = win.get(b[0x22], 0) + 1
            if time.perf_counter() >= nxt:
                nxt += 30
                tot = sum(win.values())
                if tot:
                    txt = "/".join("0x%02X:%.0f%%" % (k, 100 * v / tot)
                                   for k, v in sorted(win.items(), key=lambda kv: -kv[1]))
                    mv = int.from_bytes(b[0x20:0x22], "little")
                    print("  +%4.1fmin  %s  读数=%d" % ((time.perf_counter() - t_f) / 60, txt, mv), flush=True)
                win.clear()
        h.close()

    if a.follow <= 0:
        h.close()

    if not frames:
        print("[FAIL] 插回后 4 秒内没有任何输入报告")
        return 2

    print("-" * 58)
    print("共 %d 帧 / %.2f 秒 / 平均 %.0f Hz" % (len(frames), a.secs, len(frames) / a.secs))
    for k in range(min(3, len(frames))):
        t, c, r, s = frames[k]
        print("  帧%d  +%6.1fms  clock=%s  状态=0x%02X %-18s 读数=%d"
              % (k, t * 1000, format(c, ","), s, NAMES.get(s, "未知"), r))

    # 状态时间线（只在变化时打印）
    print("  状态时间线：", end="")
    prev = None
    for t, _, _, s in frames:
        if s != prev:
            print(" 0x%02X@%.0fms" % (s, t * 1000), end="")
            prev = s
    print()

    first = frames[0]
    seq = []
    prev = None
    for _, _, _, s in frames:
        if s != prev:
            seq.append(s)
            prev = s

    print("-" * 58)
    print("首帧状态：0x%02X（%s）" % (first[3], NAMES.get(first[3], "未知")))
    print("序列：%s" % " → ".join("0x%02X" % s for s in seq))
    if first[3] == 0x20:
        print("判定：维持态**跨拔插保持** → 0x20 只能靠放电到阈值或断电退出")
    elif first[3] == 0x2C:
        print("判定：拔插触发**握手** → 满电也会走一轮 0x2C，之后看是否进 0x34")
    elif first[3] == 0x34:
        print("判定：**插上即充电** → 0x20 只是短暂标志，不是吸收态")
    elif first[3] == 0x00:
        print("判定：首帧即判定无外部供电（可能供电尚未就绪）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
