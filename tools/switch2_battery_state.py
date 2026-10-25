#!/usr/bin/env python3
"""Switch 2 Pro 手柄电量状态分类器（轻量滑动窗口，纯只读）。

输入：实时帧流（读数 raw + 充电状态字节 status），1Hz 即可。
输出四个业务状态：
  DISCHARGING   低占空比 + 读数长期下行（USB 供电下极少见，留给未来 BLE）
  FAST_CHARGING 低占空比（充电器持续导通）—— 恒流/恒压大电流段
  TOPPING_OFF   中等占空比（充电器开始斩波）—— 涓流/补电段
  FULL          仅由 status==0x20 判定（占空比高只说明仍在维持，不等于已满）

为什么「占空比」是主信号、而不是斜率：
  实测读数在平台期以 ±20mV 抖动（0x00 采样系统性低 20mV），而快充的真实爬升只有
  +7mV/min（=0.117mV/s）。120s 窗口内噪声 >> 信号，斜率根本无法可靠估计。
  而 0x00 斩波占空比是干净的 0/1 统计，且随充电推进单调爬升（0%→16%→40%→70%→80%），
  是满电最稳健的连续信号。

满电准则（通用，不依赖任何单一字节值）：
  「0x00 斩波占空比 >= 75% 且读数平台不再上行」——与实机一致：满电时红灯熄灭、
  主机显示满电，同期占空比 79~85%、读数平台 3663~3684。
"""
from collections import deque
from dataclasses import dataclass
from enum import Enum
import csv, sys, time
from statistics import median


class State(Enum):
    DISCHARGING = "Discharging"
    FAST_CHARGING = "FastCharging"
    TOPPING_OFF = "ToppingOff"
    FULL = "Full"
    GENERIC_CHARGING = "GenericCharging"          # 未知状态字节的降级态（防御性）


KNOWN_STATUSES = frozenset({0x2C, 0x34, 0x24, 0x3C, 0x00})  # 实测已知集合（0x3C 为 2026-10-24 新观测）
FULL_STATUS = 0x20                                      # 充电完成（2026-10-24 09:42 实测确认存在）
NOMINAL_MIN, NOMINAL_MAX = 3520, 3680                   # 基础标定区间（防御性，防上下溢）


@dataclass
class _Sample:
    t: float
    raw: int
    status: int


