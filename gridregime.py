"""
gridregime.py -- Ch.17 STRUCTURAL-BREAK / VOL-REGIME analysis for the GridStat
momentum-grid (session 19o). The ONE under-exploited AFML lever for the momentum
book: a regime filter that cuts the deep-DD / blow-up baskets -> lower the grid's
~20% DD -> size up (more $) + qualify NEW candidate symbols.

WHY this is faithful despite the Python<->MT5 indicator parity wall
(see memory python-grid-sim-parity-wall): we do NOT simulate grid P&L. We use the
shadow DB's EXACT MT5-logged atr_at_entry to define the per-signal stop-distance,
derive each signal's MAX ADVERSE EXCURSION (MAE) from bars (a path-independent
extreme = robust), and ask which regime feature KNOWN AT ENTRY predicts the
deep-adverse signals -- the ones that stack recovery legs and float a basket to the
-20% floor. MT5 every-tick stays the P&L arbiter for any filter we design.

Tests BOTH failure modes the project has hit:
  (1) VOL-EXPANSION  -- ATR(D1,5)/ATR(D1,60) ratio (the fib C (a)+(c) detector).
  (2) DIRECTIONAL DRIFT -- the gold blind-spot (sustained one-way move at NORMAL
      vol that a vol-expansion detector misses; Session 19 early-May dip / fib C May).
      Proxies: |ret60|/ATR (drift), dist of price from D1-MA in ATR, AR(1) explosiveness.

Outcome var = MAE_r (max adverse excursion / stop-dist; more negative = worse =
deeper basket). Question: does a regime threshold separate the worst-MAE signals,
and how many GOOD signals does it also cut (the honest trade-off)?

Run: python gridregime.py [gold|silver|oil]   (default gold)
"""
import sys, datetime as dt
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

SYMMAP = {
    "gold":   ("GOLD",    "analysis_data/gridstat_setups_gold_20260609.csv"),
    "silver": ("SILVER",  "analysis_data/gridstat_setups_silver_research_20260609.csv"),
    "oil":    ("OILCash", "analysis_data/gridstat_setups_oil_g4_20260610.csv"),
}
MAE_WINDOWS = [288, 864]     # bars to scan adverse excursion (24h, 72h) -- grid baskets float for days
BARRIER_LOWER = 0.8          # stop-side ATR mult (BarrierATRLower default = BarrierATRMultiplier)


