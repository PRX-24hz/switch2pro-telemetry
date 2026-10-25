#!/usr/bin/env python3
"""盯住 1431,655.8ms 的硬件时钟回绕，验证「32 位 3MHz tick 计数器」假设。纯只读。

用法：python wrap_watch.py [最长等待分钟数，默认 60]
原理：若假设成立，回绕前最后一个读数必然 ≈ 2^32/3e6*1000 = 1,431,655.8 ms（抖动 <1ms）。
      脚本按 250Hz 读，捕获回绕瞬间的「最后读数」，与理论值比对并给出结论。
"""
import os, sys, time
from datetime import datetime
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pylibs")
sys.path.insert(0, os.path.join(_libs, "py%d%d" % sys.version_info[:2]))
try:
    import hid
except ImportError:
    sys.exit("hidapi 不可用，请 pip install hidapi")

VID, PID = 0x057E, 0x2069
PREDICTED = 2 ** 32 / 3e6 * 1000        # 1,431,655.7658 ms


def main(minutes: float = 60.0) -> int:
    devs = [d for d in hid.enumerate(VID, PID)
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not devs:
        print("未找到 0x057E:0x2069（插好线再跑）"); return 1
    h = hid.device(); h.open_path(devs[0]["path"])
    print(f"已打开；理论回绕点 {PREDICTED:,.1f} ms（2^32 ticks @ 3MHz → ms）")
    t0 = time.time(); last = None; maxv = 0; tick = t0 + 15
    try:
        while time.time() - t0 < minutes * 60:
            buf = h.read(64, 100)
            if not buf or buf[0] != 0x05:
                continue
            ctr = int.from_bytes(buf[1:5], "little")
            maxv = max(maxv, ctr)
            if last is not None and ctr < last and (last - ctr) > 1000:     # 回绕
                dev = last - PREDICTED
                print(f"\n[{datetime.now():%H:%M:%S}] [WRAP] 回绕前最后读数 = {last:,} ms")
                print(f"       理论 2^32@3MHz   = {PREDICTED:,.1f} ms")
                print(f"       偏差             = {dev:+.1f} ms")
                print("       结论：" + ("假设成立 ✔（32 位 3MHz tick 计数器）" if abs(dev) < 50
                      else f"假设需修正 ✘（偏差 {dev:+.1f}ms 超出采样抖动，周期另有成因）"))
                print(f"       回绕后首帧 = {ctr} ms")
                return 0
            last = ctr
            now = time.time()
            if now >= tick:
                tick = now + 15
                eta = max(0.0, (PREDICTED - ctr) / 1000)
                print(f"  [{datetime.now():%H:%M:%S}] clock={ctr:>9,}ms  距预测回绕 {eta:6.0f}s  已运行 {now - t0:5.0f}s", flush=True)
    finally:
        try: h.close()
        except Exception: pass
    print(f"\n[未捕获] 本轮最大值 {maxv:,} ms（{minutes:g} 分钟内未回绕；差值 {PREDICTED - maxv:,.0f}ms）")
    return 2


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 60.0))
