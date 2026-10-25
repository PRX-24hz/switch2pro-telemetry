#!/usr/bin/env python3
"""读取 HID 设备的报告长度定义（只读，不写设备）。

为什么需要：hidapi 的 write() 要求缓冲区长度精确匹配 report descriptor 声明的
OutputReportByteLength（含 1 字节 report ID）。长度不符时 Windows 直接返回 -1，
且不会给出任何提示。

调用链（纯 Windows API，用 ctypes）：
  CreateFile → HidD_GetPreparsedData → HidP_GetCaps → 打印 HIDP_CAPS

用法：python hid_caps.py
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


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
hid_dll.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid_dll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]


def caps_for(path):
    # 只用 GENERIC_READ 打开：HidD_GetPreparsedData / HidP_GetCaps 都只需要读权限。
    # 早期版本顺手连写权限一起申请了，虽然从不写入，但会让只读审计判红，
    # 也让「只读」这句话在代码层面变得不可验证。
    h = kernel32.CreateFileW(path, GENERIC_READ,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE or not h:
        return None, ctypes.get_last_error()
    ppd = ctypes.c_void_p()
    if not hid_dll.HidD_GetPreparsedData(h, ctypes.byref(ppd)):
        kernel32.CloseHandle(h)
        return None, ctypes.get_last_error()
    c = HIDP_CAPS()
    ok = hid_dll.HidP_GetCaps(ppd, ctypes.byref(c))
    hid_dll.HidD_FreePreparsedData(ppd)
    kernel32.CloseHandle(h)
    return (c if ok else None), 0


def main():
    targets = [d for d in hid.enumerate(VID, PID)
               if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not targets:
        print("未找到 usage_page=1/usage=5 的接口")
        return 2
    for d in targets:
        path = d["path"]
        if isinstance(path, bytes):
            path = path.decode("utf-8", "ignore")
        print(f"接口: {path}\n")
        c, err = caps_for(path)
        if not c:
            print(f"  读取 caps 失败，GetLastError={err}")
            continue
        print(f"  UsagePage/Usage        : 0x{c.UsagePage:04X} / 0x{c.Usage:04X}")
        print(f"  InputReportByteLength  : {c.InputReportByteLength}")
        print(f"  OutputReportByteLength : {c.OutputReportByteLength}   ← write() 要用这个长度")
        print(f"  FeatureReportByteLength: {c.FeatureReportByteLength}")
        print(f"  输入 value caps 数      : {c.NumberInputValueCaps}")
        print(f"  输出 value caps 数      : {c.NumberOutputValueCaps}")
        print(f"  输出 button caps 数     : {c.NumberOutputButtonCaps}")
        print(f"  特性 value caps 数      : {c.NumberFeatureValueCaps}")
        print()
        print(f"  => 写入报告的缓冲区应为 {c.OutputReportByteLength} 字节"
              f"（首字节 report ID；本脚本不写入，仅供后来者参考）")
        print(f"  => 读取缓冲区应为 {c.InputReportByteLength} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
