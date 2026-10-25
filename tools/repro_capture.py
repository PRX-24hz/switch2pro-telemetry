#!/usr/bin/env python3
"""跨设备复现采集器：其他 Switch 2 Pro 用户跑这一条，就能生成可对比的指纹报告。

设计原则
--------
1. **只读**：只调 hid.enumerate / device / open_path / read / close，不向设备发任何字节。
   可用 `python tools/audit_readonly.py` 自证。
2. **一次采集覆盖全部待验假设**，避免让贡献者分多次跑：
   - H1 时钟回绕点 = 1,431,655.765 ms（2^32 @ 3 MHz）
   - H2 报告率 250 Hz、时钟每帧 +4
   - H3 状态字节是位域（b5=电源在位 / b2=有充电电流；b4:b3 语义未知，不作断言）
   - H4 满电维持态 0x20 的读数落在 ≈3670 平台（3663~3713）
3. **结论机器可判**，不依赖人工看图；无法判定时明确写 INCONCLUSIVE，不猜。

用法
----
    python tools/repro_capture.py                      # 默认采 30 分钟（够覆盖一次回绕）
    python tools/repro_capture.py --minutes 45 --fw "20.0.0"
    python tools/repro_capture.py --csv out.csv --json out.json --note "原装线+官方底座"

注意
----
* **30 分钟是硬需求**：任取 23.87 分钟以上的连续窗口，必然包含至少一个回绕点。
  少于 24 分钟有可能一次都碰不到，报告会写 INCONCLUSIVE。
* 手柄固件版本无法通过只读通道读到（读版本要发命令）。请在 Switch 2 的
  「设置 → 控制器与传感器 → 更新控制器」页面手抄，用 `--fw` 传进来，否则报告标 unknown。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import statistics
import sys
import time
from datetime import datetime

VID, PID = 0x057E, 0x2069
REPORT_ID = 0x05
FRAME_MS = 4
WRAP_MS = 2 ** 32 / 3e6 * 1000  # 1,431,655.765 ms
WRAP_TOL = 20.0                 # 判定容差（4 ms 量化 + 抖动）
GATE_MS = 1000                  # 时钟回退超过此值才当事件，否则视为抖动
_HEAD = ["timestamp", "elapsed_sec", "clock_ms", "raw", "status_hex", "lost_frames"]


def _hid():
    try:
        import hid
        return hid
    except ImportError:
        # 向上找 _pylibs（本文件可能在 tools/ 里，也可能被拷到别处）
        here = pathlib.Path(__file__).resolve()
        cand = [p / "_pylibs" for p in here.parents]
        lib = next((c for c in cand if c.is_dir()), None)
        if lib is None:
            raise
        sys.path.insert(0, str(lib / ("py%d%d" % sys.version_info[:2])))
        import hid
        return hid


def open_device(hid):
    devs = [d for d in hid.enumerate(VID, PID)
            if (d.get("usage_page") or 0) == 0x01 and (d.get("usage") or 0) in (0x04, 0x05)]
    if not devs:
        return None, None
    dev = devs[0]
    h = hid.device()
    h.open_path(dev["path"])
    return h, dev


def fingerprint(dev) -> dict:
    raw = dev["path"]
    raw = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
    return {
        "vid_pid": "0x%04X:0x%04X" % (VID, PID),
        "usage_page": dev.get("usage_page"),
        "usage": dev.get("usage"),
        "interface": dev.get("interface_number"),
        "product": dev.get("product_string"),
        # 路径含实例 ID（每次插拔/换口都会变），只留哈希用于区分设备，不外泄本机信息
        "path_sha1_12": hashlib.sha1(raw.encode()).hexdigest()[:12],
    }


def collect(h, minutes: float, want_csv: str | None):
    t0 = time.time()
    deadline = t0 + minutes * 60
    prev_clock = None
    last_ok = t0
    got = lost = fails = 0
    deltas: list[int] = []
    wraps: list[dict] = []
    status: dict[int, dict] = {}
    csv_f = csv_w = None

    if want_csv:
        import csv
        new = not os.path.exists(want_csv) or os.path.getsize(want_csv) == 0
        csv_f = open(want_csv, "a", newline="", encoding="utf-8")
        csv_w = csv.writer(csv_f)
        if new:
            csv_w.writerow(_HEAD)
            csv_f.flush()

    print("  ↳ 采集中（%g 分钟，250 Hz 只读）… 按 Ctrl-C 可提前结束并保留已有数据" % minutes, flush=True)
    try:
        while time.time() < deadline:
            try:
                buf = h.read(64, 200)
            except Exception as e:                       # 拔线/休眠：单次不算离线
                fails += 1
                if fails >= 3:
                    print("  ↳ [Offline] 连续 %d 次读失败（%s），提前结束采集" % (fails, type(e).__name__))
                    break
                time.sleep(0.3)
                continue
            now = time.time()
            if not buf:
                fails += 1
                if now - last_ok > 3.0:
                    print("  ↳ [Offline] 连续 3s 无输入报告，提前结束采集")
                    break
                continue
            fails = 0
            last_ok = now
            if buf[0] != REPORT_ID or len(buf) < 0x23:
                continue
            got += 1
            clock = int.from_bytes(buf[1:5], "little")
            raw = int.from_bytes(buf[0x20:0x22], "little")
            st = buf[0x22]

            # ---- 状态字节普查（每个取值单独记读数分布与首末时刻）----
            s = status.setdefault(st, {"n": 0, "raws": [], "first": None, "last": None})
            s["n"] += 1
            s["raws"].append(raw)
            if s["first"] is None:
                s["first"] = datetime.fromtimestamp(now).strftime("%H:%M:%S")
            s["last"] = datetime.fromtimestamp(now).strftime("%H:%M:%S")

            # ---- 时钟：先判回绕/重置，再算掉帧（绝不做无符号直接相减）----
            if prev_clock is not None:
                if clock < prev_clock and prev_clock - clock > GATE_MS:
                    gap = prev_clock - clock
                    kind = "wrap" if abs(prev_clock - WRAP_MS) <= GATE_MS else "reset"
                    # 双向估算事件时刻：前帧外推 vs 后帧回推
                    fwd = now - clock / 1000.0                      # 后帧回推
                    bwd = now - (clock + (WRAP_MS - prev_clock)) / 1000.0 \
                        if kind == "wrap" else None                 # 前帧外推到回绕点
                    wraps.append({
                        "kind": kind,
                        "prev_clock": prev_clock,
                        "new_clock": clock,
                        "gap_ms": gap,
                        "prev_minus_wrap_ms": round(prev_clock - WRAP_MS, 1),
                        "est_from_prev": (datetime.fromtimestamp(bwd).strftime("%H:%M:%S.%f")[:-3]
                                          if bwd else None),
                        "est_from_next": datetime.fromtimestamp(fwd).strftime("%H:%M:%S.%f")[:-3],
                        "two_way_delta_ms": (round(abs(fwd - bwd) * 1000, 1) if bwd else None),
                    })
                elif clock > prev_clock:
                    deltas.append(clock - prev_clock)
                    lost += max(0, (clock - prev_clock) // FRAME_MS - 1)
            prev_clock = clock

            if csv_w:
                csv_w.writerow([datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                                round(now - t0, 3), clock, raw, "0x%02X" % st, lost])
    except KeyboardInterrupt:
        print("  ↳ 已中断，保留已采集数据")
    finally:
        if csv_f:
            try:
                csv_f.flush()
                csv_f.close()
                print("  ↳ CSV 已保存：%s" % os.path.abspath(want_csv))
            except Exception:
                pass

    dur = max(0.001, time.time() - t0)
    # 帧率优先用设备时钟算（每帧 +4 ms → 250 Hz），避免主机调度抖动污染；
    # 主机侧实际吞吐另记 wall_rate_hz，两者差太多说明读线程被抢占。
    med = statistics.median(deltas) if deltas else None
    return {"duration_s": round(dur, 1), "frames": got, "lost": lost,
            "rate_hz": round(1000.0 / med, 1) if med else 0.0,
            "wall_rate_hz": round(got / dur, 1), "deltas": deltas,
            "wraps": wraps, "status": status}


def _median(xs):
    return statistics.median(xs) if xs else None


def verdicts(res: dict) -> list[dict]:
    out = []

    # H2 报告率 / 帧步进
    d, dt = _median(res["deltas"]), _median(res["deltas"])
    ok_rate = 235 <= res["rate_hz"] <= 260 and (dt == FRAME_MS if dt is not None else False)
    out.append({
        "id": "H2",
        "claim": "0x05 报告 250 Hz，时钟每帧 +4 ms",
        "verdict": "PASS" if ok_rate else ("INCONCLUSIVE" if not res["deltas"] else "FAIL"),
        "detail": "设备时钟 %.1f Hz，相邻帧时钟差中位数 %s ms，掉帧 %d（主机侧吞吐 %.1f Hz）" %
                  (res["rate_hz"], dt, res["lost"], res.get("wall_rate_hz", 0)),
    })

    # H1 回绕点
    wraps = [w for w in res["wraps"] if w["kind"] == "wrap"]
    resets = [w for w in res["wraps"] if w["kind"] == "reset"]
    if wraps:
        devs = [abs(w["prev_minus_wrap_ms"]) for w in wraps]
        out.append({
            "id": "H1",
            "claim": "时钟回绕点 = 1,431,655.765 ms（2^32 @ 3 MHz）",
            "verdict": "PASS" if max(devs) <= WRAP_TOL else "FAIL",
            "detail": "捕获 %d 次，偏差 %s ms（前帧末值与理论点之差）" %
                      (len(wraps), ", ".join("%+.1f" % (w["prev_clock"] - WRAP_MS) for w in wraps)),
        })
    else:
        out.append({
            "id": "H1",
            "claim": "时钟回绕点 = 1,431,655.765 ms（2^32 @ 3 MHz）",
            "verdict": "INCONCLUSIVE",
            "detail": "本次未捕获回绕（需连续 ≥23.87 分钟；%s）" %
                      ("捕获到 %d 次疑似重置，非回绕" % len(resets) if resets else "时长 %.1f 分钟" % (res["duration_s"] / 60)),
        })

    # H3 位域假说
    seen = sorted(res["status"])
    viol = []
    for v in seen:
        if v == 0:
            continue
        if not (v & 0x20):
            viol.append("0x%02X 未置 b5(电源在位)" % v)
    for v in (0x2C, 0x24, 0x34, 0x3C):
        if v in seen and not (v & 0x04):
            viol.append("0x%02X 未置 b2(充电电流)" % v)
    if 0x20 in seen and (0x20 & 0x04):
        viol.append("0x20 置了 b2(充电电流)")
    coverage = len([v for v in seen if v != 0])
    out.append({
        "id": "H3",
        "claim": "状态字节是位域：b5=电源在位, b2=充电电流",
        "verdict": ("FAIL" if viol else ("PASS" if coverage >= 3 else "INCONCLUSIVE")),
        "detail": ("违反 %d 条：%s" % (len(viol), "; ".join(viol))) if viol
                  else "观测到 %d 个非零取值 %s，全部符合位域规律" %
                       (coverage, ", ".join("0x%02X" % v for v in seen)),
    })

    # H4 满电平台
    if 0x20 in res["status"] and res["status"][0x20]["n"] >= 30:
        raws = res["status"][0x20]["raws"]
        med = _median(raws)
        out.append({
            "id": "H4",
            "claim": "0x20（充电完成）读数落在 ≈3670 平台（3663~3713）",
            "verdict": "PASS" if 3663 <= med <= 3713 else "FAIL",
            "detail": "0x20 段 %d 帧，读数 %d~%d，中位数 %d" % (len(raws), min(raws), max(raws), med),
        })
    else:
        out.append({
            "id": "H4",
            "claim": "0x20（充电完成）读数落在 ≈3670 平台（3663~3713）",
            "verdict": "INCONCLUSIVE",
            "detail": "本次未观测到足量 0x20 样本（需充到满电并保持连接）",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Switch 2 Pro 只读跨设备复现采集器")
    ap.add_argument("--minutes", type=float, default=30.0, help="采集时长（默认 30 分钟，勿低于 24）")
    ap.add_argument("--csv", help="逐帧落盘 CSV（可选）")
    ap.add_argument("--json", help="报告 JSON 输出路径（默认 repro_report.json）")
    ap.add_argument("--fw", default="unknown", help="手柄固件版本（在 Switch 2 设置页手抄）")
    ap.add_argument("--note", default="", help="拓扑备注，如 原装线+官方底座 / 第三方线")
    a = ap.parse_args()

    hid = _hid()
    h, dev = open_device(hid)
    if h is None:
        print("[FAIL] 未发现 0x057E:0x2069。请插上手柄 USB，确认系统已识别到 HID 设备。")
        return 2

    print("=" * 62)
    print("Switch 2 Pro 只读复现采集器（不向设备发送任何字节）")
    print("=" * 62)
    fp = fingerprint(dev)
    print("  设备：%s  usage=0x%04X/0x%04X  iface=%s  product=%s" %
          (fp["vid_pid"], fp["usage_page"] or 0, fp["usage"] or 0, fp["interface"], fp["product"]))
    print("  固件：%s  备注：%s" % (a.fw, a.note or "-"))
    print("  提示：采集期间请勿拔线、勿让电脑睡眠；时长必须 ≥24 分钟才能验回绕。")
    print("-" * 62)

    res = collect(h, a.minutes, a.csv)
    try:
        h.close()
    except Exception:
        pass

    v = verdicts(res)
    census = {("0x%02X" % k): {"frames": s["n"],
                              "raw_min": min(s["raws"]), "raw_max": max(s["raws"]),
                              "raw_median": _median(s["raws"]),
                              "first": s["first"], "last": s["last"]}
              for k, s in sorted(res["status"].items())}

    print("-" * 62)
    print("  时长 %.1f 分钟 / %d 帧 / 设备时钟 %.1f Hz（主机吞吐 %.1f Hz）/ 掉帧 %d" %
          (res["duration_s"] / 60, res["frames"], res["rate_hz"], res["wall_rate_hz"], res["lost"]))
    print("  状态字节普查：")
    for k, c in census.items():
        print("    %s  %5d 帧  读数 %d~%d (中位 %d)  %s→%s" %
              (k, c["frames"], c["raw_min"], c["raw_max"], c["raw_median"], c["first"], c["last"]))
    print("  假设判定：")
    for x in v:
        print("    [%-12s] %s" % (x["verdict"], x["claim"]))
        print("                  %s" % x["detail"])

    report = {"generated": datetime.now().isoformat(timespec="seconds"),
              "firmware": a.fw, "note": a.note, "device": fp,
              "session": {k: res[k] for k in ("duration_s", "frames", "lost", "rate_hz", "wall_rate_hz")},
              "wraps": res["wraps"], "status_census": census, "verdicts": v}
    out = a.json or "repro_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("-" * 62)
    print("  报告已写入：%s" % os.path.abspath(out))
    print("  请把这个文件（或上面这段输出）贴到仓库 issue 里，注明固件版本与线材/底座型号。")
    return 0 if all(x["verdict"] != "FAIL" for x in v) else 1


if __name__ == "__main__":
    sys.exit(main())
