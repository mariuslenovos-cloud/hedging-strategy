"""
gridsim_parity.py -- STAGE 1a of the tick-faithful grid simulator.

Before simulating the grid P&L, we must prove the Python INDICATOR + SIGNAL layer
reproduces the MT5 EA exactly. The MT5 shadow DB (gridstat_setups_gold) conveniently
logs, at every signal bar: adx, atr_at_entry (=ATR(D1,14) shift1), ma_angle, wpr.

This script recomputes those four values in Python from M5 bars and compares them to
the logged values, row by row. If they match within tolerance, the indicator + signal
replication is faithful and we can trust the grid sim built on top of it.

Parity tests:
  A. INDICATOR match  -- recompute adx/atr/ma_angle/wpr at each logged signal time.
  B. SIGNAL match     -- does the Python Goldminer fire at the same bars / direction?

Run: python gridsim_parity.py
"""
import sys, datetime as dt
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

SYM = "GOLD"
SETUPS = "analysis_data/gridstat_setups_gold_20260609.csv"   # read-only snapshot
# EA params (gold locked config)
GRISK = 4
MA_PERIOD = 20
ADX_PERIOD = 14
ATR_D1_PERIOD = 14
ATR_CUR_PERIOD = 20
ATR_AVG_PERIOD = 100
RUNUP_BARS = 12
GM_PERIOD = 0          # 0 = auto = grisk*2+3 = 11
GM_GAPMULT = 2.0
GM_GAPMODE = 0
GM_FASTMULT = 4.6
GMSHIFT = 1


def ema(x, period):
    return pd.Series(x).ewm(span=period, adjust=False).mean().to_numpy()


def wilder_atr(high, low, close, period):
    """MT5 iATR uses Wilder/SMMA smoothing of True Range."""
    n = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.full(n, np.nan)
    if n > period:
        atr[period] = tr[1:period+1].mean()      # first ATR = simple mean of TR (MT5 convention)
        for i in range(period+1, n):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr


def wilder_adx(high, low, close, period):
    """MT5 iADX (Wilder). Returns the ADX main line."""
    n = len(close)
    pdm = np.zeros(n); ndm = np.zeros(n); tr = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i-1]; dn = low[i-1] - low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    # Wilder smoothing
    def smma(s):
        out = np.full(n, np.nan)
        if n > period:
            out[period] = s[1:period+1].sum()
            for i in range(period+1, n):
                out[i] = out[i-1] - out[i-1]/period + s[i]
        return out
    str_ = smma(tr); spdm = smma(pdm); sndm = smma(ndm)
    pdi = 100.0 * spdm / str_
    ndi = 100.0 * sndm / str_
    dx = 100.0 * np.abs(pdi - ndi) / (pdi + ndi)
    adx = np.full(n, np.nan)
    # ADX = Wilder smoothing of DX
    first = period + period  # need 'period' DX values
    if n > first:
        adx[first] = np.nanmean(dx[period+1:first+1])
        for i in range(first+1, n):
            adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period
    return adx


def wpr_value(high, low, close, j, period):
    """Goldminer oscillator at bar j (shift): 100 - |WPR(period)|."""
    hh = high[j:j+period].max()
    ll = low[j:j+period].min()
    cl = close[j]
    wpr = -100.0 * (hh - cl) / (hh - ll) if (hh - ll) != 0 else 0.0
    return 100.0 - abs(wpr)


def gm_value_at(high, low, close, opn, j, base_period):
    """Adaptive period value at bar j; returns (value, bigMove, periodUsed)."""
    avg_range = np.mean(np.abs(high[j:j+10] - low[j:j+10]))
    gap = False
    for k in range(j, j+9):
        if GM_GAPMODE == 1:
            jump = abs(close[k] - close[k+1])
        else:
            jump = abs(opn[k] - close[k+1])
        if jump >= GM_GAPMULT * avg_range:
            gap = True; break
    fast = False
    for k in range(j, j+6):
        if abs(close[k+3] - close[k]) >= GM_FASTMULT * avg_range:
            fast = True; break
    period = GM_PERIOD if GM_PERIOD > 0 else (GRISK*2 + 3)
    if gap: period = 3
    if fast: period = 4
    return wpr_value(high, low, close, j, period), (gap or fast), period


