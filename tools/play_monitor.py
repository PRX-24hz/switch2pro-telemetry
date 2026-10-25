#!/usr/bin/env python3
"""游玩期间监视器：250Hz 记录按键活动、状态占空比、读数的「活跃 vs 空闲」差异。

用途（回答三个问题）：
  1. 真实负载会不会把设备从维持斩波拉回 `0x34` 真充电？
  2. 按键活动时读数是否系统性下降（IR 压降）？
  3. 长时间游玩时 `0x05` 流是否稳定（Steam 共存、掉帧、回绕）。

用法：
    python tools/play_monitor.py --minutes 40

只读：enumerate / open_path / read / close。
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import time
from datetime import datetime

VID, PID = 0x057E, 0x2069
NAMES = {0x00: "无外部供电", 0x20: "充电完成", 0x24: "维持脉冲", 0x2C: "中间态",
         0x34: "充电中", 0x3C: "完成前瞬态"}


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=40.0)
    ap.add_argument("--window", type=float, default=60.0, help="每行输出间隔（秒）")
    ap.add_argument("--csv", default="", help="可选：把每行指标写入 CSV")
    a = ap.parse_args()

    hid = _hid()
    devs = [d for d in hid.enumerate(VID, PID)
            if (d.get("usage_page") or 0) == 0x01 and (d.get("usage") or 0) in (0x04, 0x05)]
    if not devs:
        print("[FAIL] 未发现设备")
        return 2
    h = hid.device()
    h.open_path(devs[0]["path"])
    print("开始监视 %g 分钟（250 Hz）— 你现在可以开始玩，输出每 %.0f 秒一行\n"
          % (a.minutes, a.window), flush=True)
    cf = cw = None
    if a.csv:
        import csv as _csv
        cf = open(a.csv, "w", newline="", encoding="utf-8")
        cw = _csv.writer(cf)
        cw.writerow(["t", "elapsed_s", "frames", "status_top", "btn_pct",
                     "mv_mean", "mv_min", "mv_max", "mv_first", "mv_last",
                     "slope_per_min", "status_changes", "wraps", "lost",
                     "lx_min", "lx_max", "ly_min", "ly_max",
                     "rx_min", "rx_max", "ry_min", "ry_max"])

    t_end = time.time() + a.minutes * 60
    bucket = {"n": 0, "st": {}, "btn_on": 0,
              "mv_on": [], "mv_off": [], "act_secs": set(),
              "mv_first": None, "mv_last": None, "mv_all": [], "st_chg": 0,
              "stk": {"lx": [9999, -1], "ly": [9999, -1],
                      "rx": [9999, -1], "ry": [9999, -1]}}
    prev_clock = None
    wraps = 0
    lost = 0
    seen_status = set()
    last_status = None
    b0 = time.time()
    last_print = b0

    def flush():
        nonlocal bucket
        secs = time.time() - b0
        n = bucket["n"]
        if not n:
            return
        st_txt = "/".join("0x%02X:%.0f%%" % (k, 100 * v / n)
                          for k, v in sorted(bucket["st"].items(), key=lambda kv: -kv[1])[:3])
        on = bucket["mv_on"]
        off = bucket["mv_off"]
        d = (statistics.mean(on) - statistics.mean(off)) if on and off else None
        mv_all = bucket["mv_all"]
        mean_mv = statistics.mean(mv_all) if mv_all else float("nan")
        f, l = bucket["mv_first"], bucket["mv_last"]
        slope = ((l - f) / secs * 60.0) if (f is not None and l is not None and secs > 5) else float("nan")
        stk = bucket["stk"]
        stk_txt = " 摇杆 L%d~%d/%d~%d R%d~%d/%d~%d" % (
            stk["lx"][0], stk["lx"][1], stk["ly"][0], stk["ly"][1],
            stk["rx"][0], stk["rx"][1], stk["ry"][0], stk["ry"][1]) if stk["lx"][1] >= 0 else ""
        print("[%s] %4.0fs 帧=%5d 状态=%s 键=%.1f%% 读数 均=%.0f(%d~%d) 斜率=%+.2f/min%s"
              % (datetime.now().strftime("%H:%M:%S"), secs, n, st_txt,
                 100 * bucket["btn_on"] / n, mean_mv,
                 min(mv_all) if mv_all else 0, max(mv_all) if mv_all else 0, slope, stk_txt),
              flush=True)
        if cw:
            cw.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), round(secs, 1), n,
                         st_txt, round(100 * bucket["btn_on"] / n, 2), round(mean_mv, 1),
                         min(mv_all) if mv_all else "", max(mv_all) if mv_all else "",
                         f, l, round(slope, 3) if slope == slope else "",
                         bucket["st_chg"], wraps, lost,
                         stk["lx"][0], stk["lx"][1], stk["ly"][0], stk["ly"][1],
                         stk["rx"][0], stk["rx"][1], stk["ry"][0], stk["ry"][1]])
            cf.flush()
        bucket = {"n": 0, "st": {}, "btn_on": 0, "mv_on": [], "mv_off": [], "act_secs": set(),
                  "mv_first": None, "mv_last": None, "mv_all": [], "st_chg": 0,
              "stk": {"lx": [9999, -1], "ly": [9999, -1],
                      "rx": [9999, -1], "ry": [9999, -1]}}

    fails = 0
    try:
        while time.time() < t_end:
            try:
                b = h.read(64, 200)
            except Exception as e:                  # 拔线/休眠：连续 3 次才算离线
                fails += 1
                if fails >= 3:
                    print("\n[Offline] 设备已断开（连续 %d 次读失败：%s）" % (fails, type(e).__name__), flush=True)
                    break
                time.sleep(0.3)
                continue
            if not b:
                fails += 1
                if fails >= 30:
                    print("\n[Offline] 连续 30 次读超时，结束", flush=True)
                    break
                continue
            fails = 0
            if b[0] != 0x05:
                continue
            st = b[0x22]
            mv = int.from_bytes(b[0x20:0x22], "little")
            btn = int.from_bytes(b[5:9], "little")
            clk = int.from_bytes(b[1:5], "little")

            # 12bit 双摇杆解包（偏移按含报告 ID 的 buffer 计：左 11..13，右 14..16）
            lx = b[11] | ((b[12] & 0x0F) << 8)
            ly = (b[12] >> 4) | (b[13] << 4)
            rx = b[14] | ((b[15] & 0x0F) << 8)
            ry = (b[15] >> 4) | (b[16] << 4)
            k = bucket["stk"]
            for nm, v in (("lx", lx), ("ly", ly), ("rx", rx), ("ry", ry)):
                if v < k[nm][0]:
                    k[nm][0] = v
                if v > k[nm][1]:
                    k[nm][1] = v

            if prev_clock is not None:
                if clk < prev_clock and prev_clock - clk > 1000:
                    wraps += 1
                elif clk > prev_clock:
                    lost += max(0, (clk - prev_clock) // 4 - 1)
            prev_clock = clk

            bucket["n"] += 1
            if bucket["mv_first"] is None:
                bucket["mv_first"] = mv
            bucket["mv_last"] = mv
            bucket["mv_all"].append(mv)
            if st != last_status:
                if last_status is not None:       # 状态转移必须立刻可见（可能是 0x20 → 0x2C/0x34）
                    bucket["st_chg"] += 1
                    print("  >>> 状态转移 %s → %s  读数=%d  clock=%s ms  [+%.1fs]"
                          % (NAMES.get(last_status, "0x%02X" % last_status),
                             NAMES.get(st, "0x%02X" % st), mv, format(clk, ","),
                             time.time() - b0), flush=True)
                last_status = st
            bucket["st"][st] = bucket["st"].get(st, 0) + 1
            seen_status.add(st)
            if btn:
                bucket["btn_on"] += 1
                bucket["mv_on"].append(mv)
                bucket["act_secs"].add(int(time.time() - b0))
            else:
                bucket["mv_off"].append(mv)

            if time.time() - last_print >= a.window:
                last_print = time.time()
                flush()
    except KeyboardInterrupt:
        print("\n已中断")
    finally:
        flush()
        if cf:
            try:
                cf.close()
                print("  CSV 已保存：%s" % a.csv, flush=True)
            except Exception:
                pass
        try:
            h.close()
        except Exception:
            pass

    print("\n" + "-" * 60)
    print("结束：状态集合 = %s" % ", ".join("0x%02X(%s)" % (s, NAMES.get(s, "?")) for s in sorted(seen_status)))
    print("时钟回绕 %d 次，累计掉帧 %d" % (wraps, lost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
