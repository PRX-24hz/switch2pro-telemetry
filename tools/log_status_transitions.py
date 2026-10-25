#!/usr/bin/env python3
"""记录 0x05 报告里「充电状态字节」的每一次跳变（含读数与墙钟），纯只读。
用途：把硬件红灯的亮/灭 与 状态字节 做时间对齐，建立因果而非相关。

用法：python log_status_transitions.py [分钟数，默认 20]
"""
import os, sys, time
from datetime import datetime
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pylibs")
sys.path.insert(0, os.path.join(_libs, "py%d%d" % sys.version_info[:2]))
try:
    import hid
except ImportError:
    sys.exit("hidapi 不可用")

VID, PID = 0x057E, 0x2069


def main(minutes: float = 20.0) -> int:
    devs = [d for d in hid.enumerate(VID, PID)
            if d.get("usage_page") == 0x0001 and d.get("usage") == 0x0005]
    if not devs:
        print("未找到设备"); return 1
    h = hid.device(); h.open_path(devs[0]["path"])
    print(f"[{datetime.now():%H:%M:%S}] 开始记录状态跳变（{minutes:g} 分钟）", flush=True)
    last = None; t0 = time.time(); stat = {}; beat = t0 + 30
    prev_pair = None; skew = 0.0             # (壁钟, 设备时钟) 与累计偏差
    win = {}                                 # 本轮心跳窗口内的状态计数（算占空比）
    try:
        while time.time() - t0 < minutes * 60:
            buf = h.read(64, 200)
            if not buf or buf[0] != 0x05:
                continue
            st = buf[0x22]; mv = int.from_bytes(buf[0x20:0x22], "little")
            win[st] = win.get(st, 0) + 1
            btn = int.from_bytes(buf[5:9], "little")      # 按键位域，用于判断"活动是否影响读数"
            ctr = int.from_bytes(buf[1:5], "little")
            stat[st] = stat.get(st, 0) + 1
            if st != last:
                if last is not None:
                    print(f"[{datetime.now():%H:%M:%S}] 0x{last:02X} → 0x{st:02X}   读数={mv}  clock={ctr:,}ms",
                          flush=True)
                last = st
            if time.time() >= beat:                      # 30s 心跳：让"红灯亮/灭"能对齐到读数
                beat = time.time() + 30
                now_wall = time.time()
                msg = (f"[{datetime.now():%H:%M:%S}]   · 心跳 状态=0x{st:02X} 读数={mv} "
                       f"clock={ctr:,}ms 键=0x{btn:08X}")
                tot = sum(win.values())
                if tot:
                    parts = sorted(win.items(), key=lambda kv: -kv[1])[:3]
                    msg += " 窗内=" + "/".join("0x%02X:%.0f%%" % (k, 100 * v / tot) for k, v in parts)
                win.clear()
                if prev_pair:
                    dwall = (now_wall - prev_pair[0]) * 1000.0
                    dclk = ctr - prev_pair[1]
                    if 0 < dclk < 120000:                # 排除回绕/断档
                        skew += dwall - dclk             # 累计：壁钟相对设备时钟多走的时间
                        msg += f" 偏={skew:+.0f}ms"
                        if abs(dwall - dclk) > 100:
                            msg += " <<壁钟被调整"
                prev_pair = (now_wall, ctr)
                print(msg, flush=True)
    finally:
        try: h.close()
        except Exception: pass
    total = sum(stat.values())
    print(f"[{datetime.now():%H:%M:%S}] 结束。状态分布：" +
          "  ".join(f"0x{k:02X}={v}({v*100//max(1,total)}%)" for k, v in sorted(stat.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 20.0))