def goldminer_signal(high, low, close, opn, base_period):
    """Returns (dir, wpr, periodUsed, bigMove) evaluated at GMSHIFT using bars
    indexed so that index 0 = current forming bar (newest). We pass arrays where
    index increases going BACK in time (MT5 series convention: shift 0 newest)."""
    upper = GRISK + 67
    lower = 33 - GRISK
    LB = 40
    val = np.zeros(LB)
    bm0 = False; pu0 = 0
    for k in range(LB):
        v, bm, pu = gm_value_at(high, low, close, opn, GMSHIFT + k, base_period)
        val[k] = v
        if k == 0: bm0, pu0 = bm, pu
    direction = -1
    li = 1
    if val[0] > upper:
        while li < LB-1 and lower <= val[li] <= upper: li += 1
        if val[li] < lower: direction = 0   # BUY
    elif val[0] < lower:
        while li < LB-1 and lower <= val[li] <= upper: li += 1
        if val[li] > upper: direction = 1   # SELL
    return direction, val[0], pu0, bm0, li


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); return
    mt5.symbol_select(SYM, True)
    # pull M5 bars (enough to cover Dec2025-Jun2026 + warmup) -- newest-first via copy_rates_from_pos
    bars = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 40000)
    d1   = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 0, 800)
    mt5.shutdown()
    if bars is None:
        print("no M5 bars"); return
    df = pd.DataFrame(bars)
    df["dt"] = pd.to_datetime(df["time"], unit="s")
    print(f"M5 bars: {len(df)}  {df['dt'].iloc[0]} .. {df['dt'].iloc[-1]}")
    dd = pd.DataFrame(d1); dd["dt"] = pd.to_datetime(dd["time"], unit="s")
    print(f"D1 bars: {len(dd)}  {dd['dt'].iloc[0]} .. {dd['dt'].iloc[-1]}")

    # chronological arrays (index increases forward in time)
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy();  c = df["close"].to_numpy()
    t = df["dt"].to_numpy()

    ema20 = ema(c, MA_PERIOD)
    atr20 = wilder_atr(h, l, c, ATR_CUR_PERIOD)
    atr100 = wilder_atr(h, l, c, ATR_AVG_PERIOD)
    adx = wilder_adx(h, l, c, ADX_PERIOD)
    # D1 ATR
    dh = dd["high"].to_numpy(); dl = dd["low"].to_numpy(); dc = dd["close"].to_numpy()
    atr_d1 = wilder_atr(dh, dl, dc, ATR_D1_PERIOD)
    dd_dates = dd["dt"].dt.date.to_numpy()

    # index M5 bars by datetime for lookup
    idx_by_dt = {pd.Timestamp(t[i]).to_pydatetime(): i for i in range(len(t))}

    # load logged signals
    setups = pd.read_csv(SETUPS)
    setups["et"] = pd.to_datetime(setups["entry_time"], format="%Y.%m.%d %H:%M")

    point = 0.01  # gold 2-digit
    nmatch = 0; ntot = 0
    errs = {"adx": [], "atr": [], "ma_angle": [], "wpr": []}
    for _, row in setups.iterrows():
        et = row["et"].to_pydatetime()
        if et not in idx_by_dt: continue
        i = idx_by_dt[et]   # this is the bar whose TimeCurrent matched the signal (new bar i)
        if i < 200: continue
        ntot += 1
        # EA reads: adx = ReadBuf(hADX,0,0) at signal time. On a new bar i, shift0 = bar i.
        py_adx = adx[i]
        # atr_at_entry = ATR(D1,14) shift1 = last CLOSED daily bar before et
        dday = et.date()
        di = np.searchsorted(dd_dates, dday) - 1
        py_atr = atr_d1[di] if 0 <= di < len(atr_d1) else np.nan
        # ma_angle = arctan((ema[0]-ema[5])/(5*point))*180/pi, directional
        slope = (ema20[i] - ema20[i-5]) / (5*point)
        ang = np.degrees(np.arctan(slope))
        py_ang = ang if row["direction"] == "BUY" else -ang
        # wpr = GM value at shift1 (period 11 base)
        # build newest-first window arrays at bar i: index 0 = bar i, 1 = bar i-1...
        win = 60
        hh = h[i-win+1:i+1][::-1]; ll = l[i-win+1:i+1][::-1]
        cc = c[i-win+1:i+1][::-1]; oo = o[i-win+1:i+1][::-1]
        py_wpr = wpr_value(hh, ll, cc, GMSHIFT, GRISK*2+3)

        errs["adx"].append(abs(py_adx - row["adx"]))
        errs["atr"].append(abs(py_atr - row["atr_at_entry"]))
        errs["ma_angle"].append(abs(py_ang - row["ma_angle"]))
        errs["wpr"].append(abs(py_wpr - row["wpr"]))
        if ntot <= 12:
            print(f"{et}  adx {py_adx:6.1f}/{row['adx']:6.1f}  "
                  f"atr {py_atr:7.2f}/{row['atr_at_entry']:7.2f}  "
                  f"ang {py_ang:6.1f}/{row['ma_angle']:6.1f}  "
                  f"wpr {py_wpr:5.1f}/{row['wpr']:5.1f}")

    print(f"\nCompared {ntot} signals")
    for k, v in errs.items():
        if v:
            v = np.array(v)
            print(f"  {k:<9} median|err|={np.median(v):.3f}  mean={np.mean(v):.3f}  "
                  f"p90={np.percentile(v,90):.3f}  max={v.max():.3f}")


if __name__ == "__main__":
    main()
