#!/usr/bin/env python3
"""逐事件输出六轴原始极值，并用姿态向量叉积推断真实旋转轴，完成陀螺轴映射。

对每个「运动事件」：
- 加速度计的 min/max/峰峰值（判断是否有平移冲击）
- 陀螺三轴的 min/max 与绝对峰值，指出峰值轴
- 事件前后重力向量的叉积 a1 x a2（归一化）→ 真实旋转轴方向，
  再与陀螺峰值轴比对，确认轴映射与符号

用法：python imu_events.py <csv>
"""
import sys, csv, math, statistics

AX = ["ax", "ay", "az", "gx", "gy", "gz"]


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        return [row for row in r if row and len(row) >= 9]


def main(path):
    rows = load(path)
    t = [float(r[1]) for r in rows]
    d = {a: [float(r[2 + i]) for r in rows] for i, a in enumerate(AX)}

    # 0.25s 中值分箱，用于找平台
    W = 0.25
    bins, cur, ts = [], [], t[0]
    for i, tt in enumerate(t):
        if tt - ts >= W and cur:
            bins.append((ts + W / 2, {a: statistics.median([d[a][j] for j in cur]) for a in AX},
                         (cur[0], cur[-1])))
            cur, ts = [], tt
        cur.append(i)
    if cur:
        bins.append((ts, {a: statistics.median([d[a][j] for j in cur]) for a in AX}, (cur[0], cur[-1])))

    still = [0]
    for i in range(1, len(bins)):
        da = math.hypot(*[bins[i][1][a] - bins[i - 1][1][a] for a in AX[:3]])
        dg = math.hypot(*[bins[i][1][a] - bins[i - 1][1][a] for a in AX[3:]])
        still.append(1 if (da < 300 and dg < 400) else 0)

    segs, c = [], None
    for i, s in enumerate(still):
        if s:
            c = [i, i] if c is None else [c[0], i]
        else:
            if c and c[1] - c[0] + 1 >= 3:
                segs.append(tuple(c))
            c = None
    if c and c[1] - c[0] + 1 >= 3:
        segs.append(tuple(c))

    def plat(a, b):
        return {k: statistics.median([bins[i][1][k] for i in range(a, b + 1)]) for k in AX}

    print("事件   区间(s)        dur   accel峰峰  陀螺峰峰   峰值轴(原始|max|)         姿态变化→旋转轴(归一化叉积)")
    print("-" * 118)
    for i in range(len(segs) - 1):
        a, b = segs[i][1] + 1, segs[i + 1][0] - 1
        if b < a:
            continue
        i0, i1 = bins[a][2][0], bins[b][2][1]
        sl = slice(i0, i1 + 1)
        p2p = [max(d[k][sl]) - min(d[k][sl]) for k in AX]
        gpk = max(max(abs(x) for x in d[k][sl]) for k in AX[3:])
        g_axis = max(range(3), key=lambda j: max(abs(x) for x in d[AX[3 + j]][sl]))
        g_signed = max(d[AX[3 + g_axis]][sl], key=abs)
        before, after = plat(segs[i][0], segs[i][1]), plat(segs[i + 1][0], segs[i + 1][1])
        v1 = [before[k] for k in AX[:3]]
        v2 = [after[k] for k in AX[:3]]
        cross = [v1[1] * v2[2] - v1[2] * v2[1],
                 v1[2] * v2[0] - v1[0] * v2[2],
                 v1[0] * v2[1] - v1[1] * v2[0]]
        n = math.sqrt(sum(x * x for x in cross)) or 1
        cross = [x / n for x in cross]
        ang = math.degrees(math.acos(max(-1, min(1, sum(v1[j] * v2[j] for j in range(3)) /
                                                (math.sqrt(sum(x * x for x in v1)) *
                                                 math.sqrt(sum(x * x for x in v2)))))))
        print(f"  #{i+1:<2d}  {bins[a][0]:6.2f}~{bins[b][0]:6.2f} {bins[b][0]-bins[a][0]+W:5.2f}  "
              f"{max(p2p[:3]):8.0f}  {gpk:8.0f}   {AX[3+g_axis]}({g_signed:+6.0f})   "
              f"{ang:5.1f}° → ({cross[0]:+.2f},{cross[1]:+.2f},{cross[2]:+.2f})")

    print("\n六面重力（用于轴向/符号/灵敏度）")
    print("平台            ax      ay      az     |a|(g)")
    for a, b in segs:
        p = plat(a, b)
        m = math.sqrt(p["ax"] ** 2 + p["ay"] ** 2 + p["az"] ** 2) / 4096
        print(f"  {bins[a][0]:6.2f}s  {p['ax']:7.0f} {p['ay']:7.0f} {p['az']:7.0f}   {m:6.3f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: imu_events.py <csv>")
    main(sys.argv[1])
