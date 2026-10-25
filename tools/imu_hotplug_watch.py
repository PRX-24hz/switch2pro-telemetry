#!/usr/bin/env python3
"""热插拔监听：自动重连，完整记录「拔掉 → 插回」的全过程。

普通探针在设备拔出后句柄失效、直接退出，看不到重连。本脚本用状态机处理：
- CONNECTED：持续读 0x05，超过 STALE 秒没有报告就判定掉线
- DISCONNECTED：每秒重新枚举一次，找到就重开

输出（CSV）：每个采样点的 wall/t/ax..gz/rate；另打印事件日志。
纯只读：enumerate / open_path / read / close。

用法：python imu_hotplug_watch.py [秒数 默认120] [--csv 路径] [--stale 1.0]
"""
import os, sys, time, csv, argparse
from datetime import datetime
from collections import deque

_here = os.path.dirname(os.path.abspath(__file__))
_tag = "py%d%d" % sys.version_info[:2]
for _base in (_here,
              os.path.dirname(_here),
              os.path.dirname(os.path.dirname(os.path.dirname(_here)))):
    _p = os.path.join(_base, "_pylibs", _tag)
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
        break
try:
    import hid
except ImportError:
    sys.exit("hidapi 不可用")

VID, PID = 0x057E, 0x2069
AX = [(0x31, "ax"), (0x33, "ay"), (0x35, "az"), (0x37, "gx"), (0x39, "gy"), (0x3B, "gz")]


def s16(b, o):
    v = b[o] | (b[o + 1] << 8)
    return v - 65536 if v >= 32768 else v


def find():
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            return d
    return None


def main(seconds, csv_path, stale):
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    cw = csv.writer(cf)
    cw.writerow(["wall", "t", "event", "rate_hz"] + [n for _, n in AX] + ["amag_g"])
    cf.flush()

    def emit(t, event, rate, buf=None):
        row = [f"{datetime.now():%H:%M:%S.%f}"[:-3], round(t, 3), event, round(rate, 1)]
        if buf:
            v = {n: s16(buf, o) for o, n in AX}
            amag = (v["ax"] ** 2 + v["ay"] ** 2 + v["az"] ** 2) ** 0.5 / 4096
            row += [v[n] for _, n in AX] + [round(amag, 3)]
        else:
            row += [""] * 7
        cw.writerow(row)
        cf.flush()

    t0 = time.time()
    print(f"[{datetime.now():%H:%M:%S}] 热插拔监听开始（{seconds:g}s，掉线判定 {stale}s）", flush=True)
    print("  现在可以拔手柄了", flush=True)

    h = None
    last_data = 0.0
    win = deque()
    state = "init"
    n_total = 0
    seg_start = None
    segments = []

    try:
        while time.time() - t0 < seconds:
            now = time.time()
            if h is None:
                d = find()
                if d:
                    try:
                        h = hid.device()
                        h.open_path(d["path"])
                        state = "connected"
                        last_data = now
                        seg_start = now
                        emit(now - t0, "CONNECT", 0)
                        print(f"  [{datetime.now():%H:%M:%S}] ++ 已连接", flush=True)
                    except Exception as e:
                        h = None
                        emit(now - t0, "OPEN_FAIL", 0)
                else:
                    if state != "disconnected":
                        state = "disconnected"
                        emit(now - t0, "DISCONNECTED", 0)
                        print(f"  [{datetime.now():%H:%M:%S}] -- 设备不在（重新枚举中）", flush=True)
                    time.sleep(0.5)
                continue

            # 已连接：读数据
            try:
                buf = h.read(64, 100)
            except Exception:
                buf = None
                try: h.close()
                except Exception: pass
                if seg_start is not None:
                    segments.append((seg_start, now))
                h = None
                emit(now - t0, "READ_ERROR", 0)
                print(f"  [{datetime.now():%H:%M:%S}] -- 读取出错，句柄失效", flush=True)
                continue

            if buf and buf[0] == 0x05:
                last_data = now
                n_total += 1
                win.append(now)
                while win and now - win[0] > 1.0:
                    win.popleft()
                if n_total % 25 == 0:          # 每 0.1s 落一行
                    emit(now - t0, "DATA", len(win), buf)
            elif now - last_data > stale:
                # 超时太久 → 判定掉线
                try: h.close()
                except Exception: pass
                if seg_start is not None:
                    segments.append((seg_start, now))
                h = None
                emit(now - t0, "STALE", 0)
                print(f"  [{datetime.now():%H:%M:%S}] -- {stale}s 无数据，判定掉线", flush=True)
    finally:
        if h:
            try: h.close()
            except Exception: pass
        cf.close()

    print(f"\n[{datetime.now():%H:%M:%S}] 结束：共 {n_total} 帧 0x05 → {csv_path}", flush=True)
    if segments:
        print("  有效数据区间：")
        for a, b in segments:
            print(f"    {a-t0:7.2f}s ~ {b-t0:7.2f}s  ({b-a:5.2f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float, nargs="?", default=120.0)
    ap.add_argument("--csv", default="hotplug.csv")
    ap.add_argument("--stale", type=float, default=1.0)
    a = ap.parse_args()
    sys.exit(main(a.seconds, a.csv, a.stale))
