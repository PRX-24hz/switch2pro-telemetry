#!/usr/bin/env python3
"""向设备发送 HID 输出报告，用于验证激活命令。

⚠️ 这是本仓库第一个会【写】设备的工具。只发从抓包里原样提取的报文，不构造新命令。
   发送内容来自 USBPcap 抓到的 Steam 激活序列，`data[0]` 是报告 ID，原样回放。

用法：
  python send_activation.py <hex 报文> [--read 8] [--repeat 1]
  python send_activation.py --list            # 列出内置的候选报文

每条报文发送后立刻读 N 秒，统计收到的 0x05 帧数与速率，用来判断是否被激活。
"""
import os, sys, time, argparse
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

# 从 steam_capture.pcap 原样提取（t=2.929~2.930，激活前最后几条）
CANDIDATES = {
    "mode_27": "0c 91 00 04 00 04 00 00 27 00 00 00",   # subcmd 0x04, 报告模式 0x27
    "imu_on":  "03 91 00 0d 00 08 00 00 01 00 ff ff",   # subcmd 0x0D, 使能 IMU
    "imu_on_ack": "03 01 00 0d 00 f8 00 00 01 00 00 00",
    "led_0a":  "03 91 00 0a 00 04 00 00 05 00 00 00",
    "led_0c":  "01 91 00 0c 00 00 00 00",
    "vib_08":  "0a 91 00 08 00 14 00 00 01 ff ff ff ff ff ff ff",
    "info_02": "0c 91 00 02 00 04 00 00 27 00 00 00",
    "hand_01": "02 91 00 01 00 08 00 00 00 00 00 00 00 30 01 00",
}


def open_dev():
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            h = hid.device()
            h.open_path(d["path"])
            return h
    return None


def main(args):
    if args.list:
        print("内置候选报文：")
        for k, v in CANDIDATES.items():
            n = len(bytes.fromhex(v.replace(" ", "")))
            print(f"  {k:12s} {n:3d} B  {v}")
        return 0

    raw = args.hexstr.replace(" ", "").replace(",", "")
    payload = bytes.fromhex(raw)
    print(f"[{datetime.now():%H:%M:%S}] 待发送 {len(payload)} 字节：{payload.hex(' ')}")

    h = open_dev()
    if not h:
        print("!! 未找到设备（usage_page=1/usage=5）")
        return 2
    print("  设备已打开")

    for attempt in range(1, args.repeat + 1):
        try:
            n = h.write(payload)
        except Exception as e:
            print(f"  第 {attempt} 次写入异常：{e}")
            n = -1
        print(f"  第 {attempt} 次写入返回 {n}（期望 {len(payload)}）")
        if n != len(payload):
            print("  !! 写入长度不符，报告可能被拒绝")
        time.sleep(0.05)

    # 发送后读一段时间，看报告流是否起来
    print(f"  开始读取 {args.read:g}s ……")
    t0 = time.time()
    got = 0
    ids = {}
    first = None
    while time.time() - t0 < args.read:
        buf = h.read(64, 200)
        if not buf:
            continue
        rid = buf[0]
        ids[rid] = ids.get(rid, 0) + 1
        if rid == 0x05:
            got += 1
            if first is None:
                first = time.time() - t0
    try:
        h.close()
    except Exception:
        pass

    el = time.time() - t0
    print(f"\n结果：{el:.2f}s 内收到 {sum(ids.values())} 个报告")
    print("  报告 ID 分布：", {f"0x{k:02X}": v for k, v in sorted(ids.items())} or "（空）")
    if got:
        print(f"  ✅ 0x05 共 {got} 帧 = {got/el:.1f} Hz，首帧在 {first*1000:.0f} ms")
        print("  → 这条命令足以激活")
        return 0
    print("  ❌ 没有 0x05 报告")
    print("  → 这条命令单独不够（或报文格式不对）")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hexstr", nargs="?", default="")
    ap.add_argument("--read", type=float, default=8.0)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if not a.list and not a.hexstr:
        sys.exit("用法: send_activation.py <hex 报文> | --list")
    sys.exit(main(a))
