#!/usr/bin/env python3
"""按顺序回放 Steam 的完整激活序列，看能否自己把设备激活。

命令来自 USBPcap 抓包（activate_capture.pcap, t=17.222~17.329），原样复制，
不做任何构造。包结构 `[counter][rumble_hi][rumble_lo][subcmd][params…]`。

难点：真正的 report ID 不在数据里（在控制传输的 SETUP 阶段，而 USBPcap 1.5.4
没记录它）。所以这里对每个候选 report ID 各回放一遍，哪个能让设备开始吐 0x05
就是对的。

⚠️ 会写设备。命令行都是中性 rumble + 已知子命令。

用法：
  python replay_activation.py --rid 0x02        # 用指定 report ID 回放
  python replay_activation.py --sweep           # 依次试 0x00~0x0F
  python replay_activation.py --list            # 只看要发什么
"""
import os, sys, time, ctypes, argparse
from ctypes import wintypes
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
REPORT_LEN = 64

# 抓包 t=17.222~17.329 原样抄录，17 条
SEQ = [
    "02 91 00 01 00 08 00 00 00 00 00 00 00 30 01 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 40 30 01 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 80 30 01 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 c0 30 01 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 00 31 01 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 40 c0 1f 00",
    "02 91 00 01 00 08 00 00 00 00 00 00 80 c0 1f 00",
    "07 91 00 01 00 00 00 00",
    "0c 91 00 02 00 04 00 00 27 00 00 00",
    "11 91 00 01 00 00 00 00",
    "0a 91 00 08 00 14 00 00 01 ff ff ff ff ff ff ff ff 35 00 46 00 00 00 00 00 00 00 00",
    "0c 91 00 04 00 04 00 00 27 00 00 00",
    "01 91 00 0c 00 00 00 00",
    "01 91 00 01 00 00 00 00",
    "08 91 00 02 00 04 00 00 01 00 00 00",
    "03 91 00 0a 00 04 00 00 05 00 00 00",
    "03 91 00 0d 00 08 00 00 01 00 ff ff ff ff ff ff",
]

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid_dll = ctypes.WinDLL("hid", use_last_error=True)
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
SHARE_RW, OPEN_EXISTING = 3, 3
INVALID = ctypes.c_void_p(-1).value

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
hid_dll.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_SetOutputReport.restype = wintypes.BOOLEAN


def path_of():
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            p = d["path"]
            return p.decode("utf-8", "ignore") if isinstance(p, bytes) else p
    return None


def read_for(sec):
    """读 sec 秒，返回 0x05 帧数"""
    dev = None
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            dev = hid.device(); dev.open_path(d["path"]); break
    if not dev:
        return 0, {}
    t0 = time.time(); n05 = 0; ids = {}
    while time.time() - t0 < sec:
        b = dev.read(64, 150)
        if not b:
            continue
        ids[b[0]] = ids.get(b[0], 0) + 1
        if b[0] == 0x05:
            n05 += 1
    try: dev.close()
    except Exception: pass
    return n05, ids


def replay(rid):
    path = path_of()
    if not path:
        print("  !! 找不到设备"); return -1
    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, SHARE_RW,
                             None, OPEN_EXISTING, 0, None)
    if h == INVALID or not h:
        print(f"  !! CreateFile 失败 err={ctypes.get_last_error()}"); return -1

    ok_cnt = 0
    for i, hx in enumerate(SEQ):
        body = bytes.fromhex(hx.replace(" ", ""))
        buf = bytes([rid]) + body
        if len(buf) < REPORT_LEN:
            buf += bytes(REPORT_LEN - len(buf))
        buf = buf[:REPORT_LEN]
        c = ctypes.create_string_buffer(buf, REPORT_LEN)
        r = hid_dll.HidD_SetOutputReport(h, c, REPORT_LEN)
        err = ctypes.get_last_error()
        ok_cnt += 1 if r else 0
        if i == 0 or r or err != 87:
            tag = "OK" if r else f"fail({err})"
            print(f"    #{i+1:02d} rid=0x{rid:02X} → {tag}")
        time.sleep(0.002)
    kernel32.CloseHandle(h)
    return ok_cnt


def main(a):
    if a.list:
        print(f"将回放 {len(SEQ)} 条命令（每条补齐到 {REPORT_LEN} 字节）：")
        for i, hx in enumerate(SEQ):
            print(f"  #{i+1:02d}  {hx}")
        return 0

    if a.sweep:
        cands = list(range(0x00, 0x10))
    else:
        cands = [a.rid]

    for rid in cands:
        print(f"\n=== 尝试 report ID 0x{rid:02X} ===")
        okc = replay(rid)
        if okc < 0:
            return 2
        n05, ids = read_for(a.read)
        print(f"    写入成功 {okc}/{len(SEQ)} 条；读取 {a.read:g}s → "
              f"0x05 {n05} 帧，报告分布 {dict(sorted(ids.items())) or '空'}")
        if n05 > 0:
            print(f"\n✅ report ID = 0x{rid:02X} 激活成功！{n05/a.read:.1f} Hz")
            return 0
    print("\n❌ 所有候选都没能激活")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rid", type=lambda x: int(x, 0), default=0x02)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--read", type=float, default=3.0)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a))
