#!/usr/bin/env python3
"""
growth_mc.py — months-to-target Monte Carlo for a compounding account.

Calibrated from the GridStat PT50 backtest (Dec-01 -> Sep-05, every tick):
  ~$3,000 -> ~$8,950 in 9 months  =>  geometric monthly return ~ 12.9%
  eqDD 12%                         =>  monthly sd ~ 8%
Tail episode = the July pin (-34% on the PT35 path): PT50 escaped it by a
balance-path artefact, so it is modelled as a real risk, not a zero.

Scenarios scale the backtest edge down (100%, 50%, 25%) because nine months
is one regime. Lots are assumed to scale with balance above a floor where
0.01-lot granularity makes returns linear rather than proportional.

Usage:  python growth_mc.py --balance 2390 --targets 10000 20000
"""
import argparse
import numpy as np

def simulate(balance, target, mu, sd, p_tail, tail_lo, tail_hi, floor,
             months=60, n=20000, seed=1):
    rng = np.random.default_rng(seed)
    bal = np.full(n, float(balance))
    hit = np.full(n, -1)
    halved = np.zeros(n, dtype=bool)
    peak = bal.copy()
    for m in range(1, months + 1):
        r = rng.normal(mu, sd, n)
        # below the floor, 0.01-lot granularity: dollar P&L stops scaling down
        eff = np.where(bal < floor, r * floor / np.maximum(bal, 1), r)
        tail = rng.random(n) < p_tail
        eff = np.where(tail, eff - rng.uniform(tail_lo, tail_hi, n), eff)
        bal = bal * (1 + eff)
        peak = np.maximum(peak, bal)
        halved |= bal < 0.5 * balance
        newly = (hit < 0) & (bal >= target)
        hit[newly] = m
    reached = hit > 0
    q = np.percentile(hit[reached], [25, 50, 75]) if reached.any() else [np.nan]*3
    return dict(p_hit=reached.mean(), p25=q[0], p50=q[1], p75=q[2],
                p_halved_first=(halved & ~reached).mean() + (halved & reached).mean()*0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, required=True)
    ap.add_argument("--targets", type=float, nargs="+", default=[10000, 20000])
    ap.add_argument("--mu", type=float, default=0.129, help="backtest geometric monthly return")
    ap.add_argument("--sd", type=float, default=0.08)
    ap.add_argument("--p-tail", type=float, default=1/12, help="pin-episode prob per month")
    ap.add_argument("--tail", type=float, nargs=2, default=[0.20, 0.35])
    ap.add_argument("--floor", type=float, default=2500, help="balance below which lots can't scale down")
    ap.add_argument("--months", type=int, default=60)
    a = ap.parse_args()

    print(f"start ${a.balance:,.0f}   tail: {a.p_tail*12:.1f}/yr of -{a.tail[0]:.0%}..-{a.tail[1]:.0%}   horizon {a.months} mo\n")
    print(f"{'edge vs backtest':<18}{'target':>9}{'P(hit)':>9}{'p25':>7}{'median':>8}{'p75':>7}{'P(halve, never hit)':>22}")
    for label, k in (("100%", 1.0), ("50%", 0.5), ("25%", 0.25)):
        for t in a.targets:
            s = simulate(a.balance, t, a.mu*k, a.sd, a.p_tail, *a.tail, a.floor, a.months)
            print(f"{label:<18}{t:>9,.0f}{s['p_hit']:>9.0%}{s['p25']:>7.0f}{s['p50']:>8.0f}{s['p75']:>7.0f}{s['p_halved_first']:>22.0%}")
        print()

if __name__ == "__main__":
    main()