def wilder_atr_series(high, low, close, period):
    n = len(close); tr = np.empty(n); tr[0] = high[0]-low[0]
    pc = close[:-1]
    tr[1:] = np.maximum.reduce([high[1:]-low[1:], np.abs(high[1:]-pc), np.abs(low[1:]-pc)])
    atr = np.full(n, np.nan)
    if n > period:
        atr[period] = tr[1:period+1].mean()
        for i in range(period+1, n):
            atr[i] = (atr[i-1]*(period-1) + tr[i]) / period
    return atr


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "gold"
    sym, setups_csv = SYMMAP[which]
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); return
    mt5.symbol_select(sym, True)
    m5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60000)
    d1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 800)
    mt5.shutdown()
    if m5 is None or d1 is None:
        print("no bars"); return

    df = pd.DataFrame(m5); df["dt"] = pd.to_datetime(df["time"], unit="s")
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    idx_by_dt = {pd.Timestamp(df["dt"].iloc[i]).to_pydatetime(): i for i in range(len(df))}

    dd = pd.DataFrame(d1); dd["dt"] = pd.to_datetime(dd["time"], unit="s")
    dh = dd["high"].to_numpy(); dl = dd["low"].to_numpy(); dc = dd["close"].to_numpy()
    atr_d1_5  = wilder_atr_series(dh, dl, dc, 5)
    atr_d1_60 = wilder_atr_series(dh, dl, dc, 60)
    ema_d1_50 = pd.Series(dc).ewm(span=50, adjust=False).mean().to_numpy()
    dd_dates = dd["dt"].dt.date.to_numpy()

    s = pd.read_csv(setups_csv)
    s["et"] = pd.to_datetime(s["entry_time"], format="%Y.%m.%d %H:%M")
    print(f"{sym}: {len(df)} M5 bars ({df['dt'].iloc[0]}..{df['dt'].iloc[-1]}), "
          f"{len(s)} signals from {setups_csv}\n")

    rows = []
    for _, r in s.iterrows():
        et = r["et"].to_pydatetime()
        i = idx_by_dt.get(et)
        if i is None or i < 200 or i + max(MAE_WINDOWS) >= len(df): continue
        entry = float(r["entry_price"]); atr = float(r["atr_at_entry"])
        if atr <= 0: continue
        stop = atr * BARRIER_LOWER
        is_buy = (r["direction"] == "BUY")
        rec = {"et": et, "dir": r["direction"], "setup": r["setup_key"],
               "r": float(r["r_multiple"]), "mfe_r": float(r.get("mfe_r", np.nan)),
               "adx": float(r["adx"])}
        # MAE over each window (path-independent extreme from bars)
        for w in MAE_WINDOWS:
            seg_lo = l[i+1:i+1+w]; seg_hi = h[i+1:i+1+w]
            if is_buy: mae = (seg_lo.min() - entry) / stop      # buys hurt on lows
            else:      mae = (entry - seg_hi.max()) / stop      # sells hurt on highs
            rec[f"mae{w}"] = mae
        # --- regime features KNOWN AT ENTRY ---
        di = np.searchsorted(dd_dates, et.date()) - 1     # last closed D1 bar
        if di < 60: continue
        rec["vol_ratio"] = atr_d1_5[di] / atr_d1_60[di] if atr_d1_60[di] > 0 else np.nan  # (1) vol-expansion
        # (2) directional drift proxies (the gold blind-spot)
        ret60 = (c[i] - c[i-60])
        atr_m5 = np.mean(h[i-14:i] - l[i-14:i])
        rec["drift60"] = abs(ret60) / atr_m5 if atr_m5 > 0 else np.nan        # one-way move strength
        rec["distD1MA"] = abs(dc[di] - ema_d1_50[di]) / atr_d1_60[di] if atr_d1_60[di] > 0 else np.nan
        # AR(1) explosiveness (SADF-lite): regress price on its lag over 60 bars, coef>1 => explosive
        y = c[i-60:i+1]; x = c[i-61:i]
        if len(x) == len(y) and np.std(x) > 0:
            b = np.polyfit(x, y, 1)[0]
            rec["ar1"] = b
        else:
            rec["ar1"] = np.nan
        rows.append(rec)

    d = pd.DataFrame(rows).dropna(subset=["vol_ratio", "drift60", "distD1MA", "ar1"])
    if len(d) < 30:
        print("too few signals with features"); return
    print(f"Usable signals with regime features: {len(d)}\n")

    # === ANALYSIS: do regime features predict deep adverse MAE? ===
    feats = ["vol_ratio", "drift60", "distD1MA", "ar1", "adx"]
    for w in MAE_WINDOWS:
        mae = d[f"mae{w}"]
        # worst quintile = deepest adverse baskets
        thr = mae.quantile(0.20)   # most-negative 20%
        bad = mae <= thr
        print(f"=== MAE window {w} bars ===  median MAE_r={mae.median():+.2f}  "
              f"worst-20% threshold={thr:+.2f} (n_bad={bad.sum()})")
        print(f"  {'feature':<10} corr(feat,MAE)  mean@bad   mean@good   separation")
        for f in feats:
            fv = d[f]
            corr = np.corrcoef(fv, mae)[0, 1]   # negative corr w/ MAE => high feat predicts deep adverse
            mb, mg = fv[bad].mean(), fv[~bad].mean()
            sep = (mb - mg) / (fv.std() + 1e-9)
            flag = "  <== flags bad" if abs(sep) > 0.3 else ""
            print(f"  {f:<10} {corr:+.3f}          {mb:8.2f}   {mg:8.2f}   {sep:+.2f}{flag}")
        print()

    # === candidate FILTER trade-off: pick the best-separating feature, sweep a threshold ===
    w = MAE_WINDOWS[-1]
    mae = d[f"mae{w}"]
    # rank features by |separation| on worst-20%
    best = None
    thr_bad = mae.quantile(0.20)
    bad = mae <= thr_bad
    for f in feats:
        sep = abs((d[f][bad].mean() - d[f][~bad].mean()) / (d[f].std() + 1e-9))
        if best is None or sep > best[1]: best = (f, sep)
    f = best[0]
    print(f"=== FILTER TRADE-OFF on '{f}' (best separator, window {w}) ===")
    print(f"  'skip entries when {f} >= T' -- how many deep-adverse baskets vs good signals does each T cut?")
    print(f"  {'T(pctile)':<10}{'T':>8}  {'%bad cut':>9}  {'%good cut':>10}  {'kept n':>7}  {'kept medMAE':>12}")
    good = ~bad
    for q in [0.5, 0.6, 0.7, 0.8, 0.9]:
        T = d[f].quantile(q)
        cut = d[f] >= T
        pbad = (cut & bad).sum() / max(1, bad.sum()) * 100
        pgood = (cut & good).sum() / max(1, good.sum()) * 100
        kept = d[~cut]
        print(f"  {q:<10.0%}{T:>8.2f}  {pbad:>8.0f}%  {pgood:>9.0f}%  {len(kept):>7}  {kept[f'mae{w}'].median():>+12.2f}")
    print("\n  READ: a useful filter cuts a HIGH %bad while sparing %good (asymmetric).")
    print("  If %bad ~ %good at every T -> the regime feature does NOT separate -> no free DD reduction here.")
    print("  Winner (if any) -> design an MT5 default-OFF toggle (skip/size-down in hot regime) -> validate every-tick.")


if __name__ == "__main__":
    main()
