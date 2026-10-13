#!/usr/bin/env python3
"""
mm_nano_capture.py -- TICK-LEVEL MEASUREMENT RIG for t2one (2026-10-13). PLACES NO ORDERS.

The bar-level record already answers the stop, the trail and the time stop (a bar's low IS the lowest tick).
What bars cannot see: (a) MICROSTRUCTURE at the fire -- tick rate, spread path, up/down-tick imbalance,
realised vol over the last 60 s; (b) INTRABAR ORDER -- does price retrace before it pays, how fast do winners
move in the first 30-60 s vs losers, what is the tick-exact first-touch of 0.5R vs the stop.

For every t2one fire since real ticks exist (Pepperstone, 2026-08-28), pull the ticks from 10 min before the
fire to the fire's resolution and write ONE ROW of features + tick-path outcomes. mm_nano_lab.py scores them.
Pre-committed gate for anything built on this: walk-forward AUC >= 0.60 on the SELL-fire outcome, OR a
tick-timed entry that beats the bar entry in BOTH halves on net $ AND worst-28-day. Below that, nothing ships.

usage:  python mm_nano_capture.py            (run on the PC with the MT5 terminal logged in; ~1 s per fire)
output: analysis_data\mm_nano_fires_<date>.csv
"""
import io, os, sys, time, datetime as dt
import numpy as np, pandas as pd
try:
    import MetaTrader5 as mt5
except Exception as e:
    print("MetaTrader5 import FAILED:", e); sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
