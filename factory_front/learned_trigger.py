"""learned_trigger.py -- UPSTREAM QUESTION (2026-10-13, user): label EVERY gold M1 bar, not just the 0.5% where Million Moves fired,
and ask a model to find the entry itself.

PRE-REGISTERED (written before the data was read; see CLAUDE.md 2026-10-13 (2)):
  LABEL   at each M1 close, LONG (enter ask, exit bid) and SHORT (enter bid, exit ask): does +0.5R come before -1R?
          R = 2.33 x Wilder ATR(14) on the last COMPLETED M5 bar (t2one geometry); per-bar real spread; eligible only if
          3 x R <= $40 (the 0.01x3 cap); 720-bar time limit (timeout = mark-to-market in R); both touched in one bar = STOP.
  SPLIT   train on the first half, test on the second, 720-bar purge at the boundary; then SWAP.
  PASS    held-out precision >= 72% at >= 1 trade/day AND positive net $ after spread with trades taken ONE AT A TIME,
          in BOTH split directions. Break-even at 0.5R:1R = 66.7%. Below 67% = no learnable edge at this scale.
usage: python factory_front/learned_trigger.py [analysis_data/xauusd_m1_15mo.csv]"""
import os, sys, time
import numpy as np, pandas as pd
from numba import njit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "analysis_data", "xauusd_m1_15mo.csv")
PT, K_STOP, TGT, HOR, CAP = 0.01, 2.33, 0.5, 720, 40.0

