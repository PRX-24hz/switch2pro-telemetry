#!/usr/bin/env python3
"""只读审计：把「我们只读」从一句承诺变成一条可复现的检查。

分两个区扫描：

  只读区  仓库内除 `tools/write/` 之外的全部 .py —— 命中任何写调用即 FAIL
  写入区  `tools/write/` —— 只登记、只告警，不计入 PASS/FAIL

为什么要分区：本仓库确实有三个会写设备的脚本（尝试自己激活手柄），它们失败了，
但失败本身是结论的一部分，不能删。若把它们和只读工具混在一起，「只读」就成了口号；
把它们挪进隔离目录、由本脚本单独列出，才既保留证据又不污染承诺。

退出码：0 = 只读区干净；1 = 只读区发现写调用。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRITE_ZONE = ROOT / "tools" / "write"

# 任何一条命中即视为「可能写设备」
FORBIDDEN = [
    # hidapi 写通道
    r"\bhid_write\b", r"\bhid_send_feature_report\b", r"\bsend_feature_report\b",
    r"\bsend_output_report\b", r"\bhid_send_output_report\b", r"\bHidD_SetOutputReport\b",
    # hidapi 的设备对象写方法（h.write / dev.write）——注意不要匹配普通文件句柄
    r"\b(?:h|dev|device|hid_dev)\.write\b",
    # Win32 / WinUSB 写通道
    r"\bWriteFile\b", r"\bWinUsb_WritePipe\b", r"\bDeviceIoControl\b",
    r"\bSetupDiSetClassInstallParams\b",
    # 打开句柄时申请写权限（只读场景不该出现 GENERIC_WRITE）
    r"\bGENERIC_WRITE\b",
]

# 允许自指的例外（本审计脚本自身）
EXEMPT_FILES = {"audit_readonly.py"}


def scan(files):
    """返回 [(相对路径, 行号, 命中模式, 源码行)]"""
    hits = []
    for f in files:
        rel = f.relative_to(ROOT)
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            print(f"  跳过 {rel}: {e}")
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in FORBIDDEN:
                if re.search(pat, line):
                    hits.append((rel, i, pat, line.strip()))
    return hits


def split_zones():
    all_py = sorted(p for p in ROOT.rglob("*.py") if p.name not in EXEMPT_FILES)
    readonly, write = [], []
    for p in all_py:
        try:
            p.relative_to(WRITE_ZONE)
            write.append(p)
        except ValueError:
            readonly.append(p)
    return readonly, write


def main() -> int:
    readonly, write = split_zones()

    print(f"仓库根：{ROOT}")
    print(f"只读区：{len(readonly)} 个 Python 文件")
    print(f"写入区：{len(write)} 个 Python 文件（tools/write/）")

    ro_hits = scan(readonly)
    wr_hits = scan(write)

    print()
    print("── 只读区 ─────────────────────────────────────────────")
    for f in readonly:
        print(f"  {f.relative_to(ROOT)}")

    print()
    print("── 写入区（隔离，知悉即可）────────────────────────────")
    if not write:
        print("  （空）")
    by_file = {}
    for rel, ln, pat, line in wr_hits:
        by_file.setdefault(str(rel), []).append((ln, pat, line))
    for f in write:
        rel = str(f.relative_to(ROOT))
        n = len(by_file.get(rel, []))
        print(f"  {rel}  → {n} 处写调用")
        if n == 0:
            print("      ⚠ 该文件没有检测到写调用，可能误放：请确认它是否该留在只读区")

    print()
    if ro_hits:
        print(f"[FAIL] 只读区发现 {len(ro_hits)} 处写调用：")
        for rel, ln, pat, line in ro_hits:
            print(f"  {rel}:{ln}  /{pat}/  {line}")
        print("\n只读区必须为零。会写设备的脚本请移入 tools/write/ 并更新其 README。")
        return 1

    print("[PASS] 只读区未发现任何写设备调用。")
    if wr_hits:
        print(f"[NOTE] 另有 {len(wr_hits)} 处写调用位于 tools/write/，已隔离，不计入本判定。")

    used = set()
    for f in readonly:
        t = f.read_text(encoding="utf-8", errors="ignore")
        used |= set(re.findall(r"\bhid\.\w+|\bh\.[a-z_]+", t))
    print("只读区实际使用的接口：" + ", ".join(sorted(used)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