FIRES = [os.path.join(HERE, "analysis_data", "mm_fires_t2one_bt10m_20261008.csv"),
         r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Files\mm_fires_XAUUSD_PERIOD_M1_t2one.csv"]
SYMBOL = "XAUUSD"; TICKS_FROM = dt.datetime(2026, 8, 28)
PRE_S = 600            # seconds of ticks before the fire for microstructure features
MAX_HOLD_S = 720 * 60  # the EA's own cap
TGT_R, STOP_R = 0.5, 1.0

def load_fires():
    fs = []
    for p in FIRES:
        if os.path.exists(p):
            d = pd.read_csv(p); fs.append(d)
    f = pd.concat(fs); f["t"] = pd.to_datetime(f.signal_time, format="mixed")
    f = f.drop_duplicates("t").sort_values("t")
    f = f[(f.t >= TICKS_FROM) & (f.tier >= 2)]
    return f.reset_index(drop=True)

def ticks(t0, t1):
    # 2026-10-13 FIX: a NAIVE datetime is read as LOCAL time (SAST, UTC+2) and shifted -> ticks came from 2 h BEFORE the fire
    # (first run: 42% tick-vs-bar agreement, SELL win 32%). Server-time wall clock must be passed as UTC-aware.
    t0 = t0.replace(tzinfo=dt.timezone.utc); t1 = t1.replace(tzinfo=dt.timezone.utc)
    r = mt5.copy_ticks_range(SYMBOL, t0, t1, mt5.COPY_TICKS_INFO)
    if r is None or len(r) == 0:
        return None
    d = pd.DataFrame(r); d["ts"] = pd.to_datetime(d.time_msc, unit="ms"); d["mid"] = (d.bid + d.ask) / 2
    return d[(d.bid > 0) & (d.ask > 0)].reset_index(drop=True)

def micro(pre, fire_t):
    """microstructure over the PRE_S seconds before the fire bar closes"""
    if pre is None or len(pre) < 20:
        return {}
    last60 = pre[pre.ts >= fire_t - pd.Timedelta(seconds=60)]
    last10 = pre[pre.ts >= fire_t - pd.Timedelta(seconds=10)]
    dmid = pre.mid.diff().dropna()
    up = (dmid > 0).sum(); dn = (dmid < 0).sum()
    spread = (pre.ask - pre.bid)
    rv60 = np.sqrt((last60.mid.diff().dropna() ** 2).sum()) if len(last60) > 2 else np.nan
    # run-length: longest same-direction tick run in the last 60 s
    s = np.sign(last60.mid.diff().dropna().values); run = best = 0; prev = 0
    for x in s:
        if x != 0 and x == prev: run += 1
        else: run = 1 if x != 0 else 0
        best = max(best, run); prev = x
    return dict(tick_rate_600=len(pre) / PRE_S, tick_rate_60=len(last60) / 60.0, tick_rate_10=len(last10) / 10.0,
                imb_600=(up - dn) / max(up + dn, 1), imb_60=((last60.mid.diff() > 0).sum() - (last60.mid.diff() < 0).sum()) / max(len(last60) - 1, 1),
                spread_mean=spread.mean(), spread_max=spread.max(), spread_last=spread.iloc[-1], spread_std=spread.std(),
                rv_60=rv60, rv_600=np.sqrt((dmid ** 2).sum()), max_run_60=best,
                drift_60=(last60.mid.iloc[-1] - last60.mid.iloc[0]) if len(last60) > 1 else np.nan,
                drift_600=pre.mid.iloc[-1] - pre.mid.iloc[0],
                range_600=pre.mid.max() - pre.mid.min())

def path(post, entry, R, d):
    """tick-exact outcome + early-path features. SELL: fills at bid, exits at ask. BUY: reverse."""
    if post is None or len(post) < 2:
        return {}
    px_fav = post.bid if d < 0 else post.ask        # price that must reach the target / stop for us
    fav = (entry - px_fav) / R if d < 0 else (px_fav - entry) / R
    adv = (entry - post.ask) / R if d < 0 else (post.bid - entry) / R
    t_rel = (post.ts - post.ts.iloc[0]).dt.total_seconds().values
    hit_t = np.where(fav.values >= TGT_R)[0]; hit_s = np.where(adv.values <= -STOP_R)[0]
    it = hit_t[0] if len(hit_t) else None; isx = hit_s[0] if len(hit_s) else None
    if it is not None and (isx is None or it < isx): out, r, k = "target", TGT_R, it
    elif isx is not None: out, r, k = "stop", -STOP_R, isx
    else: out, r, k = "timeout", float(fav.iloc[-1]), len(post) - 1
    def seg(sec):
        m = t_rel <= sec
        return dict(**{f"mfe_{sec}s": float(fav[m].max()) if m.any() else np.nan, f"mae_{sec}s": float(adv[m].min()) if m.any() else np.nan,
                       f"close_{sec}s": float(fav[m].iloc[-1]) if m.any() else np.nan, f"ticks_{sec}s": int(m.sum())})
    o = dict(tick_outcome=out, tick_r=r, secs_to_resolve=float(t_rel[k]), ticks_to_resolve=int(k),
             mae_before_target=float(adv.iloc[:it + 1].min()) if it is not None else np.nan,
             mfe_before_stop=float(fav.iloc[:isx + 1].max()) if isx is not None else np.nan,
             first_adverse_s=float(t_rel[np.where(adv.values < -0.1)[0][0]]) if (adv.values < -0.1).any() else np.nan,
             first_fav_s=float(t_rel[np.where(fav.values > 0.1)[0][0]]) if (fav.values > 0.1).any() else np.nan,
             entry_spread=float(post.ask.iloc[0] - post.bid.iloc[0]))
    for sec in (10, 30, 60, 120, 300): o.update(seg(sec))
    return o

def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    f = load_fires(); print(f"{len(f)} fires since {TICKS_FROM.date()}  ({(f.dir=='SELL').sum()} SELL)")
    rows = []; t0 = time.time(); paths = {}
    for i, r in f.iterrows():
        fire_close = r.t + pd.Timedelta(minutes=1)          # the fire is the CLOSE of the signal bar
        pre = ticks((fire_close - pd.Timedelta(seconds=PRE_S)).to_pydatetime(), fire_close.to_pydatetime())
        post = ticks(fire_close.to_pydatetime(), (fire_close + pd.Timedelta(seconds=MAX_HOLD_S)).to_pydatetime())
        d = -1 if r.dir == "SELL" else 1
        row = dict(signal_time=r.signal_time, dir=r.dir, tier=r.tier, entry=r.entry, sl=r.sl, R=r.risk_price, riskUSD=3 * r.risk_price,
                   bar_outcome=r.exit_tp1, bar_r=r["r_tp1_0.5R"], adx=r.adx, eff=r.eff_ratio, mtf=r.mtf_agree, vol_ratio=r.vol_ratio,
                   ema_dist_atr=r.ema_dist_atr, spread_pts=r.spread_pts, atr=r.atr, hour=r.t.hour)
        row.update(micro(pre, fire_close)); row.update(path(post, r.entry, r.risk_price, d))
        rows.append(row)
        if post is not None and len(post) > 1:                      # raw path for tick-level simulation in the lab
            k = min(len(post) - 1, int(row.get('ticks_to_resolve', len(post) - 1)) + 600)
            paths[f'f{i}'] = np.column_stack([(post.ts.iloc[:k+1] - fire_close).dt.total_seconds().values, post.bid.values[:k+1], post.ask.values[:k+1]]).astype(np.float64)
        if (i + 1) % 25 == 0: print(f"  {i+1}/{len(f)}  {time.time()-t0:.0f}s")
    out = pd.DataFrame(rows); fn = os.path.join(HERE, "analysis_data", f"mm_nano_fires_{dt.date.today():%Y%m%d}.csv")
    out.to_csv(fn, index=False)
    np.savez_compressed(fn.replace('mm_nano_fires_', 'mm_nano_ticks_').replace('.csv', '.npz'), **paths)
    ok = out.tick_outcome.notna().sum(); agree = (out.tick_outcome == out.bar_outcome).mean()
    print(f"written {fn}: {len(out)} rows, {ok} with ticks, tick-vs-bar outcome agreement {agree*100:.1f}%")
    mt5.shutdown()

if __name__ == "__main__":
    main()
