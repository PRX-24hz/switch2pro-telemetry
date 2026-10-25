#!/usr/bin/env python3
"""分析 imu_tail_probe.py 产出的尾部字节 CSV：找出「晃动窗口」并量化各字节对运动的响应。

做三件事：
1. 逐字节统计全局取值范围 / 不同取值数 / 相邻帧变化率（delta 命中率）
2. 按 1 秒分箱算「活跃度」（该秒内不同取值数 + 帧间变化率），定位晃动区间
3. 输出静止段 vs 晃动段对照表，判断哪些字节真正携带运动信息

用法：python analyze_imu_ab.py <csv>
"""
import sys, csv
from collections import defaultdict, Counter


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        head = next(r)
        rows = [row for row in r if row]
    return head, rows


def main(path):
    head, rows = load(path)
    cols = head[3:]                      # 从 0x23 开始
    idx = {c: i + 3 for i, c in enumerate(cols)}
    t = [float(r[0]) for r in rows]
    dur = t[-1]
    print(f"总帧数 {len(rows)}，时长 {dur:.1f}s，平均 {len(rows)/dur:.0f} Hz\n")

    data = {c: [int(r[idx[c]]) for r in rows] for c in cols}

    # --- 1. 逐字节全局统计 ---
    print("字节    取值数  最小  最大   帧间变化率   len>=2?")
    stat = {}
    for c in cols:
        v = data[c]
        uniq = len(set(v))
        chg = sum(1 for i in range(1, len(v)) if v[i] != v[i - 1]) / max(1, len(v) - 1)
        stat[c] = (uniq, min(v), max(v), chg)
        print(f"{c:6s} {uniq:6d} {min(v):5d} {max(v):5d}   {chg*100:8.2f}%   {'是' if uniq > 1 else '否'}")

    # --- 2. 按秒分箱活跃度 ---
    # 活跃度 = 每秒内 (不同取值数/该秒帧数) 与 (帧间变化率) 的乘积，归一化后取对数前的直观量
    bins = defaultdict(lambda: defaultdict(list))
    for i, tt in enumerate(t):
        s = int(tt)
        for c in cols:
            bins[s][c].append(data[c][i])
    secs = sorted(bins)
    print("\n每秒活跃度（变化帧占比 %，只列有明显动静的字节）")
    header = "秒  " + "".join(f"{c:>7s}" for c in cols if stat[c][0] > 1)
    print(header)
    act = {}
    for s in secs:
        line = f"{s:3d} "
        for c in cols:
            if stat[c][0] <= 1:
                continue
            v = bins[s][c]
            chg = sum(1 for i in range(1, len(v)) if v[i] != v[i - 1]) / max(1, len(v) - 1)
            act[(s, c)] = chg
            line += f"{chg*100:7.1f}"
        print(line)

    # --- 3. 自动定位晃动窗口 ---
    # 用变化率最高的字节作为运动指标，取活跃度超过「全局中位数 3 倍」的连续秒段
    cand = [c for c in cols if stat[c][0] > 1]
    if not cand:
        print("\n没有任何字节发生变化。")
        return

    def score(s):
        return sum(act.get((s, c), 0) for c in cand)

    all_scores = [score(s) for s in secs]
    srt = sorted(all_scores)
    med = srt[len(srt) // 2] or 1e-9
    thr = med * 3
    hot = [s for s in secs if score(s) > thr]
    print(f"\n活跃度中位数 {med*100:.2f}%，阈值(3x) {thr*100:.2f}%")
    print(f"疑似晃动秒段：{hot if hot else '无'}")
    if not hot:
        print("=> 判定：尾部字节对运动无响应")
        return
    lo, hi = min(hot), max(hot)

    # --- 4. 静止 vs 晃动 对照 ---
    print(f"\n对照：静止段（{hi+1}s 之后 + {lo}s 之前）vs 晃动段（{lo}~{hi}s）")
    quiet = [i for i, tt in enumerate(t) if tt < lo or tt > hi + 1]
    shake = [i for i, tt in enumerate(t) if lo <= tt <= hi + 1]
    print("字节   静止取值数  晃动取值数   静止max变化率  晃动max变化率")
    for c in cand:
        v = data[c]
        qu, sh = len({v[i] for i in quiet}), len({v[i] for i in shake})

        def rate(idxs):
            if len(idxs) < 2:
                return 0.0
            return sum(1 for a, b in zip(idxs, idxs[1:]) if v[a] != v[b]) / (len(idxs) - 1)
        print(f"{c:6s} {qu:9d} {sh:10d}   {rate(quiet)*100:12.2f}%  {rate(shake)*100:12.2f}%")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: analyze_imu_ab.py <csv>")
    main(sys.argv[1])
