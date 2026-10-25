#!/usr/bin/env python3
"""把 0x2B~0x3C 按「16 位小端成对」拆开，做静止/晃动对照，验证 IMU 假设。

关键判据：
- 若某对是 16 位传感器读数，静止时低字节(offset+0)高频抖动、高字节(offset+1)几乎不变；
  晃动时高字节开始大幅变化 —— 这一「高字节从冻结到解冻」的跃迁是 IMU 的指纹。
- 纯计数器（如时间戳）则在静止时也是每帧必变，两字节同步活跃。

用法：python imu_pairs.py <csv>
"""
import sys, csv, statistics


def main(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        head = next(r)
        rows = [row for row in r if row]
    idx = {c: i for i, c in enumerate(head)}
    t = [float(row[0]) for row in rows]
    b = {c: [int(row[idx[c]]) for row in rows] for c in head[3:]}

    # 晃动窗口由「偶数偏移字节」的活动量自动判定（这些字节静止时为 0）
    even = ["0x%02X" % o for o in range(0x24, 0x40, 2)]
    even = [c for c in even if c in b]
    per_sec = {}
    for s in range(int(t[-1]) + 1):
        ids = [i for i, tt in enumerate(t) if int(tt) == s]
        if len(ids) < 2:
            continue
        hit = 0
        for c in even:
            v = b[c]
            hit += sum(1 for a, z in zip(ids, ids[1:]) if v[a] != v[z])
        per_sec[s] = hit / (len(ids) - 1) / len(even)
    active = [s for s, v in per_sec.items() if v > 0.25]
    lo, hi = (min(active), max(active)) if active else (0, 0)
    print(f"自动判定的运动窗口：第 {lo}s ~ 第 {hi}s（{hi-lo+1}s）\n")

    q = [i for i, tt in enumerate(t) if tt < lo or tt > hi + 1]
    k = [i for i, tt in enumerate(t) if lo <= tt <= hi + 1]

    def stats(vals):
        return (min(vals), max(vals), statistics.mean(vals), statistics.pstdev(vals))

    print("== 16 位小端成对字段 ==")
    print("字段        静止 min/max     静止均值±σ     晃动 min/max     晃动均值±σ     σ比")
    for o in range(0x2B, 0x3D, 2):
        lo_c, hi_c = "0x%02X" % o, "0x%02X" % (o + 1)
        if lo_c not in b or hi_c not in b:
            continue
        raw = [b[lo_c][i] | (b[hi_c][i] << 8) for i in range(len(t))]
        signed = [x - 65536 if x >= 32768 else x for x in raw]
        sq, sk = [signed[i] for i in q], [signed[i] for i in k]
        a, c2 = stats(sq), stats(sk)
        ratio = (c2[3] / a[3]) if a[3] > 0 else float("inf")
        print(f"{lo_c}:{hi_c}  {a[0]:6d}/{a[1]:-6d}  {a[2]:9.1f}±{a[3]:6.1f}  "
              f"{c2[0]:6d}/{c2[1]:-6d}  {c2[2]:9.1f}±{c2[3]:6.1f}  {ratio:6.1f}x")

    print("\n== 单字节活跃度（静止 → 晃动，帧间变化率）==")
    for c in ["0x%02X" % o for o in range(0x23, 0x40)]:
        if c not in b:
            continue
        v = b[c]
        def rate(ids):
            if len(ids) < 2:
                return 0.0
            return sum(1 for x, y in zip(ids, ids[1:]) if v[x] != v[y]) / (len(ids) - 1)
        print(f"  {c}  静止 {rate(q)*100:6.2f}%   晃动 {rate(k)*100:6.2f}%   "
              f"取值数 {len(set(v))}")

    print("\n== 0x2B:0x2C 是否为计数器（取前 20 帧与差分样本）==")
    raw = [b["0x2B"][i] | (b["0x2C"][i] << 8) for i in range(len(t))]
    print("  前 20 个值:", raw[:20])
    d = [raw[i] - raw[i - 1] for i in range(1, min(400, len(raw)))]
    print("  前 400 帧差分取值:", sorted(set(d))[:15], "..." if len(set(d)) > 15 else "")
    print(f"  单调递增帧占比: {sum(1 for x in d if x > 0)/len(d)*100:.1f}%")

    print("\n== 0x2F:0x30 的 16 位值随时间的演化（每 5 秒取一帧）==")
    sig = [b["0x2F"][i] | (b["0x30"][i] << 8) for i in range(len(t))]
    for s in range(0, int(t[-1]) + 1, 5):
        ids = [i for i, tt in enumerate(t) if int(tt) == s]
        if not ids:
            continue
        vals = {sig[i] for i in ids}
        print(f"  {s:3d}s  {sorted(vals)}  非零帧占比 {sum(1 for i in ids if sig[i])/len(ids)*100:5.1f}%")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: imu_pairs.py <csv>")
    main(sys.argv[1])
