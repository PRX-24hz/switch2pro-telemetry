#!/usr/bin/env python3
"""用「角速度积分 = 姿态转角」标定陀螺：同时确定符号与 LSB/(°/s)。

原理：
- 姿态从 a1 转到 a2，转角 θ = acos(â1·â2)，旋转轴 n̂ = (a1×a2)/|a1×a2|
- 同一区间内陀螺读数积分 I = Σ(ω - bias)·dt，单位 LSB·s
- 若轴映射为 gx/gy/gz ↔ X/Y/Z，则 |I| 在对应轴上应最大，且
      LSB/(°/s) = |I|_轴 / θ
- 符号：I 与 n̂ 在对应轴上的分量同号 → 正装；异号 → 反装

只统计 θ > 30° 的事件（小角度叉积方向不可靠）。

用法：python imu_gyro_fit.py <csv>
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

    W = 0.25
    bins, cur, ts = [], [], t[0]
    for i, tt in enumerate(t):
        if tt - ts >= W and cur:
            bins.append((ts + W / 2, {a: statistics.median([d[a][j] for j in cur]) for a in AX}, (cur[0], cur[-1])))
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
        return [statistics.median([bins[i][1][k] for i in range(a, b + 1)]) for k in AX]

    # 静止零偏：用最长的平台
    longest = max(segs, key=lambda s: s[1] - s[0])
    bias = {k: statistics.median([bins[i][1][k] for i in range(longest[0], longest[1] + 1)]) for k in AX[3:]}
    print(f"陀螺零偏（取自最长静止平台 {bins[longest[0]][0]:.1f}s，{longest[1]-longest[0]+1} 箱）："
          f"gx={bias['gx']:.0f} gy={bias['gy']:.0f} gz={bias['gz']:.0f} LSB\n")

    print("事件   θ(°)   ∫gx     ∫gy     ∫gz    | 主导轴  |I|/(θ)   →LSB/(°/s)  符号  叉积轴")
    print("-" * 112)
    fits = []
    for i in range(len(segs) - 1):
        a, b = segs[i][1] + 1, segs[i + 1][0] - 1
        if b < a:
            continue
        i0, i1 = bins[a][2][0], bins[b][2][1]
        v1, v2 = plat(segs[i][0], segs[i][1]), plat(segs[i + 1][0], segs[i + 1][1])
        n1 = math.sqrt(sum(x * x for x in v1[:3])) or 1
        n2 = math.sqrt(sum(x * x for x in v2[:3])) or 1
        dotv = sum(v1[j] * v2[j] for j in range(3)) / (n1 * n2)
        theta = math.degrees(math.acos(max(-1, min(1, dotv))))
        if theta < 30 or theta > 175:
            continue
        cross = [v1[1] * v2[2] - v1[2] * v2[1],
                 v1[2] * v2[0] - v1[0] * v2[2],
                 v1[0] * v2[1] - v1[1] * v2[0]]
        cn = math.sqrt(sum(x * x for x in cross)) or 1
        cross = [x / cn for x in cross]
        # 梯形积分
        I = [0.0, 0.0, 0.0]
        for j in range(i0 + 1, i1 + 1):
            dt = t[j] - t[j - 1]
            for k in range(3):
                w0 = d[AX[3 + k]][j - 1] - bias[AX[3 + k]]
                w1 = d[AX[3 + k]][j] - bias[AX[3 + k]]
                I[k] += (w0 + w1) / 2 * dt
        ax_i = max(range(3), key=lambda k: abs(I[k]))
        scale = abs(I[ax_i]) / theta if theta else 0
        # 符号：积分方向与叉积在该轴上的分量是否同号
        sgn = "同" if I[ax_i] * cross[ax_i] > 0 else "反"
        fits.append((theta, ax_i, scale, cross[ax_i]))
        print(f" #{i+1:<2d} {theta:6.1f} {I[0]:8.0f} {I[1]:8.0f} {I[2]:8.0f}  | "
              f"{AX[3+ax_i]:>5s}  {abs(I[ax_i]):7.0f}   {scale:8.2f}     {sgn}   "
              f"({cross[0]:+.2f},{cross[1]:+.2f},{cross[2]:+.2f})")

    if fits:
        print("\n== 按轴汇总 LSB/(°/s) 估计 ==")
        for k, nm in enumerate(["X", "Y", "Z"]):
            vals = [f[2] for f in fits if f[1] == k]
            if vals:
                print(f"  {nm} 轴: n={len(vals)}  中值 {statistics.median(vals):.2f}  "
                      f"范围 {min(vals):.1f}~{max(vals):.1f}")
        print("\n  参考量程对照：±250dps→131 LSB/(°/s)  ±500dps→65.5  ±1000dps→32.8  ±2000dps→16.4")
        print("  （以上按 16 位、满量程 32768 计）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: imu_gyro_fit.py <csv>")
    main(sys.argv[1])
