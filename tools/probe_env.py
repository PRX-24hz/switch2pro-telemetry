#!/usr/bin/env python3
"""环境探测：确认 Steam 关闭 + 重新插拔后，设备枚举与报告流是否与采集时一致。

回答三个问题：
1. 手柄是否仍以相同 VID/PID、相同 usage_page/usage 暴露（Steam 可能是它工作的前提）
2. 报告 ID 分布是否只有 0x05（若出现 0x09/0x3F 等其他 ID，说明模式已变）
3. 实际报告率与 IMU 字段是否照常（0x31~0x3C 是否有合理的重力读数）

纯只读：enumerate / open_path / read / close。

用法：python probe_env.py [采样秒数，默认 3]
"""
import os, sys, time
from collections import Counter

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


def s16(lo, hi):
    v = lo | (hi << 8)
    return v - 65536 if v >= 32768 else v


def main(secs):
    devs = hid.enumerate(VID, PID)
    print(f"枚举到 {len(devs)} 个 VID=0x{VID:04X} PID=0x{PID:04X} 接口：\n")
    for d in devs:
        print(f"  if={d.get('interface_number')}  usage_page=0x{d.get('usage_page', 0):04X}  "
              f"usage=0x{d.get('usage', 0):04X}  {d.get('product_string') or '-'}")
        print(f"    path={d.get('path')}")

    target = [d for d in devs if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not target:
        print("\n!! 没有 usage_page=0x0001/usage=0x0005 的接口，无法采集 0x05 报告。")
        print("   可能原因：Steam 关闭后手柄换了接口，或需要先按一下手柄唤醒。")
        return 2

    h = hid.device(); h.open_path(target[0]["path"])
    print(f"\n在 {target[0]['path']} 上采样 {secs:g}s ……")
    ids = Counter(); n = 0; t0 = time.time(); samples = []
    try:
        while time.time() - t0 < secs:
            buf = h.read(64, 200)
            if not buf:
                continue
            n += 1
            ids[buf[0]] += 1
            if buf[0] == 0x05 and len(samples) < 5:
                samples.append(list(buf))
    finally:
        try: h.close()
        except Exception: pass

    el = time.time() - t0
    print(f"\n共 {n} 帧 / {el:.2f}s = {n/el:.1f} Hz")
    print("报告 ID 分布：", {f"0x{k:02X}": v for k, v in sorted(ids.items())})

    if 0x05 not in ids:
        print("\n!! 没有收到任何 0x05 报告，环境与采集时不同。")
        return 3

    print("\n0x05 样本（六轴解析值）：")
    print("  wall        ax     ay     az     gx     gy     gz    |a|(g)  status")
    for b in samples:
        v = {nm: s16(b[o], b[o + 1]) for o, nm in AX}
        amag = (v["ax"] ** 2 + v["ay"] ** 2 + v["az"] ** 2) ** 0.5 / 4096
        print(f"  {time.strftime('%H:%M:%S')}  {v['ax']:6d} {v['ay']:6d} {v['az']:6d} "
              f"{v['gx']:6d} {v['gy']:6d} {v['gz']:6d}  {amag:6.3f}   0x{b[0x22]:02X}")

    ok = abs((samples[-1][0x35] | samples[-1][0x36] << 8) % 65536 / 4096 - 1.0) < 0.2 if samples else False
    az = s16(samples[-1][0x35], samples[-1][0x36]) if samples else 0
    print(f"\n判定：报告流正常，az={az} LSB ({az/4096:.3f} g) — "
          f"{'IMU 在，且平放姿态与之前一致' if abs(az/4096-1)<0.2 else 'az 不接近 1g，注意当前姿态或字段已变'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 3.0))
