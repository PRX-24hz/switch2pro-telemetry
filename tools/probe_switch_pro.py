#!/usr/bin/env python3
"""Switch 2 Pro 手柄 (0x057E:0x2069) 只读探针：HID 集合枚举 + 0x05 报告解析 + 趋势采样 + CSV 记录。
纯用户态、只读：不发任何命令、不切报告模式、不碰 interface1。

用法：
  python probe_switch_pro.py                     抓 4 帧，逐帧明细
  python probe_switch_pro.py --watch 60          连续采样 60 秒，每秒一行
  python probe_switch_pro.py --csv sw2.csv       持续采样直到 Ctrl-C / 离线，同步落 CSV
  python probe_switch_pro.py --watch 600 --csv sw2.csv   采样 10 分钟并记录
  python probe_switch_pro.py --hotplug           测首帧时钟：等设备出现即读，扣掉脚本延迟
  python probe_switch_pro.py --until-full --csv sw2_charge.csv   挂机到满电(0x20)自动退出
     ※ 实测 73 分钟未观测到 0x20，该判据可能永不触发；长期挂机请用 --watch 兜底

协议依据 ndeadly/switch2_controller_research · kennethreitz/switch2bridge-macos：
  0x05 通用报告（上电即在流 250Hz/4ms），USB 下 buf = 报告ID + 63B body：
    body[0:4]  32bit 计数器，实为链路毫秒时钟，每帧 +4（插拔归零，不要当墙钟）
    body[4:8]  按键 4B   body[0xA:0xD] 左摇杆12bit  body[0xD:0x10] 右摇杆12bit
    body[0x1F:0x21] 电池电压 mV(LE)   body[0x21] 充电状态字节（0x20=满 0x2C=刚插上 0x34=恒流充电中）
  注意：USB 供电下状态字节恒为充电态，0x00「未接电源」只能通过 BLE 观测 → USB 通道测不出放电曲线。
  0x09 Pro2 扩展报告里的 0..9 电量档位需经 interface1 bulk 初始化才会流（本脚本刻意不做）。
  旧规则 buf[2]>>4 来自 Switch1 0x30 报告，对 Switch2 无效：0x05 里 buf[2] 只是计数器第 2 字节。
"""
import csv, os, sys, time
from datetime import datetime
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pylibs")   # 本地 hidapi 兜底
sys.path.insert(0, os.path.join(_libs, "py%d%d" % sys.version_info[:2]))
VID, PID = 0x057E, 0x2069
RID = {0x05: "通用报告", 0x09: "Pro2 扩展报告", 0x02: "输出/震动"}
B05 = [(0, 0x80, "ZR"), (0, 0x40, "R"), (0, 0x08, "A"), (0, 0x04, "B"), (0, 0x02, "X"), (0, 0x01, "Y"),
       (1, 0x40, "C"), (1, 0x20, "Capture"), (1, 0x10, "Home"), (1, 0x08, "LS"), (1, 0x04, "RS"),
       (1, 0x02, "+"), (1, 0x01, "-"), (2, 0x80, "ZL"), (2, 0x40, "L"), (2, 0x08, "←"), (2, 0x04, "→"),
       (2, 0x02, "↑"), (2, 0x01, "↓"), (3, 0x10, "Headset"), (3, 0x02, "GL"), (3, 0x01, "GR")]
# 单节锂电开路电压 → SoC 查表（充电中端电压被抬高，读数偏乐观，只能当上限）
SOC = [(4200, 100), (4100, 90), (4000, 80), (3930, 70), (3870, 60), (3830, 50), (3790, 40),
       (3760, 35), (3730, 30), (3710, 25), (3680, 20), (3660, 15), (3630, 10), (3580, 5), (3500, 3), (3300, 0)]
CSV_HEAD = ["timestamp", "elapsed_sec", "frame_count", "clock_ms",
            "voltage_mv", "soc_percent", "status_hex", "lost_frames"]
