#!/usr/bin/env python3
"""把 imu_calib.py 的长记录切成「静止平台 / 运动事件」，用于分轴校准对照。

思路：
1. 按 0.25s 分箱取中值（滤掉传感器噪声，保留姿态台阶）
2. 相邻箱的 6 维欧氏距离 → 变化强度曲线
3. 变化强度低于阈值且持续 >=0.6s 的区间 = 静止平台；其余 = 运动事件
4. 平台输出六轴中值与 |a|；运动事件输出峰值、主导向量、持续时长

用法：python imu_segments.py <csv> [--acc-thr 300] [--gyro-thr 400]
"""
import sys, csv, argparse, statistics, math


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        head = next(r)
        rows = [row for row in r if row and len(row) >= 9]
    return head, rows


def bins_of(rows, width=0.25):
    """按固定时间宽分箱，返回 [(t_center, {axis: median}), ...]"""
    axes = ["ax", "ay", "az", "gx", "gy", "gz"]
    out = []
    cur, t_start = [], None
    for r in rows:
        t = float(r[1])
        v = dict(zip(axes, map(float, r[2:8])))
        if t_start is None:
            t_start = t
        if t - t_start >= width and cur:
            out.append((t_start + width / 2,
                        {a: statistics.median([c[a] for c in cur]) for a in axes}))
            cur, t_start = [], t
        cur.append(v)
    if cur:
        out.append((t_start, {a: statistics.median([c[a] for c in cur]) for a in axes}))
    return out


def main(path, acc_thr, gyro_thr):
    head, rows = load(path)
    bs = bins_of(rows)
    axes = ["ax", "ay", "az", "gx", "gy", "gz"]
    print(f"记录 {float(rows[0][1]):.1f}~{float(rows[-1][1]):.1f}s，{len(rows)} 行，"
          f"分箱 {len(bs)} 个（0.25s）\n")

    # 变化强度
    diff = []
    for i in range(1, len(bs)):
        d = [bs[i][1][a] - bs[i - 1][1][a] for a in axes]
        acc = math.hypot(d[0], d[1], d[2])
        gyr = math.hypot(d[3], d[4], d[5])
        diff.append((bs[i][0], acc, gyr, d))

    # 静止判据：相邻加速度差 < acc_thr 且陀螺差 < gyro_thr
    still = [False] + [1 if (a < acc_thr and g < gyro_thr) else 0 for _, a, g, _ in diff]

    # 找连续静止区（>=0.6s = 至少 3 个箱）
    segs, cur = [], None
    for i, s in enumerate(still):
        if s:
            cur = [i, i] if cur is None else [cur[0], i]
        else:
            if cur and cur[1] - cur[0] + 1 >= 3:
                segs.append(tuple(cur))
            cur = None
    if cur and cur[1] - cur[0] + 1 >= 3:
        segs.append(tuple(cur))

    print("=== 静止平台（六轴中值 + 重力模长）===")
    print("  区间(s)         dur   ax      ay      az     |a|(g)   gx     gy     gz")
    prev = None
    for a, b in segs:
        vals = {k: statistics.median([bs[i][1][k] for i in range(a, b + 1)]) for k in axes}
        amag = math.sqrt(vals["ax"] ** 2 + vals["ay"] ** 2 + vals["az"] ** 2) / 4096
        mark = ""
        if prev is not None:
            jump = max(abs(vals[k] - prev[k]) for k in axes[:3])
            if jump > 300:
                mark = "  <-- 姿态变化"
        t0, t1 = bs[a][0], bs[b][0]
        print(f"  {t0:7.2f}~{t1:7.2f}  {t1-t0+0.25:5.2f}  "
              f"{vals['ax']:6.0f} {vals['ay']:7.0f} {vals['az']:7.0f}  {amag:6.3f}  "
              f"{vals['gx']:5.0f} {vals['gy']:5.0f} {vals['gz']:5.0f}{mark}")
        prev = vals

    print("\n=== 运动事件（平台之间的空档）===")
    print("  区间(s)         dur    accel峰值  gyro峰值  陀螺主导轴  加速主导轴")
    for i in range(len(segs) - 1):
        a, b = segs[i][1] + 1, segs[i + 1][0] - 1
        if b < a:
            continue
        pa = max((d for _, _, _, d in diff[a:b + 1]), key=lambda d: abs(d[0]) + abs(d[1]) + abs(d[2]), default=None)
        pg = max((d for _, _, _, d in diff[a:b + 1]), key=lambda d: abs(d[3]) + abs(d[4]) + abs(d[5]) if len(d) > 5 else 0, default=None)
        if pa is None:
            continue
        gi = max(range(3), key=lambda j: abs(pg[3 + j])) if pg else -1
        ai = max(range(3), key=lambda j: abs(pa[j]))
        print(f"  {bs[a][0]:7.2f}~{bs[b][0]:7.2f}  {bs[b][0]-bs[a][0]+0.25:5.2f}  "
              f"{math.hypot(pa[0],pa[1],pa[2]):8.0f}  {math.hypot(pg[3],pg[4],pg[5]):8.0f}  "
              f"{axes[3+gi] if gi>=0 else '-':>8s}    {axes[ai]:>8s}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--acc-thr", type=float, default=300.0)
    ap.add_argument("--gyro-thr", type=float, default=400.0)
    a = ap.parse_args()
    main(a.csv, a.acc_thr, a.gyro_thr)
