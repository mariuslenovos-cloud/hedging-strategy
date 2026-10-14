#!/usr/bin/env python3
"""
run_t2one_bt.py -- headless backtest of the MM t2one live-order config on the PEP runner (2026-09-29).

Answers, from the tester instead of a 20-day forward clock, the items still open before t2one goes to
the two live accounts: a RISING-gold stretch, the loss-streak tail, the worst 4-week stretch, and whether
SELL-only is an edge or a regime bet (the BUY-side cell).

CONTROL first: the demo's own t2one record (09-22 -> 09-29, 33 ladders / +$293 / 28 wins, from
mm_babysit_20260929) must reproduce on the runner's 100%-tick window. If it does not, the table is VOID.

Fidelity note: the ladder enters at market and exits on BROKER SL/TP at fixed levels -- the class the
09-06 LongVol finding showed is insensitive to generated-vs-real ticks (42/42 trades matched to the cent).
The runner's XAUUSD tick store starts 2026-08-28; earlier months are generated from M1.

Runner guards carried from run_frz_ab.py: BOM-less ini, [Experts] Enabled=0, [Common] Login pinned,
stale report purged, report must post-date the launch, the run's own log must show login + sync.

usage:  python run_t2one_bt.py [CELL ...]      (default: all cells in ORDER)
"""
import io, os, re, glob, subprocess, sys, time, statistics
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_EXE = r"C:\MT5 Pepperstone Runner\terminal64.exe"
RUNNER_DATA = r"C:\MT5 Pepperstone Runner"
SETDIR = os.path.join(RUNNER_DATA, r"MQL5\Profiles\Tester")
INIDIR = os.path.join(HERE, "analysis_data", "tester_ini")
OUT = os.path.join(HERE, "analysis_data", "t2one_bt_results.txt")
os.makedirs(INIDIR, exist_ok=True); os.makedirs(SETDIR, exist_ok=True)

EXPERT, SYMBOL, PERIOD, MODEL, DEPOSIT = "MM_ShadowLogger", "XAUUSD", "M1", 4, 2678
FULL = ("2025.12.01", "2026.09.30")
CTL = ("2026.09.22", "2026.09.30")
ANCHOR = dict(ladders=33, wins=28, net=292.96)          # demo t2one, mm_babysit_20260929 section B/G

# the t2one preset from the demo (MQL5\Profiles\MM_ShadowLogger_t2one.set), verbatim
BASE = OrderedDict([
    ("InpSensitivity", "2.5"), ("InpAtrPeriod", "10"), ("InpMinTier", "2"), ("InpCloudBasis", "50"),
    ("InpCloudOuterATR", "3.5"), ("InpEmaTrend", "200"), ("InpMtfMinAgree", "4"), ("InpVolLookback", "50"),
    ("InpMinVolDots", "1"), ("InpEffRatioBars", "30"), ("InpAdxPeriod", "14"), ("InpMaxBarsInTrade", "720"),
    ("InpSpreadCostR", "1.0"), ("InpChargeSpread", "true"), ("InpStopMode", "1"), ("InpStopAtrTF", "5"),
    ("InpStopAtrPeriod", "14"), ("InpStopAtrMult", "2.33"), ("InpTrade", "true"), ("InpLotsPerRung", "0.01"),
    ("InpMaxOpen", "3"), ("InpReverseOnOpposite", "false"), ("InpMinHoldMinutes", "0"),
    ("InpAlignEmaTF", "5"), ("InpAlignEmaPeriod", "0"), ("InpTradeStartHour", "0"), ("InpTradeEndHour", "23"),
    ("InpTradeSide", "-1"), ("InpRungR1", "0.5"), ("InpRungR2", "0.5"), ("InpRungR3", "0.5"),
    ("UseBEAfterTP1", "false"), ("BEOffsetR", "0.10"), ("InpCloseMixedInProfit", "true"),
    ("InpMixedMinProfit", "2.0"), ("InpMaxLadderRiskUSD", "0"), ("InpFridayFlattenHour", "0"), ("InpCutOnOpposite", "0"), ("InpMinAdx", "0"), ("InpMaxHoldMinutes", "0"), ("InpMagic", "0"), ("InpRunTag", "t2one"), ("InpVerbose", "false"),
])

