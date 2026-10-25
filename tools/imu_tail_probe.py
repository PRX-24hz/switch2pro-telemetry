#!/usr/bin/env python3
"""采集 0x05 报告尾部 0x23~0x3F 的逐字节原始值，用于「晃动 vs 静止」IMU A/B 对照。
纯只读：enumerate / open_path / read / close，不写设备。

设计：连续采集 N 秒，每帧把 0x23~0x3F（含状态 0x22、读数 0x20 作参照）写成 CSV。
用户流程：先静止 ~10s → 拿起大幅晃动 ~30s → 放回静止 ~10s。
脚本会在屏幕上一路打印「已采 s 秒」，方便用户踩点。

用法：python imu_tail_probe.py [秒数，默认 60] [--csv 输出路径]
"""
import os, sys, time, csv, argparse
from datetime import datetime

# hidapi 兜底：依次尝试 tools/_pylibs、仓库根/_pylibs、工作目录根/_pylibs
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
TAIL_LO = 0x23          # 采集起点（含）
TAIL_HI = 0x3F          # 采集终点（含，64 字节末字节）


def main(seconds: float, csv_path: str) -> int:
    devs = [d for d in hid.enumerate(VID, PID)
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not devs:
        print("未找到设备"); return 1
    h = hid.device(); h.open_path(devs[0]["path"])

    cols = ["t", "status", "gauge"] + ["0x%02X" % o for o in range(TAIL_LO, TAIL_HI + 1)]
    cf = None; cw = None
    if csv_path:
        cf = open(csv_path, "w", newline="", encoding="utf-8")
        cw = csv.writer(cf); cw.writerow(cols)

    print(f"[{datetime.now():%H:%M:%S}] 开始采集尾部 0x{TAIL_LO:02X}~0x{TAIL_HI:02X}，共 {seconds:g}s，"
          "请按「静止10s→晃动30s→静止10s」操作", flush=True)

    t0 = time.time(); n = 0; last_beat = -1
    try:
        while time.time() - t0 < seconds:
            buf = h.read(64, 200)
            if not buf or buf[0] != 0x05:
                continue
            st = buf[0x22]
            mv = int.from_bytes(buf[0x20:0x22], "little")
            row = [round(time.time() - t0, 3), f"0x{st:02X}", mv]
            row += [buf[o] for o in range(TAIL_LO, TAIL_HI + 1)]
            if cw:
                cw.writerow(row)
            n += 1
            sec = int(time.time() - t0)
            if sec != last_beat and sec % 5 == 0:
                last_beat = sec
                print(f"  [{datetime.now():%H:%M:%S}] 已采 {sec}s / {seconds:g}s  "
                      f"(帧数 {n}, 状态 0x{st:02X}, 读数 {mv})", flush=True)
    finally:
        try: h.close()
        except Exception: pass
        if cf:
            cf.close()

    print(f"[{datetime.now():%H:%M:%S}] 完成：{n} 帧 → {csv_path or '(未写文件)'}", flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float, nargs="?", default=60.0)
    ap.add_argument("--csv", default="")
    a = ap.parse_args()
    sys.exit(main(a.seconds, a.csv))
