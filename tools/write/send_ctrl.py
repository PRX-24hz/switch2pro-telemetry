#!/usr/bin/env python3
"""用控制传输 SET_REPORT 发送输出报告（HidD_SetOutputReport）。

为什么不用 hid.write()：hidapi 的 write() 走中断 OUT 端点，Windows 要求缓冲区长度
精确等于 OutputReportByteLength（本设备是 64），发 12 字节直接被拒（返回 -1）。

而 USBPcap 抓包显示，Steam 发的命令是 **OUT + CONTROL**（transfer 字节 = 0x02），
长度只有 8~28 字节。控制传输不受固定报告长度的硬性约束，所以走
HidD_SetOutputReport 才能复现。

⚠️ 会写设备。只回放抓包中提取的原始报文。

用法:
  python send_ctrl.py --list
  python send_ctrl.py "0c 91 00 04 00 04 00 00 27 00 00 00" [--read 8]
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

CANDIDATES = {
    "mode_27": "0c 91 00 04 00 04 00 00 27 00 00 00",
    "imu_on":  "03 91 00 0d 00 08 00 00 01 00 ff ff",
    "led_0a":  "03 91 00 0a 00 04 00 00 05 00 00 00",
    "led_0c":  "01 91 00 0c 00 00 00 00",
    "info_02": "0c 91 00 02 00 04 00 00 27 00 00 00",
}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid_dll = ctypes.WinDLL("hid", use_last_error=True)
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID = ctypes.c_void_p(-1).value

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
hid_dll.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_SetOutputReport.restype = wintypes.BOOLEAN


def find_path():
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            p = d["path"]
            return p.decode("utf-8", "ignore") if isinstance(p, bytes) else p
    return None


def main(a):
    if a.list:
        print("内置候选报文（原样取自 steam_capture.pcap）：")
        for k, v in CANDIDATES.items():
            print(f"  {k:10s} {len(bytes.fromhex(v.replace(' ',''))):2d} B  {v}")
        return 0

    payload = bytes.fromhex(a.hexstr.replace(" ", "").replace(",", ""))
    if a.pad and len(payload) < a.pad:
        pad_byte = bytes([a.pad_byte])
        payload = payload + pad_byte * (a.pad - len(payload))
        print(f"  已用 0x{a.pad_byte:02X} 补齐到 {a.pad} 字节")
    path = find_path()
    if not path:
        print("!! 未找到设备")
        return 2

    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
    if h == INVALID or not h:
        print(f"!! CreateFile 失败，err={ctypes.get_last_error()}")
        return 3

    print(f"[{datetime.now():%H:%M:%S}] 发送 {len(payload)} 字节（控制传输 SET_REPORT）")
    print(f"  {payload.hex(' ')}  [report_id=0x{payload[0]:02X}]")
    buf = ctypes.create_string_buffer(payload, len(payload))
    ok = hid_dll.HidD_SetOutputReport(h, buf, len(payload))
    print(f"  HidD_SetOutputReport 返回 {ok}（1=成功，0=失败 err={ctypes.get_last_error()}）")
    kernel32.CloseHandle(h)

    # 用 hidapi 读回，看报告流是否起来
    print(f"  读取 {a.read:g}s ……")
    dev = None
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            dev = hid.device()
            dev.open_path(d["path"])
            break
    if not dev:
        print("!! 读取时无法打开设备")
        return 4

    t0 = time.time()
    ids = {}
    first = None
    while time.time() - t0 < a.read:
        b = dev.read(64, 200)
        if not b:
            continue
        ids[b[0]] = ids.get(b[0], 0) + 1
        if b[0] == 0x05 and first is None:
            first = time.time() - t0
    try:
        dev.close()
    except Exception:
        pass

    el = time.time() - t0
    total = sum(ids.values())
    print(f"\n结果：{el:.2f}s 收到 {total} 个报告")
    print("  报告 ID 分布：", {f"0x{k:02X}": v for k, v in sorted(ids.items())} or "（空）")
    if ids.get(0x05):
        print(f"  ✅ 0x05 共 {ids[0x05]} 帧 = {ids[0x05]/el:.1f} Hz，首帧 {first*1000:.0f} ms")
        return 0
    print("  ❌ 没有 0x05")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hexstr", nargs="?", default="")
    ap.add_argument("--read", type=float, default=8.0)
    ap.add_argument("--pad", type=int, default=0)
    ap.add_argument("--pad-byte", type=lambda x: int(x,0), default=0x00)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if not a.list and not a.hexstr:
        sys.exit("用法: send_ctrl.py <hex> | --list")
    sys.exit(main(a))