def hr(t): print(f"\n--- {t} " + "-" * max(0, 58 - len(t)))
def s12(a, b, c): return (a | ((b & 0x0F) << 8)), ((b >> 4) | (c << 4))       # 两个 12bit 打包
def btn(blk, table): return " ".join(n for i, m, n in table if len(blk) > i and blk[i] & m) or "-"
def soc(mv):                    # 仅供旧 CSV 的 soc_percent 列兼容；该字段非电芯电压，结果不可当电量用
    for (v1, p1), (v2, p2) in zip(SOC, SOC[1:]):
        if mv >= v2: return round(p2 + (p1 - p2) * (mv - v2) / (v1 - v2))
    return 0
def chg_txt(c):                                       # 语义由实机锚定：红灯熄灭+主机显示满电 时 0x00 占优
    return {0x00: "充电终止/维护(满电)", 0x24: "收尾涓流", 0x2C: "插上初期", 0x34: "恒流充电中",
            0x20: "未观测值"}.get(c, "未知")
def detail(b):
    ctr, mv, c = int.from_bytes(b[0:4], "little"), int.from_bytes(b[0x1F:0x21], "little"), b[0x21]
    lx, ly = s12(b[10], b[11], b[12]); rx, ry = s12(b[13], b[14], b[15])
    print(f"      hex={' '.join(f'{x:02X}' for x in b[:12])}")
    print(f"      时钟={ctr}ms 按键=[{btn(b[4:8], B05)}] L=({lx},{ly}) R=({rx},{ry})")
    print(f"      读数={mv}（raw {b[0x1F]:02X} {b[0x20]:02X} LE，无量纲：满电也仅 ≈3670）| 充电状态=0x{c:02X} {chg_txt(c)}")

def prompt_replug():
    print("[提示] 本模式会先读当前值，首帧 clock_ms 里混着脚本启动延迟（提示/回车/枚举/打开）。")
    print("       若目的是判定「计数器是否随插拔归零」，别用肉眼比大小，改用：")
    print("         python probe_switch_pro.py --hotplug     ← 等设备出现即读，扣掉自身延迟")
    if sys.stdin and sys.stdin.isatty():
        try: input("       直接采样按回车；要测归零请先 Ctrl-C 再跑 --hotplug…")
        except (EOFError, KeyboardInterrupt): print()

def open_csv(path):
    new = (not os.path.exists(path)) or os.path.getsize(path) == 0
    f = open(path, "a", newline="", encoding="utf-8")     # 追加模式：多次采样可累积同一条曲线
    w = csv.writer(f)
    if new:
        w.writerow(CSV_HEAD); f.flush()
    return f, w

def enum_sets(hid):
    devs = list(hid.enumerate(VID, PID))
    if not devs:
        print("  ↳ 未发现 0x057E:0x2069（关机 / 仅蓝牙未配对 / 被独占）"); return []
    for i, d in enumerate(devs):
        p = d["path"].decode(errors="ignore") if isinstance(d["path"], bytes) else str(d["path"])
        print(f"  [{i}] iface={d.get('interface_number')!s:<3} page=0x{d.get('usage_page') or 0:04X}"
              f" usage=0x{d.get('usage') or 0:04X}  {d.get('product_string') or '-'}\n      path={p}")
    return devs

def pick_pad(devs):
    return next((d for d in devs if d.get("usage_page") == 0x01 and d.get("usage") in (0x04, 0x05)), devs[0])

