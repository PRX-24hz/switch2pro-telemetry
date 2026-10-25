#!/usr/bin/env python3
"""读取并粗解析 HID 报告描述符（只读）。

目的：确认设备有几个 output report、是否使用 report ID。
HID 描述符里：
  Item 0x85 = Report ID
  Item 0x95 = Report Count
  Item 0x75 = Report Size
  Item 0x81 = Input
  Item 0x91 = Output
  Item 0xB1 = Feature
  Item 0x05 = Usage Page

OutputReportByteLength 已知为 64。若描述符里没有 0x85，说明只有一个无 ID 的报告，
此时写报告的缓冲区首字节就是数据，而不是 report ID。

用法：python hid_descriptor.py
"""
import os, sys, ctypes
from ctypes import wintypes

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
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid_dll = ctypes.WinDLL("hid", use_last_error=True)
GENERIC_READ = 0x80000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID = ctypes.c_void_p(-1).value

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
hid_dll.HidD_GetReportDescriptor.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                             wintypes.ULONG]
hid_dll.HidD_GetReportDescriptor.restype = wintypes.BOOLEAN

ITEMS = {
    0x80: "Input", 0x90: "Output", 0xB0: "Feature",
    0x84: "Report ID", 0x74: "Report Size", 0x94: "Report Count",
    0x04: "Usage Page", 0x08: "Usage", 0xA0: "Collection", 0xC0: "End Collection",
}


def main():
    path = None
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005:
            p = d["path"]
            path = p.decode("utf-8", "ignore") if isinstance(p, bytes) else p
            break
    if not path:
        print("未找到设备"); return 2

    # 只用读权限：HidD_GetReportDescriptor 不需要写。
    h = kernel32.CreateFileW(path, GENERIC_READ,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
    if h == INVALID or not h:
        print(f"CreateFile 失败 err={ctypes.get_last_error()}"); return 3

    buf = ctypes.create_string_buffer(8192)
    ok = hid_dll.HidD_GetReportDescriptor(h, buf, 8192)
    err = ctypes.get_last_error()
    kernel32.CloseHandle(h)
    if not ok:
        print(f"HidD_GetReportDescriptor 失败 err={err}"); return 4

    raw = buf.raw
    # 实际长度：截到最后一个非零段（描述符通常不以 0 结尾，用启发式找 0xC0 尾部）
    n = 0
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] != 0:
            n = i + 1
            break
    d = raw[:n]
    print(f"报告描述符长度 {n} 字节\n")
    for i in range(0, n, 16):
        print(f"  {i:3d}: {' '.join('%02x' % b for b in d[i:i+16])}")
    print()

    # 粗解析：找 report ID 与 output
    ids = []
    cur_id = None
    size = count = 0
    print("关键项：")
    i = 0
    while i < n:
        b = d[i]
        if b == 0xFE:            # long item
            ln = d[i + 1] if i + 1 < n else 0
            i += 3 + ln
            continue
        ln = b & 0x03
        ln = 4 if ln == 3 else ln
        tag = b & 0xFC
        val = int.from_bytes(d[i + 1:i + 1 + ln], "little") if ln else None
        if tag == 0x84 and val is not None:
            cur_id = val
            ids.append(val)
            print(f"  off {i:3d}: Report ID = 0x{val:02X}")
        elif tag == 0x74 and val is not None:
            size = val
        elif tag == 0x94 and val is not None:
            count = val
        elif tag in (0x90, 0x80, 0xB0) and val is not None:
            kind = "Output" if tag == 0x90 else ("Input" if tag == 0x80 else "Feature")
            bits = size * count
            print(f"  off {i:3d}: {kind:6s} report_id={('0x%02X' % cur_id) if cur_id else '无'} "
                  f"count={count} size={size} → {bits} bit = {bits//8} 字节")
        i += 1 + ln

    print()
    if ids:
        print(f"=> 设备使用 report ID，共 {len(ids)} 个：{[hex(x) for x in ids]}")
    else:
        print("=> 描述符中没有 Report ID 项：只有一个无 ID 的报告，"
              "写报告时缓冲区首字节是数据本身")


if __name__ == "__main__":
    sys.exit(main())
