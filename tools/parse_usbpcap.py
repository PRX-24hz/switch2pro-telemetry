#!/usr/bin/env python3
"""解析 USBPcap 生成的 pcap（DLT_USBPCAP=249），把 Steam 启动瞬间的 USB 命令挖出来。

USBPcap 包头 28 字节（小端，packed）：
  headerLen u16 | irpId u64 | status u32 | function u16 | info u16
  bus u16 | device u16 | endpoint u8 | transfer u8 | dataLength u32
transfer: 0=ISO 1=INTERRUPT 2=CONTROL 3=BULK
info bit0: 0 = 主机提交(请求), 1 = 设备完成(回调)
端点 0 + transfer=CONTROL 的 data 前 8 字节 = setup packet:
  bmRequestType u8 | bRequest u8 | wValue u16 | wIndex u16 | wLength u16

用法:
  python parse_usbpcap.py <pcap> summary      # 总体统计
  python parse_usbpcap.py <pcap> ctrl         # 所有控制传输的 setup + 数据
  python parse_usbpcap.py <pcap> timeline     # 报告流起始时刻与节奏
"""
import struct, sys
from collections import Counter, defaultdict
from datetime import datetime

XFER = {0: "ISO", 1: "INT", 2: "CTRL", 3: "BULK"}


def read_pcap(path):
    d = open(path, "rb").read()
    magic = d[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        e = "<"
    elif magic == b"\xa1\xb2\xc3\xd4":
        e = ">"
    else:
        raise SystemExit("不是经典 pcap（magic=%s），可能是 pcapng" % magic.hex())
    _, vmaj, vmin, tz, sig, snap, network = struct.unpack(e + "IHHiIII", d[:24])
    print(f"pcap v{vmaj}.{vmin}  snaplen={snap}  linktype={network}"
          f"{'  (DLT_USBPCAP)' if network == 249 else '  !! 非 USBPcap'}")
    off, pkts = 24, []
    while off + 16 <= len(d):
        ts, tus, incl, orig = struct.unpack(e + "IIII", d[off:off + 16])
        off += 16
        pkts.append((ts + tus / 1e6, d[off:off + incl]))
        off += incl
    return pkts


def parse_usbpcap(pkt):
    if len(pkt) < 26:
        return None
    # 注意：status 是 USHORT(2)，不是 ULONG。写错 2 字节会让后续字段全部错位。
    hl, irp, status, func, info, bus, dev, ep, xfer, dlen = \
        struct.unpack("<HQHHHHHBBI", pkt[:26])
    data = pkt[hl:hl + dlen]
    return dict(hl=hl, irp=irp, status=status, func=func, info=info,
                bus=bus, dev=dev, ep=ep, xfer=xfer, dlen=dlen, data=data)


def setup_of(p):
    """从控制传输包中取 setup packet（前 8 字节）"""
    if p["xfer"] != 2 or len(p["data"]) < 8:
        return None
    bm, br, wv, wi, wl = struct.unpack("<BBHHH", p["data"][:8])
    # 合理性检查：wLength 通常等于 data 长度 - 8（IN 请求时只带 setup）
    return dict(bm=bm, br=br, wv=wv, wi=wi, wl=wl, body=p["data"][8:])


def main(path, mode):
    pkts = read_pcap(path)
    print(f"总包数 {len(pkts)}\n")
    recs = []
    for t, raw in pkts:
        p = parse_usbpcap(raw)
        if p:
            p["t"] = t
            recs.append(p)
    print(f"解析成功 {len(recs)} 个 USB 包\n")

    devs = Counter((r["bus"], r["dev"]) for r in recs)
    print("== 设备地址分布（bus, dev）==")
    for (b, d), n in devs.most_common(10):
        eps = sorted({r["ep"] for r in recs if (r["bus"], r["dev"]) == (b, d)})
        print(f"  bus={b} dev={d:<3d}  {n:6d} 包  端点 {[hex(x) for x in eps]}")
    print()

    if mode == "summary":
        print("== 传输类型 ==")
        for k, n in Counter(XFER.get(r["xfer"], str(r["xfer"])) for r in recs).most_common():
            print(f"  {str(k):>5s}: {n}")
        print("\n== 中断端点的报告 ID 分布 ==")
        rid = Counter()
        for r in recs:
            if r["xfer"] == 1 and r["data"]:
                rid[(r["ep"], r["data"][0])] += 1
        for (ep, i), n in rid.most_common(12):
            print(f"  ep 0x{ep:02X}  report 0x{i:02X}: {n}")

    elif mode == "ctrl":
        print("== 控制传输（host→device 为主）==")
        print("   时间(s)    dev ep  st   bmReq br   wValue wIndex wLen  说明")
        t0 = recs[0]["t"] if recs else 0
        n = 0
        for r in recs:
            s = setup_of(r)
            if not s:
                continue
            if s["bm"] & 0x80:            # 设备→主机（GET_*）先跳过
                continue
            n += 1
            kind = ""
            if s["bm"] == 0x21 and s["br"] == 0x09:
                kind = "SET_REPORT"
            elif s["bm"] == 0x21 and s["br"] == 0x0A:
                kind = "SET_IDLE"
            elif s["br"] == 0x09:
                kind = "SET_CONFIGURATION"
            elif s["bm"] == 0x21:
                kind = f"class-req 0x{s['br']:02X}"
            print(f"  {r['t']-t0:8.3f}  {r['dev']:3d} {r['ep']:02X} {r['status']:3d}  "
                  f"0x{s['bm']:02X}   0x{s['br']:02X} 0x{s['wv']:04X} 0x{s['wi']:04X} {s['wl']:4d}  {kind}")
            if s["body"]:
                print(f"           data: {s['body'][:24].hex(' ')}")
            if n > 200:
                print("  ...（截断）")
                break
        print(f"\n共 {n} 条 host→device 控制传输")

    elif mode == "timeline":
        t0 = recs[0]["t"]
        print("== 中断 IN 包的时间分布（每秒一个桶）==")
        buckets = defaultdict(lambda: Counter())
        for r in recs:
            if r["xfer"] == 1 and r["data"] and not (r["ep"] & 0x80) == 0:
                buckets[int(r["t"] - t0)][r["data"][0]] += 1
        for s in sorted(buckets):
            items = "  ".join(f"0x{k:02X}:{v}" for k, v in buckets[s].most_common(4))
            print(f"  {s:3d}s  {items}")
        first = next((r for r in recs if r["xfer"] == 1 and r["data"]), None)
        if first:
            print(f"\n首个中断包在 t={first['t']-t0:.3f}s，report 0x{first['data'][0]:02X}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
