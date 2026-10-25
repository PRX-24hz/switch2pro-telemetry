#!/usr/bin/env python3
"""IMU 分轴校准采集：连续记录 6 轴原始值 + 绝对墙钟时间戳，供分步动作对照。

纯只读：enumerate / open_path / read / close。

与 imu_tail_probe.py 的区别：
- 带绝对时间戳（HH:MM:SS.mmm），用户口头报「几点几分做了什么」可以直接对齐
- 长时间运行（默认 600s），每行写完立即 flush，允许外部随时读取最新数据
- 降采样到 50Hz（每 5 帧取 1），保留转动峰值足够，文件不至于过大
- 每 10 秒输出一行六轴快照到 stdout，便于从后台日志定位

用法：python imu_calib.py [秒数 默认600] [--hz 50] [--csv 路径]
"""
import os, sys, time, csv, argparse
from datetime import datetime

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

# 六轴：低字节偏移 → (名称, 推断类型)
AXES = [
    (0x31, "ax", "accel"),
    (0x33, "ay", "accel"),
    (0x35, "az", "accel"),
    (0x37, "gx", "gyro"),
    (0x39, "gy", "gyro"),
    (0x3B, "gz", "gyro"),
]
LSB_ACC = 4096.0          # 假设 ±8g 量程


def s16(lo, hi):
    v = lo | (hi << 8)
    return v - 65536 if v >= 32768 else v


def main(seconds, hz, csv_path):
    devs = [d for d in hid.enumerate(VID, PID)
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not devs:
        print("未找到设备"); return 1
    h = hid.device(); h.open_path(devs[0]["path"])

    step = max(1, int(round(250 / hz)))
    cols = ["wall", "t", "ax", "ay", "az", "gx", "gy", "gz", "amag_g"]
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    cw = csv.writer(cf); cw.writerow(cols); cf.flush()

    print(f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "] 校准采集开始：{seconds:g}s @ {hz}Hz → {csv_path}",
          flush=True)
    print("  当前应保持静止，作为平放基线", flush=True)

    t0 = time.time(); n = 0; k = 0; last_beat = -1
    try:
        while time.time() - t0 < seconds:
            buf = h.read(64, 200)
            if not buf or buf[0] != 0x05:
                continue
            n += 1
            if n % step:
                continue
            now = time.time()
            vals = {name: s16(buf[o], buf[o + 1]) for o, name, _ in AXES}
            amag = (vals["ax"] ** 2 + vals["ay"] ** 2 + vals["az"] ** 2) ** 0.5 / LSB_ACC
            cw.writerow([f"{datetime.now():%H:%M:%S.%f}"[:-3], round(now - t0, 3),
                         vals["ax"], vals["ay"], vals["az"],
                         vals["gx"], vals["gy"], vals["gz"], round(amag, 3)])
            cf.flush()
            k += 1
            sec = int(now - t0)
            if sec != last_beat and sec % 10 == 0:
                last_beat = sec
                print(f"  [{datetime.now():%H:%M:%S}] {sec:4d}s  "
                      f"a=({vals['ax']:6d},{vals['ay']:6d},{vals['az']:6d}) |a|={amag:5.2f}g  "
                      f"g=({vals['gx']:6d},{vals['gy']:6d},{vals['gz']:6d})", flush=True)
    finally:
        try: h.close()
        except Exception: pass
        cf.close()

    print(f"[{datetime.now():%H:%M:%S}] 完成：{k} 行 / {n} 帧 → {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float, nargs="?", default=600.0)
    ap.add_argument("--hz", type=float, default=50.0)
    ap.add_argument("--csv", default="imu_calib.csv")
    a = ap.parse_args()
    sys.exit(main(a.seconds, a.hz, a.csv))