d = pd.read_csv(FN, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
o, h, l, c = (d[x].values.astype(np.float64) for x in ("open", "high", "low", "close"))
sp = d.spread.values.astype(np.float64) * PT
t = d.time.values
n = len(d)
print(f"{n} M1 bars {d.time.iloc[0]} -> {d.time.iloc[-1]}")

# ---- R from the last COMPLETED M5 bar (no look-ahead) ----
m5 = (d.set_index("time")[["open", "high", "low", "close"]]
      .resample("5min", label="left", closed="left")
      .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
pc = m5.close.shift(1)
tr = np.maximum(m5.high - m5.low, np.maximum((m5.high - pc).abs(), (m5.low - pc).abs()))
atr5 = tr.ewm(alpha=1 / 14, adjust=False).mean()
atr5_done = atr5.shift(1)          # the M5 bar that contains bar i is not complete yet
R = K_STOP * atr5_done.reindex(d.time.dt.floor("5min")).values
elig = np.isfinite(R) & (R > 0) & (3 * R <= CAP)


@njit(cache=True)
def label(h, l, c, sp, R, elig, hor, tgt):
    n = len(c)
    yl = np.full(n, -1, np.int8); ys = np.full(n, -1, np.int8)
    rl = np.full(n, np.nan); rs = np.full(n, np.nan); kl = np.zeros(n, np.int32); ks = np.zeros(n, np.int32)
    for i in range(n - 1):
        if not elig[i]:
            continue
        r = R[i]
        # LONG: enter at ask = close + spread, exits at bid
        e = c[i] + sp[i]; tp = e + tgt * r; sl = e - r; res = 9; jend = min(n - 1, i + hor)
        for j in range(i + 1, jend + 1):
            if l[j] <= sl:
                res = 0; jend = j; break
            if h[j] >= tp:
                res = 1; jend = j; break
        kl[i] = jend - i
        if res == 1:
            yl[i] = 1; rl[i] = tgt
        elif res == 0:
            yl[i] = 0; rl[i] = -1.0
        else:
            yl[i] = 0; rl[i] = (c[jend] - e) / r
        # SHORT: enter at bid = close, exits at ask = bid + that bar's spread
        e = c[i]; tp = e - tgt * r; sl = e + r; res = 9; jend = min(n - 1, i + hor)
        for j in range(i + 1, jend + 1):
            if h[j] + sp[j] >= sl:
                res = 0; jend = j; break
            if l[j] + sp[j] <= tp:
                res = 1; jend = j; break
        ks[i] = jend - i
        if res == 1:
            ys[i] = 1; rs[i] = tgt
        elif res == 0:
            ys[i] = 0; rs[i] = -1.0
        else:
            ys[i] = 0; rs[i] = (e - (c[jend] + sp[jend])) / r
    return yl, ys, rl, rs, kl, ks


t0 = time.time()
yl, ys, rl, rs, kl, ks = label(h, l, c, sp, np.nan_to_num(R, nan=0.0), elig, HOR, TGT)
print(f"labelled in {time.time() - t0:.0f}s; eligible bars {elig.sum()} ({elig.mean()*100:.0f}%)")

# ---- features: past-only at the close of bar i ----
A = R / K_STOP
F = pd.DataFrame(index=d.index)
for k in (1, 3, 5, 15, 30, 60, 240, 720):
    F[f"ret{k}"] = (c - np.r_[np.full(k, np.nan), c[:-k]]) / A
for N in (60, 240, 1440):
    lo = pd.Series(l).rolling(N).min().values; hi = pd.Series(h).rolling(N).max().values
    rng = hi - lo
    F[f"pos{N}"] = (c - lo) / np.where(rng > 0, rng, np.nan)
for N in (50, 200, 800):
    F[f"ema{N}"] = (c - pd.Series(c).ewm(span=N, adjust=False).mean().values) / A
dl = pd.Series(c).diff()
up = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
F["rsi14"] = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
hh = pd.Series(h).rolling(17).max(); ll = pd.Series(l).rolling(17).min()
F["wpr17"] = ((pd.Series(c) - ll) / (hh - ll).replace(0, np.nan)).values
tr1 = np.maximum(h - l, np.abs(h - np.r_[c[0], c[:-1]]))
atr1 = pd.Series(tr1).ewm(alpha=1 / 14, adjust=False).mean()
F["volr"] = (atr1 / atr1.rolling(240).mean()).values
F["atr5_rel"] = (pd.Series(A) / pd.Series(A).rolling(1440 * 5).mean()).values
F["spread"] = d.spread.values
F["body"] = (c - o) / np.where(h - l > 0, h - l, np.nan)
F["tvr"] = (d.tick_volume / d.tick_volume.rolling(60).mean()).values
F["hour"] = d.time.dt.hour.values; F["dow"] = d.time.dt.dayofweek.values
dc = d.set_index("time").close.resample("1D").last().dropna()
de = dc.ewm(span=50, adjust=False).mean()
day = d.time.dt.floor("1D")
F["d1_trend"] = ((dc.shift(1) - de.shift(1)) / de.shift(1) * 100).reindex(day).values
F["d1_ret5"] = (dc.pct_change(5).shift(1) * 100).reindex(day).values
feats = list(F.columns)


def run(train_first):
    half = n // 2
    tr_idx = np.arange(0, half - HOR) if train_first else np.arange(half + HOR, n - HOR)
    te_idx = np.arange(half, n - HOR) if train_first else np.arange(0, half - HOR)
    out = {}
    for side, y, rr, kk in (("LONG", yl, rl, kl), ("SHORT", ys, rs, ks)):
        m = y >= 0
        tri = tr_idx[m[tr_idx]][::3]          # thin overlapping labels (adjacent bars share most of the path)
        tei = te_idx[m[te_idx]]
        clf = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=500, l2_regularization=1.0)
        clf.fit(F.iloc[tri][feats], y[tri])
        p = clf.predict_proba(F.iloc[tei][feats])[:, 1]
        out[side] = pd.DataFrame(dict(i=tei, p=p, y=y[tei], r=rr[tei], R=R[tei], k=kk[tei], t=t[tei]))
        out[side + "_auc"] = roc_auc_score(y[tei], p)
        out[side + "_base"] = y[tei].mean(); out[side + "_trainbase"] = y[tri].mean()
    return out


def sequential(L, S, thr):
    """one position at a time, either side (higher prob wins a tie), held to its own resolution bar"""
    sig = pd.concat([L.assign(side=1), S.assign(side=-1)])
    sig = sig[sig.p >= thr].sort_values(["i", "p"], ascending=[True, False]).drop_duplicates("i")
    busy = -1; wins = 0; usd = []; days = set(); eq = []
    for row in sig.itertuples():
        if row.i <= busy:
            continue
        wins += row.y; usd.append(row.r * row.R * 3); busy = row.i + max(int(row.k), 1); days.add(pd.Timestamp(row.t).date())
    usd = np.array(usd); cum = np.cumsum(usd) if len(usd) else np.array([0.0])
    dd = float((cum - np.maximum.accumulate(cum)).min()) if len(usd) else 0.0
    return len(usd), wins, float(usd.sum()), dd


report = []
for name, first in (("SPLIT A: train first half -> test second half", True), ("SPLIT B: train second half -> test first half", False)):
    o_ = run(first); L, S = o_["LONG"], o_["SHORT"]
    tdays = len(pd.unique(pd.to_datetime(L.t).dt.date))
    lines = [f"\n== {name} ==  test window {pd.Timestamp(L.t.min()).date()} -> {pd.Timestamp(L.t.max()).date()}, {tdays} days"]
    for side in ("LONG", "SHORT"):
        lines.append(f"  {side}: eligible test bars {len(o_[side])}, base win {o_[side+'_base']*100:.1f}% "
                     f"(train base {o_[side+'_trainbase']*100:.1f}%), held-out AUC {o_[side+'_auc']:.3f}")
    lines.append(f"  {'per day':>8}{'thr':>7}{'precision':>10}{'n bars':>8} | {'seq trades':>10}{'seq win%':>9}{'seq net$':>10}{'seq maxDD$':>11}")
    both = pd.concat([L, S])
    pv = np.sort(both.p.values)
    for rate in (1, 2, 5, 10, 20):
        k = rate * tdays
        thr = pv[-k] if k < len(pv) else pv[0]
        sel = both[both.p >= thr]
        st, sw, sn, sdd = sequential(L, S, thr)
        lines.append(f"  {rate:>8}{thr:>7.3f}{sel.y.mean()*100:>9.1f}%{len(sel):>8} | {st:>10}{(sw/st*100 if st else 0):>8.1f}%{sn:>10,.0f}{sdd:>11,.0f}")
    print("\n".join(lines), flush=True); report += lines

open(os.path.join(HERE, "analysis_data", "learned_trigger_20261013.txt"), "w", encoding="utf-8").write("\n".join(report) + "\n")