def measure_first_frame(hid, timeout=120, poll=0.05):
    """--hotplug：轮询等设备出现，出现即开即读，用「枚举出现→首帧」耗时扣掉脚本自身延迟，
    从而推算链路建立那一刻的计数。这是唯一能干净判定计数器语义的做法（首帧不扣延迟会被启动开销污染）。"""
    if list(hid.enumerate(VID, PID)):                     # 已插着：先等它拔出来，否则测的是旧链路
        print("  ↳ 设备当前已连接。请现在拔掉手柄（我等你消失后，再提示你插回）…", flush=True)
        t1 = time.perf_counter()
        while list(hid.enumerate(VID, PID)):
            if time.perf_counter() - t1 > 60:
                print("  ↳ 60s 内没等到拔线，改用当前连接直接测（结果不可信）"); break
            time.sleep(poll)
        else:
            print("  ↳ 已确认拔出。现在插上手柄 USB…", flush=True)
    print("  ↳ 等待设备出现…", flush=True)
    t0 = time.perf_counter(); devs = []
    while time.perf_counter() - t0 < timeout:
        devs = list(hid.enumerate(VID, PID))
        if devs: break
        time.sleep(poll)
    if not devs:
        print(f"  ↳ {timeout}s 内未出现，放弃"); return []
    t_appear = time.perf_counter()
    h = hid.device(); ctr = lat = mv = st = None
    try:
        h.open_path(pick_pad(devs)["path"])
        while time.perf_counter() - t_appear < 5:
            buf = h.read(64, 200)
            if buf and buf[0] == 0x05:
                ctr = int.from_bytes(buf[1:5], "little"); lat = (time.perf_counter() - t_appear) * 1000
                mv, st = int.from_bytes(buf[0x20:0x22], "little"), buf[0x22]
                break
    except Exception as e:
        print(f"  ↳ 打开/读取失败：{type(e).__name__}: {e}")
    finally:
        try: h.close()
        except Exception: pass
    if ctr is None:
        print("  ↳ 设备已出现但 5s 内没拿到 0x05 帧（可能还在初始化）"); return devs
    est = ctr - lat
    print(f"  ↳ 首帧 clock={ctr}ms，枚举出现→首帧耗时={lat:.0f}ms → 链路建立时刻计数≈{est:.0f}ms")
    print(f"  ↳ 首帧读数={mv}（无量纲电量计值） 充电状态=0x{st:02X} {chg_txt(st)}  ← 标定锚点请记这行")
    print("  ↳ 判定：" + ("计数器随链路建立归零 ✔（可当链路 uptime 用）" if -300 <= est <= 1500
          else f"仍有 {est:.0f}ms 偏移 ✘（不是链路时钟；若刚插上即测，还需再扣 USB 枚举本身耗时）"))
    return devs