class BatteryStateClassifier:
    def __init__(self,
                 duty_window: float = 120.0,     # 占空比统计窗口（秒）
                 trend_window: float = 600.0,    # 读数趋势窗口（秒）
                 full_duty: float = 0.75,        # 已废弃：原"满电占空比"双阈值之一，现只用 top_duty 单阈值
                 top_duty: float = 0.15,         # 进入涓流段的占空比门槛
                 full_release: float = 0.50,     # 已满后退出满电的占空比下限（施密特回差）
                 trend_thr: float = 8.0,         # 趋势阈值（读数，单位同 raw）：首末各半中位数差
                 dwell: float = 30.0,            # 状态滞回（秒）
                 on_statuses=frozenset({0x2C, 0x34, 0x24, 0x3C})):
        self.duty_window = duty_window
        self.trend_window = trend_window
        self.full_duty = full_duty
        self.top_duty = top_duty
        self.full_release = full_release
        self.trend_thr = trend_thr
        self.dwell = dwell
        self.on_statuses = on_statuses
        self._buf = deque()                      # 占空比 + 趋势共用一个环形缓冲
        self._state = State.FAST_CHARGING        # USB 供电下默认视为充电，直至证伪
        self._cand = State.FAST_CHARGING
        self._cand_since = None
        self.last_status: int | None = None      # 最近一帧状态字节（供副状态栏 Raw 标注）
        self.unknown_status: int | None = None

    @property
    def state(self) -> State:
        return self._state

    @staticmethod
    def clamp_percent(pct: float) -> int:
        """百分比截断到 [0,100]，严禁向 UI 抛出负数或 >100 的非法值。"""
        return max(0, min(100, int(round(pct))))

    def estimate_percent(self, raw: int) -> int:
        """工程估算百分比（**非真实 SoC**，仅供 UI 参考）。越界即截断。"""
        if raw <= NOMINAL_MIN: return 0
        if raw >= NOMINAL_MAX: return 100
        return self.clamp_percent((raw - NOMINAL_MIN) / (NOMINAL_MAX - NOMINAL_MIN) * 100)

    @property
    def duty00(self) -> float:
        if not self._buf:
            return 0.0
        return sum(1 for s in self._buf if s.status == 0x00) / len(self._buf)

    def _trend_delta(self) -> float:
        """导通采样（status != 0x00）读数在前半窗与后半窗的中位数差。数据不足返回 0。"""
        on = [(s.t, s.raw) for s in self._buf if s.status in self.on_statuses]
        if len(on) < 20:
            return 0.0
        mid = (on[0][0] + on[-1][0]) / 2.0
        a = median(y for t, y in on if t < mid)
        b = median(y for t, y in on if t >= mid)
        return b - a

    def feed(self, raw: int, status: int, t: float | None = None) -> State:
        self.last_status = status
        if status == FULL_STATUS:                    # 0x20：充分非必要 → 无条件满电（IsFull=100%）
            self._state = State.FULL
            return self._state
        if status not in KNOWN_STATUSES:             # 未知字节（过热/过放/供电异常）→ 降级，不抛异常不判离线
            self._state = State.GENERIC_CHARGING
            self.unknown_status = status
            return self._state
        t = time.monotonic() if t is None else t
        self._buf.append(_Sample(t, raw, status))
        # 同时裁剪两个窗口（保留更长的 trend_window 数据，占空比只取最近 duty_window 秒）
        while self._buf and t - self._buf[0].t > self.trend_window:
            self._buf.popleft()

        duty_buf = [s for s in self._buf if t - s.t <= self.duty_window]
        # 占空比窗口覆盖 ≥20s 即可判定（实机 20s 内斩波占比已稳定，60s 会让冷启动卡 90s）
        if t - duty_buf[0].t < 20.0:
            return self._state

        cand = self._classify(duty_buf)
        # 冷启动快速通道：满电插上时全程只有 0x00/0x24、绝无 0x2C/0x34（实测），
        # 此时无需等 dwell，直接进 Full，避免 App 启动后 90 秒还显示"快充中"。
        if (cand is State.FULL and self._state is not State.FULL
                and not any(s.status in (0x2C, 0x34) for s in duty_buf)):
            self._state, self._cand, self._cand_since = State.FULL, State.FULL, t
            return self._state
        if cand != self._cand:
            self._cand, self._cand_since = cand, t
        elif self._cand_since is not None and t - self._cand_since >= self.dwell:
            self._state = cand
        return self._state

    def _classify(self, duty_buf) -> State:
        d = sum(1 for s in duty_buf if s.status == 0x00) / len(duty_buf)
        delta = self._trend_delta()
        # 满电确定态带施密特回差：一旦满电，不因轻微补电/斩波抖动退出
        if self._state is State.FULL:
            if delta >= self.trend_thr:            # 真有新一轮大电流充电
                return State.FAST_CHARGING
            if d < self.full_release:              # 占空比明显回落到 50% 以下才算离满
                return State.TOPPING_OFF
            return State.FULL
        # 占空比高 ≠ 已满：实测 90% 占空比仍维持了数小时，之后又做了一轮 10 分钟真充。
        # Full 只由 status==0x20 触发；占空比只表达"不充电的时间占比"。
        # 只设一个阈值：0.15~1.0 都只是"维持程度"，不再用 0.75 二次细分（那是死分支）。
        if d >= self.top_duty:
            return State.TOPPING_OFF
        # 走到这里：>85% 时间在充电族(0x34/0x2C/0x24)，即真的在充电。
        # Discharging 在本只读 USB 通道下几乎不可达（0x20 已在 feed 顶部返回 Full），
        # 保留用于：① 未知固件防御；② 未来 BLE 通道；③ "充电态却读数下行"的异常标记。
        # 已知误触：边充边玩 + 震动会让 delta 短暂 <= -threshold，生产实现应加 30s 滞回。
        if delta <= -self.trend_thr:
            return State.DISCHARGING
        return State.FAST_CHARGING                 # 低占空比 + 非下行 → 大电流充电


# ---- 回放验证 ----
def replay(csv_path):
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8"))
            if r["timestamp"] >= "2026-10-24 06:11"]
    clf = BatteryStateClassifier()
    prev, changes = None, []
    for r in rows:
        t = float(r["elapsed_sec"])
        st = clf.feed(int(r["voltage_mv"]), int(r["status_hex"], 16), t)
        if st is not prev:
            changes.append((r["timestamp"][11:], t, prev, st, int(r["voltage_mv"])))
            prev = st
    print(f"输入 {len(rows)} 帧（{rows[0]['timestamp'][11:]} → {rows[-1]['timestamp'][11:]}）")
    print("状态迁移：")
    for ts, t, a, b, mv in changes:
        print(f"  {ts}  t={t:6.0f}s  {a} → {b}  (读数 {mv})")
    print(f"末态：{clf.state.value}  占空比={clf.duty00:.0%}  趋势Δ={clf._trend_delta():+.1f}")
    return clf


if __name__ == "__main__":
    replay(sys.argv[1] if len(sys.argv) > 1 else "sw2_charge.csv")