CELLS = OrderedDict([
    ("t2_ctl",     dict(win=CTL,  delta={})),                                   # CONTROL: must reproduce the demo
    ("t2_full",    dict(win=FULL, delta={})),                                   # the live candidate, 10 months
    ("t2buy_full", dict(win=FULL, delta={"InpTradeSide": "1", "InpRunTag": "t2buy"})),   # the BUY side = is SELL-only a regime bet?
    ("t2n_full",   dict(win=FULL, delta={"InpTradeStartHour": "22", "InpTradeEndHour": "8", "InpRunTag": "t2onen"})),
    # build N: the fixed-$ risk cap. $45 = a 15-pt stop at 0.01x3; must reproduce the Python cap-15 read
    # (673 ladders / +$1,870 / maxDD -$217 / worst-4wk -$169) = the build's own proof.
    ("t2cap45_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "45"})),
    ("t2cap36_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "36"})),
    ("t2cap45_ctl",  dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "45"})),
    # build N2: cap + Friday 22:00 cutoff/flatten. Must recover the 8 weekend-gap ladders (-$333) and
    # bound the worst ladder at ~the cap; nothing else may change (median hold 24 min).
    ("t2cap45fri_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "45", "InpFridayFlattenHour": "22"})),
    ("t2live_ctl",      dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "45", "InpFridayFlattenHour": "22"})),
    # 2026-10-01 improvement cells on the live config: the build-K alignment gate as a regime filter
    # (SELL only below the M5 EMA200) for the up-month drag, and the cap plateau edges.
    ("t2align200_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "45", "InpFridayFlattenHour": "22", "InpAlignEmaPeriod": "200"})),
    ("t2align100_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "45", "InpFridayFlattenHour": "22", "InpAlignEmaPeriod": "100"})),
    # 2026-10-14 (user: "ensure t2one does not trade against the trend"): the timeframes never tried. SELL only below the EMA.
    # ENUM values: PERIOD_H1=16385, PERIOD_H4=16388. Pre-committed bar vs t2cap40fri_full: net AND maxDD better, both halves.
    ("t2h1e50",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAlignEmaTF": "16385", "InpAlignEmaPeriod": "50"})),
    ("t2h1e200", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAlignEmaTF": "16385", "InpAlignEmaPeriod": "200"})),
    ("t2h4e50",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAlignEmaTF": "16388", "InpAlignEmaPeriod": "50"})),
    ("t2h4e200", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAlignEmaTF": "16388", "InpAlignEmaPeriod": "200"})),
    ("t2cap40fri_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22"})),
    ("t2cap50fri_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "50", "InpFridayFlattenHour": "22"})),
    # 2026-10-01: the ZERO-INPUT cell (make_mm_cells.py) run with NO set file -- must reproduce
    # t2cap40fri_full (622 ladders / +$2,084 / maxDD -$176) = proof the baked constants equal the preset.
    # 2026-10-08 exit-policy round on the LIVE config (cap 40 + Friday 22): the fires CSV can only score 0.5R
    # targets for this cell (tp2/tp3 columns = InpRungR2/R3 = 0.5), so the wider targets run as real cells.
    ("t2r075_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpRungR1": "0.75", "InpRungR2": "0.75", "InpRungR3": "0.75"})),
    ("t2r10_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpRungR1": "1.0", "InpRungR2": "1.0", "InpRungR3": "1.0"})),
    ("t2r20_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpRungR1": "2.0", "InpRungR2": "2.0", "InpRungR3": "2.0"})),
    ("t2vbe_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpRungR1": "0.5", "InpRungR2": "1.0", "InpRungR3": "1.5", "UseBEAfterTP1": "true"})),
    # 2026-10-08 build N3: cut the open ladder on the opposite-side fire WITHOUT reversing (InpTradeSide=-1 never
    # reached the reversal code). Specimen: all 35 stopped demo fires had the flip BEFORE the stop at ~-0.48R.
    # Pre-committed bar: beat t2cap40fri_full (622 / +$2,084 / maxDD -$176 / worst-4wk -$76) on net AND DD.
    ("t2cut_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpCutOnOpposite": "1"})),
    ("t2cut_ctl",    dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpCutOnOpposite": "1"})),
    # mode 2 = cut on ANY opposite flip = the policy the demo fires CSV scored +18R vs -0.4R on 107 fires (which could not see winners a flip cuts first)
    ("t2cut2_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpCutOnOpposite": "2"})),
    ("t2cut2_ctl",   dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpCutOnOpposite": "2"})),
    # 2026-10-08 (3) user: "find a fix" -- structurally different classes. Slower trigger on the t2one geometry
    # (s40 was only tested with reverse-on + 0.5/1/1.5 rungs); a two-sided regime-switched engine is scored offline.
    ("t2s40_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpSensitivity": "4.0", "InpAtrPeriod": "20"})),
    ("t2s30_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpSensitivity": "3.0", "InpAtrPeriod": "14"})),
    ("t2buy40_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpTradeSide": "1", "InpRunTag": "t2buy"})),
    # 2026-10-08 (3): ADX-at-fire gate -- the one survivor of a feature x tercile scan on the tester's 768 SELL tier>=2 fires
    # (adx<26.7 -0.03R both halves; adx>34.4 +0.10R both halves). Pre-committed bar vs t2cap40fri_full ($2,096/622/maxDD -175/w4 -76):
    # a monotonic plateau that keeps >= ~net at materially lower DD, or raises net at equal DD; a lone-cell spike does not deploy.
    ("t2adx27_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMinAdx": "27"})),
    ("t2adx30_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMinAdx": "30"})),
    ("t2adx34_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMinAdx": "34"})),
    ("t2adx30_ctl",   dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMinAdx": "30"})),
    # 2026-10-08 (6): THE STOP -- the one dial never moved. Every prior cell moved the target, gated entries or capped $;
    # none tightened the stop with the PRICE target held constant. Target in price = RungR x Mult x ATR(M5,14) = 1.165 ATR today
    # (0.5 x 2.33); each cell keeps that: 1.50 x 0.78, 1.75 x 0.67, 2.00 x 0.58. The $ cap is scaled with the stop
    # (40 x mult/2.33 = 26 / 30 / 34) so EXACTLY the same fires pass the cap = a clean stop-only A/B against
    # t2cap40fri_full (622 / +$2,096 / maxDD -$175 / worst-4wk -$76). t2stop150c40 keeps cap 40 = the deployable variant.
    # Pre-committed bar: a monotonic plateau across the three proportional cells that retains >= 85% of the ladders and
    # improves net AND maxDD in BOTH halves; a lone cell does not deploy. Fail = the stop is closed too.
    ("t2stop150_full",    dict(win=FULL, delta={"InpMaxLadderRiskUSD": "26", "InpFridayFlattenHour": "22", "InpStopAtrMult": "1.50", "InpRungR1": "0.78", "InpRungR2": "0.78", "InpRungR3": "0.78"})),
    ("t2stop175_full",    dict(win=FULL, delta={"InpMaxLadderRiskUSD": "30", "InpFridayFlattenHour": "22", "InpStopAtrMult": "1.75", "InpRungR1": "0.67", "InpRungR2": "0.67", "InpRungR3": "0.67"})),
    ("t2stop200_full",    dict(win=FULL, delta={"InpMaxLadderRiskUSD": "34", "InpFridayFlattenHour": "22", "InpStopAtrMult": "2.00", "InpRungR1": "0.58", "InpRungR2": "0.58", "InpRungR3": "0.58"})),
    ("t2stop150c40_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpStopAtrMult": "1.50", "InpRungR1": "0.78", "InpRungR2": "0.78", "InpRungR3": "0.78"})),
    # 2026-10-08 (7) build N4: TIME STOP on the real ladder. Measured on the control's own 622 ladders: still open after
    # 60 min -> 62% / -$119; 90 min -> 49% / -$347 (H1 -259, H2 -88); 120 min -> 44% / -$283. The unresolved ladder is a
    # coin flip on a $15/$30 payoff. The 10-08 cut-on-flip cells lost because the flip cut WINNERS early; a time stop
    # only touches ladders that have not resolved. Pre-committed bar vs t2cap40fri_full ($2,096 / maxDD -$175 / w4 -$76):
    # a plateau across 90-180 that improves net AND maxDD in both halves, ladder count within 5% of 622. Lone cell = no deploy.
    ("t2hold60_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxHoldMinutes": "60"})),
    ("t2hold90_full",  dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxHoldMinutes": "90"})),
    ("t2hold120_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxHoldMinutes": "120"})),
    ("t2hold180_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxHoldMinutes": "180"})),
    ("t2hold90_ctl",   dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxHoldMinutes": "90"})),
    # 2026-10-09: the deployment-feed REAL-TICK window (Pepperstone serves real ticks from 2026-08-28 only) on the live config
    ("t2live_rt",    dict(win=("2026.08.28", "2026.10.09"), delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22"})),
    # 2026-10-09 (3): pullback LIMIT entry -- same R geometry from a better price; unfilled limits expire
    ("t2spread17_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpMaxSpreadPts": "17"})),
    ("t2same6_full",    dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAllowSameSide": "true", "InpMaxOpen": "6"})),
    ("t2same9_full",    dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpAllowSameSide": "true", "InpMaxOpen": "9"})),
    ("t2pb02_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpEntryPullbackR": "0.2", "InpEntryExpiryMin": "15"})),
    ("t2pb03_full",   dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpEntryPullbackR": "0.3", "InpEntryExpiryMin": "15"})),
    ("t2pb02x45_full", dict(win=FULL, delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpEntryPullbackR": "0.2", "InpEntryExpiryMin": "45"})),
    ("t2pb02_ctl",    dict(win=CTL,  delta={"InpMaxLadderRiskUSD": "40", "InpFridayFlattenHour": "22", "InpEntryPullbackR": "0.2", "InpEntryExpiryMin": "15"})),
    ("cell_t2one_live_full", dict(win=FULL, delta={}, expert="MM t2one LIVE", noset=True)),
    ("cell_t2one_live_ctl",  dict(win=CTL,  delta={}, expert="MM t2one LIVE", noset=True)),
])
ORDER = list(CELLS)


def write_set(name, delta):
    cfg = OrderedDict(BASE); cfg.update(delta)
    sf = f"t2bt_{name}.set"
    io.open(os.path.join(SETDIR, sf), "w", encoding="utf-16-le").write(
        "\ufeff" + "\n".join(f"{k}={v}" for k, v in cfg.items()) + "\n")
    return sf


def report_paths(rep):
    return [os.path.join(RUNNER_DATA, rep + e) for e in (".htm", ".html")]


def parse_summary(path):
    raw = io.open(path, encoding="utf-16", errors="replace").read()
    t = re.sub(r"<[^>]+>", "|", raw); t = re.sub(r"(\s*\|\s*)+", "|", t)
    def num(label):
        m = re.search(re.escape(label) + r":?\|(-?[\d  ,]+\.\d+)", t)
        return float(m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "")) if m else None
    q = re.search(r"(?:Quality|quality)[^|]*\|(\d+)%", t)
    inp = re.search(r"Inputs:?\|([^|]*(?:\|[^|]*){0,60})", t)
    return dict(net=num("Total Net Profit"), pf=num("Profit Factor"), quality=int(q.group(1)) if q else None,
                inputs=(inp.group(1)[:400] if inp else ""))


def parse_deals(path):
    """deals-table 'out' rows -> [(close_time, pnl incl comm+swap, direction)]"""
    raw = io.open(path, encoding="utf-16", errors="replace").read()
    out = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", raw, re.S):
        cells = [c.strip() for c in re.split(r"</?t[dh][^>]*>", re.sub(r"<(?!/?t[dh])[^>]+>", "", row)) if c.strip()]
        if len(cells) >= 12 and cells[4] == "out" and re.match(r"20\d\d\.\d\d\.\d\d", cells[0]):
            try:
                t = datetime.strptime(cells[0], "%Y.%m.%d %H:%M:%S")
                pnl = sum(float(cells[i].replace(" ", "").replace("\xa0", "")) for i in (8, 9, 10))
                out.append((t, pnl, cells[3]))
            except ValueError:
                continue
    return out


def ladders(deals):
    """group the 3 rungs of a ladder: consecutive out-rows closing within 90 s of each other"""
    lad = []
    for t, p, d in deals:
        if lad and (t - lad[-1]["t"]).total_seconds() <= 90 and lad[-1]["n"] < 3:
            lad[-1]["p"] += p; lad[-1]["n"] += 1; lad[-1]["t"] = t
        else:
            lad.append(dict(t=t, p=p, n=1, d=d))
    return lad


def gold_month_moves():
    """monthly close-to-close % move of gold from the project's own M5/M1 exports (Dec-25 .. Sep-26)"""
    closes = {}
    for fn, tcol in (("xauusd_m5_export.csv", 0), ("xauusd_m1_export.csv", 0)):
        p = os.path.join(HERE, "analysis_data", fn)
        if not os.path.exists(p): continue
        hdr = None
        for line in io.open(p, encoding="utf-8", errors="replace"):
            c = line.strip().split(",")
            if hdr is None:
                hdr = c; ci = next((i for i, h in enumerate(hdr) if h.lower() in ("close", "bid_close", "close_bid")), None)
                if ci is None: break
                continue
            try:
                ts = c[tcol][:7].replace(".", "-"); closes[ts] = float(c[ci])
            except (ValueError, IndexError):
                continue
    months = sorted(closes)
    return {m: (closes[m] / closes[months[i-1]] - 1) * 100 for i, m in enumerate(months) if i > 0}


def analyse(name, path):
    s = parse_summary(path); deals = parse_deals(path); lad = ladders(deals)
    p = [l["p"] for l in lad]
    if not p:
        return f"[{name}] NO LADDERS  quality {s['quality']}%  inputs: {s['inputs']}"
    wins = [x for x in p if x > 0]; loss = [x for x in p if x <= 0]
    # streaks + realized DD + worst rolling 28-day stretch
    eq = pk = dd = 0.0; worst_streak = cur = 0
    for x in p:
        eq += x; pk = max(pk, eq); dd = min(dd, eq - pk)
        cur = cur + 1 if x <= 0 else 0; worst_streak = max(worst_streak, cur)
    worst4 = (0.0, None); ts = [l["t"] for l in lad]
    for i, l in enumerate(lad):
        j = i; tot = 0.0
        while j < len(lad) and (lad[j]["t"] - l["t"]) <= timedelta(days=28):
            tot += lad[j]["p"]; j += 1
        if tot < worst4[0]: worst4 = (tot, l["t"].date())
    gm = gold_month_moves()
    by_m = defaultdict(lambda: [0, 0, 0.0])
    for l in lad:
        k = l["t"].strftime("%Y-%m"); by_m[k][0] += 1; by_m[k][1] += l["p"] > 0; by_m[k][2] += l["p"]
    days = len({l["t"].date() for l in lad})
    lines = [f"[{name}]  quality {s['quality']}%  report net {s['net']}  PF {s['pf']}",
             f"  ladders {len(lad)} over {days} trading days ({len(lad)/max(days,1):.1f}/day)  win {len(wins)}/{len(lad)} = {100*len(wins)/len(lad):.1f}%"
             f"  net ${sum(p):+,.2f}  avgW ${statistics.mean(wins) if wins else 0:+.2f}  avgL ${statistics.mean(loss) if loss else 0:+.2f}"
             f"  worst ladder ${min(p):+.2f}",
             f"  realized maxDD ${dd:,.2f} ({-100*dd/DEPOSIT:.1f}% of ${DEPOSIT})  worst loss streak {worst_streak}"
             f"  worst 28-day stretch ${worst4[0]:+,.2f} (from {worst4[1]})   per day ${sum(p)/max(days,1):+.2f}",
             f"  {'month':8} {'gold%':>7} {'ladders':>8} {'win%':>6} {'net$':>9}"]
    for k in sorted(by_m):
        n, w, net = by_m[k]
        lines.append(f"  {k:8} {gm.get(k, float('nan')):+7.1f} {n:8d} {100*w/n:6.0f} {net:+9.2f}")
    up = [by_m[k][2] for k in by_m if gm.get(k, 0) > 0]; dn = [by_m[k][2] for k in by_m if gm.get(k, 0) < 0]
    lines.append(f"  gold-UP months: {len(up)} net ${sum(up):+,.2f}   gold-DOWN months: {len(dn)} net ${sum(dn):+,.2f}")
    return "\n".join(lines)


def run(name):
    cfg = CELLS[name]; rep = "t2bt_" + name
    expert = cfg.get("expert", EXPERT)
    setref = "" if cfg.get("noset") else f"ExpertParameters={write_set(name, cfg['delta'])}\n"
    ini = os.path.join(INIDIR, rep + ".ini")
    io.open(ini, "w", encoding="utf-8").write(
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n"
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={expert}\n{setref}Symbol={SYMBOL}\nPeriod={PERIOD}\nModel={MODEL}\n"
        f"FromDate={cfg['win'][0]}\nToDate={cfg['win'][1]}\nDeposit={DEPOSIT}\nOptimization=0\n"
        f"Report={rep}\nReplaceReport=1\nShutdownTerminal=1\n")
    for pth in report_paths(rep):
        if os.path.exists(pth):
            try: os.remove(pth)
            except OSError: pass
    t0 = time.time(); print(f"  [{name}] {cfg['win'][0]}->{cfg['win'][1]} running...", flush=True)
    # 2026-10-08: the runner's connection drops ~0.3 s after "automatic testing started"; when that lands
    # inside the tick pre-download the tester cancels it ("no history data, stop testing", 0.000 s) and
    # writes an EMPTY report (3 of 4 cells, twice). Retry up to 3x on that exact tester-log signature.
    for attempt in range(6):
        try:
            subprocess.run([RUNNER_EXE, "/portable", f"/config:{ini}"], timeout=4 * 3600)
        except subprocess.TimeoutExpired:
            print(f"  [{name}] !! TIMEOUT"); return None
        tlog = sorted(glob.glob(os.path.join(RUNNER_DATA, "Tester", "logs", "*.log")), key=os.path.getmtime)
        tt = io.open(tlog[-1], encoding="utf-16", errors="replace").read() if tlog else ""
        tail = tt[tt.rfind('.ex5" X64'):]   # THIS launch only (the expert-load line opens every launch's block)
        if "no history data, stop testing" in tail and "Test passed" not in tail:
            print(f"  [{name}] tick pre-download cancelled (connection blip) -> retry {attempt+1}/6", flush=True)
            time.sleep(5); continue
        break
    term = sorted(glob.glob(os.path.join(RUNNER_DATA, "logs", "*.log")), key=os.path.getmtime)
    ttxt = io.open(term[-1], encoding="utf-16", errors="replace").read()[-20000:] if term else ""
    if "Invalid account" in ttxt or "authorized on" not in ttxt:
        print(f"  [{name}] !! VOID: runner login refused"); return None
    tl = sorted(glob.glob(os.path.join(RUNNER_DATA, "Tester", "logs", "*.log")), key=os.path.getmtime)
    tt = io.open(tl[-1], encoding="utf-16", errors="replace").read() if tl else ""
    syncs = re.findall(r"history synchronized from \S+ to (\d{4}\.\d\d\.\d\d)", tt)
    if syncs and syncs[-1] < cfg["win"][1][:10]:
        print(f"  [{name}] history synced to {syncs[-1]} (window ends {cfg['win'][1]})")
    for pth in report_paths(rep):
        if os.path.exists(pth) and os.path.getmtime(pth) >= t0 - 2:
            print(f"  [{name}] done in {time.time()-t0:.0f}s -> {pth}", flush=True); return pth
    print(f"  [{name}] !! no fresh report ({time.time()-t0:.0f}s)"); return None


def main():
    cells = sys.argv[1:] or ORDER
    hdr = (f"T2ONE BACKTEST  {EXPERT} {SYMBOL} {PERIOD} Model={MODEL} deposit={DEPOSIT}  {datetime.now():%Y-%m-%d %H:%M}\n"
           f"control t2_ctl must reproduce the demo: {ANCHOR['ladders']} ladders / {ANCHOR['wins']} wins / ${ANCHOR['net']}\n")
    print(hdr); blocks = [hdr]
    for c in cells:
        pth = run(c)
        blk = analyse(c, pth) if pth else f"[{c}] RUN FAILED"
        print(blk + "\n", flush=True); blocks.append(blk)
        io.open(OUT, "w", encoding="utf-8").write("\n\n".join(blocks) + "\n")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