def stream(hid, devs, n_frames=None, seconds=None, csv_path=None, until_full=False):
    pick = pick_pad(devs)
    h, cf, cw = hid.device(), None, None
    if csv_path:
        cf, cw = open_csv(csv_path)
        print(f"  ↳ CSV 追加写入：{os.path.abspath(csv_path)}（表头 {','.join(CSV_HEAD)}）")
    clf = None
    if not n_frames:
        try:
            from switch2_battery_state import BatteryStateClassifier
            clf = BatteryStateClassifier()
            print("  ↳ 已启用电量状态分类器（Discharging/FastCharging/ToppingOff/Full/GenericCharging）")
        except ImportError:
            pass
    t0 = time.perf_counter(); end = t0 + seconds if seconds else None
    got = lost = 0; prev = base_mv = None; tick = t0 + 1.0; hist = []; fails = epoch = 0
    def rec(now, ctr, mv, st):                            # 与采样节拍同步落一行（不是每帧一行）
        if not cw: return
        cw.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                     round(now - t0, 3), got, ctr, mv, soc(mv), f"0x{st:02X}", lost])
        cf.flush()                                        # 每行落盘，崩溃也不丢数据
    try:
        h.open_path(pick["path"])   # hidapi 在 Windows 用共享句柄，非独占，不干扰系统 HID 栈
        print(f"  ↳ 已打开 page=0x{pick.get('usage_page') or 0:04X}/usage=0x{pick.get('usage') or 0:04X}")
        while True:
            if n_frames and got >= n_frames: break
            if end and time.perf_counter() >= end: break
            try:
                buf = h.read(64, 200)
            except Exception as e:
                fails += 1                                 # 链路闪断防抖：单次异常不判离线
                if fails >= 3:
                    print(f"[Offline] 设备已断开（连续 {fails} 次读失败：{type(e).__name__}: {e}）"); break
                time.sleep(0.3); continue                  # 1~2s 重试窗口，避免拓展坞松动导致闪烁
            now = time.perf_counter()
            if not buf:                                    # 单次超时不判离线，累计 3 次才判
                fails += 1
                if fails >= 3:
                    print("[Offline] 设备已断开（连续 3 次读超时，可能已拔出/关机/休眠）"); break
                continue
            fails = 0
            rid, b = buf[0], buf[1:]
            if rid != 0x05 or len(b) < 0x22:
                print(f"  ! id=0x{rid:02X} ({RID.get(rid, '未知')}) len={len(buf)}，非 0x05，跳过"); continue
            got += 1
            ctr = int.from_bytes(b[0:4], "little")
            if prev is not None and ctr < prev and (prev - ctr) > 1000:   # 硬件周期回绕
                epoch += 1
                print(f"  ↳ [Epoch] 时钟回绕 #{epoch}：{prev} → {ctr}ms，重置掉帧基准（不做无符号相减）")
            elif prev is not None and ctr > prev:                         # epoch 内正常前进才计掉帧
                lost += max(0, (ctr - prev) // 4 - 1)                     # 每帧应 +4
            if prev is None:
                print(f"  ↳ 首帧时钟={ctr}ms（含本脚本启动延迟，不能直接判归零；要精确判定请用 --hotplug）")
            prev = ctr
            mv, st = int.from_bytes(b[0x1F:0x21], "little"), b[0x21]
            if base_mv is None: base_mv = mv
            if n_frames:
                print(f"  [{got - 1}] len={len(buf)} id=0x05 时钟={ctr}ms 掉帧累计={lost}"); detail(b)
                rec(now, ctr, mv, st)
            if not n_frames and now >= tick:               # 采样节拍：每秒一行（控制台 + CSV）
                tag = f" 电量状态={clf.feed(mv, st, now - t0).value}" if clf else ""
                print(f"  t={now - t0:5.1f}s 帧={got:5d} 时钟={ctr:7d}ms 读数={mv}"
                      f" Δ={mv - base_mv:+d} 状态=0x{st:02X} {chg_txt(st)} 掉帧={lost}{tag}")
                rec(now, ctr, mv, st)
                tick += 1.0
                hist = (hist + [st])[-30:]                 # 近 30s 状态窗口
            if until_full and (st == 0x20 or (len(hist) >= 30 and hist.count(0x00) >= 15)):
                print(f"  ↳ 满电判据命中（{'0x20' if st == 0x20 else '0x00 占优'}），读数 {mv} → 结束采样")
                rec(now, ctr, mv, st)
                break
        print(f"  ↳ 结束：共 {got} 帧，掉帧 {lost}，平均 {got / max(0.001, time.perf_counter() - t0):.0f}Hz")
    except Exception as e:                                # 拔线 / 关机 / 句柄失效
        print(f"[Offline] 设备已断开（{type(e).__name__}: {e}）")
    finally:
        if cf:
            try: cf.flush(); cf.close(); print(f"  ↳ CSV 已保存并关闭：{os.path.abspath(csv_path)}")
            except Exception: pass
        try: h.close()
        except Exception: pass

def arg(flag, cast=str, default=None):
    if flag not in sys.argv: return default
    i = sys.argv.index(flag) + 1
    if i >= len(sys.argv): sys.exit(f"{flag} 缺少参数值")
    try: return cast(sys.argv[i])
    except ValueError: sys.exit(f"{flag} 参数非法：{sys.argv[i]}")

if __name__ == "__main__":
    try: import hid
    except ImportError: sys.exit(f"hidapi 不可用(py{sys.version_info[0]}.{sys.version_info[1]})，请 pip install hidapi")
    sec, csvp = arg("--watch", float), arg("--csv")
    full = "--until-full" in sys.argv
    if "--hotplug" in sys.argv:                            # 热插拔基准：等设备出现即读，扣掉脚本延迟
        hr("0. 热插拔首帧基准（只读）")
        print("[提示] 请先拔掉手柄；看到「等待设备出现」后再插上 USB。")
        devs = measure_first_frame(hid)
    else:
        prompt_replug()
        hr("1. HID 集合枚举 0x057E:0x2069"); devs = enum_sets(hid)
    if devs:
        hr(f"2. 0x05 报告解析{'（采样 %gs）' % sec if sec else ('（持续采样）' if csvp else '')}")
        try: stream(hid, devs, n_frames=None if (sec or csvp or full) else 4, seconds=sec,
                    csv_path=csvp, until_full=full)
        except KeyboardInterrupt: print("\n  ↳ 已中断，CSV 已 flush 保存")
