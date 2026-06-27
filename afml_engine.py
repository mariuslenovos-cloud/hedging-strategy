"""
afml_engine.py -- PATH A: the cross-sectional AFML meta-labeling engine (the "ideal EA" core).

Pulls REAL price bars from the live MT5 terminal and builds the canonical
López de Prado stack the RED gate told us we were missing -- proper FEATURES +
the right LABEL:

  Ch.2  CUSUM event sampling      -> evaluate meaningful moves, not every bar
  Ch.5  Fractional differentiation -> stationary price series that KEEPS memory
  Ch.17 Structural-break / vol-regime features
  Ch.3  vol-scaled TRIPLE-BARRIER labels (the tradeable outcome)
  Ch.4  uniqueness sample weights
  Ch.7  purged K-fold CV (symbol-aware)
  Ch.14 Deflated / Probabilistic Sharpe

THE TEST: does a uniqueness-weighted RF on REAL features, trained on the RIGHT
triple-barrier label, pooled across symbols, BEAT the raw primary signal OOS?
(Primary = sign of frac-diff momentum at each CUSUM event. Meta = RF P(win).)
Green (PSR>95% AND beats primary) -> build ONNX/EA. Red -> the edge isn't in
selection; the fingerprint/grid is already near-optimal.

Usage:  python afml_engine.py            # default symbol set, ~60k M5 bars each
"""
import math, sys
import numpy as np
import pandas as pd
from collections import defaultdict
from scipy.stats import norm, skew, kurtosis
from sklearn.ensemble import RandomForestClassifier
import MetaTrader5 as mt5

try: sys.stdout.reconfigure(line_buffering=True)   # flush progress live
except Exception: pass

SYMBOLS = ["EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "NZDUSD",
           "USDCAD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY"]   # FX-only (reversion engine) = VALIDATED GREEN config
NBARS   = 100000         # M5 bars per symbol (max ~1yr) for a bigger/stabler sample
D_FRAC  = 0.4            # fractional differentiation order (memory-preserving, ~stationary)
CUSUM_K = 3.0           # event threshold = K x rolling vol (selective -> meaningful events)
MOM_LB  = 12            # primary side = sign of frac-diff momentum over this lookback
PT_MULT, SL_MULT = 4.0, 4.0   # triple-barrier in units of rolling BAR vol (>= a few x spread = tradeable)
MAX_H   = 96           # vertical barrier (M5 bars; 96 = 8h, room for the wider barrier)
EMBARGO = 0.01
N_TRIALS = 20          # ~configs tried (momentum+fade + param/feature choices) -> Deflated Sharpe
COST_R  = 0.15         # round-trip cost as a fraction of 1R (spread/slippage haircut)


def get_bars(sym, n):
    if not mt5.symbol_select(sym, True):
        return None
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n)
    return r if (r is not None and len(r) > 5000) else None


def fd_weights(d, thres=1e-4, kmax=2000):
    w = [1.0]; k = 1
    while k < kmax:
        wk = -w[-1] * (d - k + 1) / k
        if abs(wk) < thres: break
        w.append(wk); k += 1
    return np.array(w[::-1])          # oldest-first


def frac_diff(series, d):
    w = fd_weights(d); width = len(w)
    out = np.full(len(series), np.nan)
    if len(series) >= width:
        out[width - 1:] = np.correlate(series, w, mode="valid")
    return out


def ewma_vol(ret, span=100):
    return pd.Series(ret).ewm(span=span).std().fillna(0.0).to_numpy()


def cusum_events(logp, vol, k):
    ev = []; sp = sn = 0.0
    d = np.diff(logp)
    for i in range(len(d)):
        h = k * vol[i] if vol[i] > 0 else 1e9
        sp = max(0.0, sp + d[i]); sn = min(0.0, sn + d[i])
        if sp >= h: sp = 0.0; ev.append(i + 1)
        elif sn <= -h: sn = 0.0; ev.append(i + 1)
    return ev


def build_symbol(sym, rates, point):
    close = rates["close"].astype(float)
    high = rates["high"].astype(float); low = rates["low"].astype(float)
    tvol = rates["tick_volume"].astype(float)
    spread = rates["spread"].astype(float)   # REAL per-bar spread in POINTS (spikes at rollover)
    t = rates["time"]
    logp = np.log(close)
    ret = np.diff(logp, prepend=logp[0])
    vol = ewma_vol(ret, 100)
    fd = frac_diff(logp, D_FRAC)
    ev = cusum_events(logp, vol, CUSUM_K)

    rows = []
    n = len(close)
    for e in ev:
        if e < max(MOM_LB, 60) or e + MAX_H >= n or np.isnan(fd[e]): continue
        v = vol[e]
        if v <= 0: continue
        side = -1 if (fd[e] - fd[e - MOM_LB]) > 0 else 1   # FADE the move (FX CUSUM breaches mean-revert) = GREEN config
        # vol-scaled triple barrier (vectorized scan; tie within a bar -> SL, conservative)
        entry = close[e]; pt = PT_MULT * v; sl = SL_MULT * v
        j0 = e + 1; j1 = e + 1 + MAX_H
        up = (high[j0:j1] - entry) / entry; dn = (low[j0:j1] - entry) / entry
        fav = np.maximum(side * up, side * dn); adv = np.minimum(side * up, side * dn)
        hp = np.where(fav >= pt)[0]; hs = np.where(adv <= -sl)[0]
        ip = hp[0] if len(hp) else 10**9
        is_ = hs[0] if len(hs) else 10**9
        if ip == 10**9 and is_ == 10**9:
            hit = j1 - 1; r = (side * (close[hit] - entry) / entry) / sl
        elif ip < is_:
            hit = j0 + ip; r = pt / sl
        else:
            hit = j0 + is_; r = -1.0
        # REAL spread cost in R units: round-trip = half-spread at entry + half-spread at exit,
        # divided by the SL distance (=1R in price). spread is in POINTS -> x point = price.
        sl_price = sl * entry
        cost_R = (0.5 * (spread[e] + spread[hit]) * point) / sl_price if sl_price > 0 else 9.9
        entry_cost_R = (spread[e] * point) / sl_price if sl_price > 0 else 9.9   # entry-spread only (for the spread gate)
        rows.append({
            "symbol": sym, "t0": int(t[e]), "t1": int(t[hit]),
            "e": int(e), "hit": int(hit),     # per-symbol bar indices (fast uniqueness/purge)
            "y": 1 if r > 0 else 0, "r": r, "side": float(side),
            "costR": float(cost_R), "entry_costR": float(entry_cost_R),   # REAL-spread cost (Ch.: live execution)
            # ---- features (real, AFML) ----
            "fd": fd[e], "mom": fd[e] - fd[e - MOM_LB],
            "vol": v, "volreg": v / (np.mean(vol[max(0, e - 288):e]) + 1e-12),
            "ret20": (logp[e] - logp[e - 20]), "ret60": (logp[e] - logp[e - 60]),
            "rng": (np.mean(high[e - 14:e] - low[e - 14:e]) / entry),
            "tvol_z": (tvol[e] - np.mean(tvol[e - 100:e])) / (np.std(tvol[e - 100:e]) + 1e-9),
            "hour": float((t[e] // 3600) % 24),
        })
    return rows


FEATS = ["side", "fd", "mom", "vol", "volreg", "ret20", "ret60", "rng", "tvol_z", "hour"]


def uniqueness(rows):
    """Avg uniqueness (AFML Ch.4) via per-symbol bar-index concurrency (O(span))."""
    w = [1.0] * len(rows)
    by = defaultdict(list)
    for i, r in enumerate(rows): by[r["symbol"]].append(i)
    for idxs in by.values():
        mx = max(rows[i]["hit"] for i in idxs) + 2
        diff = np.zeros(mx + 1)
        for i in idxs:
            diff[rows[i]["e"]] += 1; diff[rows[i]["hit"] + 1] -= 1
        conc = np.cumsum(diff)
        inv = np.where(conc > 0, 1.0 / np.maximum(conc, 1e-9), 0.0)
        for i in idxs:
            seg = inv[rows[i]["e"]: rows[i]["hit"] + 1]
            w[i] = float(seg.mean()) if seg.size else 1.0
    return w


def purge(train, test, rows, emb_bars):
    """Symbol-aware purge+embargo via per-symbol bar-index coverage (O(span))."""
    test_by = defaultdict(list)
    for j in test: test_by[rows[j]["symbol"]].append(j)
    cov = {}
    for s, js in test_by.items():
        mx = max(rows[j]["hit"] for j in js) + emb_bars + 2
        c = np.zeros(mx + 2)
        for j in js:
            c[rows[j]["e"]] += 1; c[rows[j]["hit"] + emb_bars + 1] -= 1   # span + embargo tail
        cov[s] = np.cumsum(c)
    kept = []
    for i in train:
        cs = cov.get(rows[i]["symbol"])
        if cs is None: kept.append(i); continue
        a = rows[i]["e"]; b = min(rows[i]["hit"], len(cs) - 1)
        if a >= len(cs) or cs[a:b + 1].max() <= 0: kept.append(i)
    return kept


def Xof(rows, idx):
    return np.array([[rows[i][f] for f in FEATS] for i in idx], dtype=float)


def psr(sr, n, g3, g4, s0=0.0):
    d = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr * sr))
    return norm.cdf((sr - s0) * math.sqrt(n - 1) / d)


def deflated_sr(sr, n, g3, g4, fold_sharpes, n_trials):
    """DSR (Ch.14): PSR vs the expected MAX Sharpe of n_trials noise strategies."""
    var = np.var(fold_sharpes, ddof=1) if len(fold_sharpes) > 1 else 0.0
    if var <= 0 or n_trials < 2:
        return psr(sr, n, g3, g4, 0.0), 0.0
    e = 0.5772156649
    z1 = norm.ppf(1 - 1.0 / n_trials); z2 = norm.ppf(1 - 1.0 / (n_trials * math.e))
    s0 = math.sqrt(var) * ((1 - e) * z1 + e * z2)
    return psr(sr, n, g3, g4, s0), s0


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); return
    rows = []
    print("Pulling bars + building events:")
    for s in SYMBOLS:
        r = get_bars(s, NBARS)
        if r is None: print(f"  {s:<10} (no data, skip)"); continue
        info = mt5.symbol_info(s)
        pt = info.point if info else 1e-5
        sr = build_symbol(s, r, pt)
        rows += sr
        print(f"  {s:<10} {len(r)} bars -> {len(sr)} events")
    mt5.shutdown()
    if len(rows) < 500:
        print("too few events"); return
    rows.sort(key=lambda r: r["t0"])
    n = len(rows)
    emb = MAX_H          # embargo = one label horizon (bars)
    uw = np.array(uniqueness(rows))
    base = sum(r["y"] for r in rows) / n
    print(f"\nPooled {n} events | {len(set(r['symbol'] for r in rows))} symbols | "
          f"primary base win {base*100:.1f}% | mean R {np.mean([r['r'] for r in rows]):+.3f}")

    rf0 = RandomForestClassifier(n_estimators=250, max_depth=5, min_samples_leaf=50,
                                 class_weight="balanced", random_state=7, n_jobs=-1)
    rf0.fit(Xof(rows, range(n)), [r["y"] for r in rows], sample_weight=uw)
    print("Feature importance (full-data, in-sample):")
    for f, v in sorted(zip(FEATS, rf0.feature_importances_), key=lambda x: -x[1]):
        print(f"   {f:<8}{v:.3f}  " + "#" * int(round(v * 50)))

    N = 6
    bnd = [round(i * n / N) for i in range(N + 1)]
    blk = [list(range(bnd[b], bnd[b + 1])) for b in range(N)]
    oosP = []                 # primary take-all R
    oosM = []                 # row INDICES of ML-gated trades (carry real costR/spread/hour)
    foldM = []                # per-fold ML mean NET R (real spread)
    fold_sh = []              # per-fold ML Sharpe (for DSR trial dispersion)
    for b in range(N):
        te = blk[b]; tr = purge([i for bb in range(N) if bb != b for i in blk[bb]], te, rows, emb)
        if len(tr) < 200: continue
        m = RandomForestClassifier(n_estimators=250, max_depth=5, min_samples_leaf=50,
                                   class_weight="balanced", random_state=7, n_jobs=-1)
        m.fit(Xof(rows, tr), [rows[i]["y"] for i in tr], sample_weight=uw[tr])
        p = m.predict_proba(Xof(rows, te))[:, 1]
        fr = []
        for k, i in enumerate(te):
            oosP.append(rows[i]["r"])
            if p[k] >= 0.55:
                oosM.append(i); fr.append(rows[i]["r"] - rows[i]["costR"])   # NET of REAL spread
        if len(fr) >= 3:
            foldM.append(np.mean(fr))
            fold_sh.append(np.mean(fr) / np.std(fr) if np.std(fr) > 0 else 0.0)

    pA = np.array(oosP) if oosP else np.array([0.0])
    rM = np.array([rows[i]["r"] for i in oosM]) if oosM else np.array([0.0])
    rMc = np.array([rows[i]["r"] - rows[i]["costR"] for i in oosM]) if oosM else np.array([0.0])  # REAL spread
    avg_spread_R = np.mean([rows[i]["costR"] for i in oosM]) if oosM else 0.0
    print(f"\nPurged K-fold OOS (meta-labeling; barrier {PT_MULT:.0f}xbar-vol; REAL per-event spread):")
    print(f"   {'primary (take all)':<22} trades={len(oosP):<6} avgR={pA.mean():+.3f} totR={pA.sum():+.1f}")
    print(f"   {'ML gate (gross/mid)':<22} trades={len(rM):<6} avgR={rM.mean():+.3f} totR={rM.sum():+.1f} win={sum(1 for x in rM if x>0)/len(rM)*100:.0f}%")
    print(f"   {'ML gate (NET real spr)':<22} trades={len(rMc):<6} avgR={rMc.mean():+.3f} totR={rMc.sum():+.1f}  (avg spread cost {avg_spread_R:.3f}R/trade)")

    # per-symbol breadth (NET of real spread)
    bysym = defaultdict(list)
    for i in oosM: bysym[rows[i]["symbol"]].append(rows[i]["r"] - rows[i]["costR"])
    print("   per-symbol (NET real spr): " + "  ".join(
        f"{s}={np.mean(v):+.2f}R/{len(v)}" for s, v in sorted(bysym.items(), key=lambda x: -np.mean(x[1]))))

    # per-fold consistency (NET real spread)
    posf = sum(1 for x in foldM if x > 0)
    print(f"   per-fold NET positive: {posf}/{len(foldM)} folds")

    # significance: PSR + Deflated SR on the NET series
    if len(rMc) > 5 and rMc.std() > 0:
        sr = rMc.mean() / rMc.std()
        g3, g4 = float(skew(rMc)), float(kurtosis(rMc, fisher=False))
        ps = psr(sr, len(rMc), g3, g4)
        dsr, s0 = deflated_sr(sr, len(rMc), g3, g4, fold_sh, N_TRIALS)
        print(f"   NET per-trade Sharpe={sr:+.3f}  PSR(>0)={ps*100:.0f}%  "
              f"DeflatedSR(N={N_TRIALS},SR*={s0:.3f})={dsr*100:.0f}%")
    else:
        dsr = 0.0; posf = 0

    print("\nVERDICT (net of cost, deflated):")
    broad = sum(1 for v in bysym.values() if np.mean(v) > 0) >= max(2, len(bysym) // 2)
    if rMc.mean() > 0.03 and dsr >= 0.95 and posf >= len(foldM) - 1 and broad:
        print("   GREEN -> survives cost + Deflated Sharpe + per-fold + breadth.")
        print("   THIS justifies building the ONNX export + MT5 inference EA.")
    else:
        why = []
        if rMc.mean() <= 0.03: why.append("net edge thin/neg after cost")
        if dsr < 0.95: why.append(f"DeflatedSR {dsr*100:.0f}%<95% (overfit risk vs {N_TRIALS} trials)")
        if posf < len(foldM) - 1: why.append(f"only {posf}/{len(foldM)} folds positive")
        if not broad: why.append("edge not broad across symbols")
        print("   NOT GREEN -> " + "; ".join(why))
        print("   The PSR-100% gross green did NOT survive honest deflation -> keep iterating, don't deploy.")

    # ================================================================
    #  PATH-A GATES (session 19o) — before any ONNX/live work:
    #   (1) TRUE FORWARD HOLDOUT (CPCV != a clean OOS period)
    #   (2) COST STRESS (wider-spread crosses)
    #   (3) HOUR-DOMINANCE breakdown (feature importance hour=0.33)
    # ================================================================
    print("\n" + "=" * 64)
    print("PATH-A GATES — true forward holdout + cost stress + hour dominance")
    print("=" * 64)

    # --- (1) TRUE HOLDOUT: train on first 80% (time-sorted), test on the never-seen last 20% ---
    split = int(0.80 * n)
    tr0 = list(range(split)); te0 = list(range(split, n))
    trH = purge(tr0, te0, rows, emb)             # drop train labels whose horizon overlaps the test span
    print(f"\n(1) TRUE FORWARD HOLDOUT  train={len(trH)} (of first {split})  "
          f"test={len(te0)} (last 20%, unseen)  "
          f"split@{pd.to_datetime(rows[split]['t0'], unit='s')}")
    if len(trH) > 500 and len(te0) > 50:
        mH = RandomForestClassifier(n_estimators=250, max_depth=5, min_samples_leaf=50,
                                    class_weight="balanced", random_state=7, n_jobs=-1)
        mH.fit(Xof(rows, trH), [rows[i]["y"] for i in trH], sample_weight=uw[trH])
        pH = mH.predict_proba(Xof(rows, te0))[:, 1]
        gate = pH >= 0.55
        gIdx = [te0[k] for k in range(len(te0)) if gate[k]]
        rH = np.array([rows[i]["r"] - rows[i]["costR"] for i in gIdx])   # NET of REAL spread
        allH = np.array([rows[i]["r"] for i in te0])
        print(f"    primary take-all (holdout, mid): trades={len(allH):<5} avgR={allH.mean():+.3f}")
        if len(rH) >= 10:
            shp = rH.mean() / rH.std() if rH.std() > 0 else 0.0
            print(f"    ML gate NET real spread: trades={len(rH):<5} netAvgR={rH.mean():+.3f} "
                  f"totR={rH.sum():+.1f} win={(rH>0).mean()*100:.0f}% Sharpe={shp:+.2f}")
            bysymH = defaultdict(list)
            for i in gIdx: bysymH[rows[i]["symbol"]].append(rows[i]["r"] - rows[i]["costR"])
            npos = sum(1 for v in bysymH.values() if np.mean(v) > 0)
            print(f"    breadth (holdout NET real spr): {npos}/{len(bysymH)} symbols positive — " + "  ".join(
                f"{s}={np.mean(v):+.2f}/{len(v)}" for s, v in sorted(bysymH.items(), key=lambda x: -np.mean(x[1]))))
            hold_ok = rH.mean() > 0.03 and npos >= max(2, len(bysymH) // 2)
            print(f"    >>> HOLDOUT VERDICT (real spread): netAvgR={rH.mean():+.3f} -> "
                  + ("PASS" if hold_ok else "FAIL (real spread eats it)"))
        else:
            print("    ML gate selected too few trades on holdout -> inconclusive")
    else:
        print("    insufficient train/test after purge -> inconclusive")

    # --- (2) SPREAD-GATE SWEEP (THE SALVAGE TEST): does a LOW-SPREAD subset survive? ---
    print("\n(2) SPREAD-GATE SWEEP (CPCV ML-gated, NET of REAL spread) — is a low-spread SUBSET tradeable?")
    ent = np.array([rows[i]["entry_costR"] for i in oosM])
    netreal = np.array([rows[i]["r"] - rows[i]["costR"] for i in oosM])
    if len(ent) > 10:
        print(f"    entry-spread cost (R units): p10={np.percentile(ent,10):.2f} p50={np.percentile(ent,50):.2f} "
              f"p90={np.percentile(ent,90):.2f} max={ent.max():.2f}  (1R = the SL barrier; >1 = spread exceeds barrier)")
        for cap_q in (1.0, 0.75, 0.5, 0.25, 0.10):
            thr = np.quantile(ent, cap_q); mask = ent <= thr; sub = netreal[mask]
            if len(sub) > 5:
                print(f"    keep entry-spread <= p{int(cap_q*100):>3} ({thr:.2f}R): n={len(sub):<5} "
                      f"netAvgR={sub.mean():+.3f} totR={sub.sum():+.1f} win={(sub>0).mean()*100:.0f}%")
        print("    -> if the LOWEST-spread subset is clearly POSITIVE, a spread gate makes it tradeable (set that as MaxSpreadToBarrier).")

    # --- (2b) LIMIT-ORDER EXECUTION MODEL (the ALIGNED fix): a reversion edge = LIQUIDITY PROVISION.
    #     Market order pays the full round-trip spread (f=1, current). A LIMIT fade fills at ~mid and
    #     pays nothing (f=0, ideal). Partial fills / adverse selection sit between. Sweep the fraction
    #     of spread paid -> does providing liquidity instead of taking it rescue the +0.54R mid edge?
    print("\n(2b) LIMIT-EXECUTION SWEEP (spread-fraction paid; reversion = provide liquidity, don't take it):")
    for f in (1.0, 0.75, 0.5, 0.25, 0.0):
        net = np.array([rows[i]["r"] - f * rows[i]["costR"] for i in oosM])
        print(f"    pay {f*100:>3.0f}% of round-trip spread: netAvgR={net.mean():+.3f} totR={net.sum():+.1f} win={(net>0).mean()*100:.0f}%")
    print("    f=1 = market (current, dead); f=0 = ideal limit fill at mid (+0.54R). Crossover where net>0.05")
    print("    = how good fills must be. If even f=0.5 is clearly positive, a maker/limit EA is worth building.")

    # --- (3) HOUR-DOMINANCE breakdown (NET of real spread) ---
    print("\n(3) HOUR BREAKDOWN (CPCV OOS ML-gated, NET real spread) — which hours survive cost?")
    byhr = defaultdict(list)
    for i in oosM: byhr[int(rows[i]["hour"])].append(rows[i]["r"] - rows[i]["costR"])
    tot = sum(sum(v) for v in byhr.values())
    for hr in sorted(byhr):
        v = byhr[hr]; m = np.mean(v); s = np.sum(v)
        bar = "#" * max(0, int(m * 40)) if m > 0 else "." * max(0, int(-m * 40))
        print(f"    hr {hr:02d}h(srv): n={len(v):<4} netAvgR={m:+.3f} totR={s:+5.1f}  {bar}")
    poshrs = sum(1 for v in byhr.values() if np.mean(v) > 0)
    print(f"    {poshrs}/{len(byhr)} hours positive; total netR={tot:+.1f}. "
          "Broad across hours = robust session effect; concentrated in 1-2 hours = fragile.")

    # --- (4) MQL5-PORTABLE FEATURE SET: does the green hold WITHOUT frac-diff? (de-risk ONNX parity) ---
    #     Top importances were hour/tvol_z/mom; fd=0.02/volreg=0.03 (frac-diff) are NEGLIGIBLE.
    #     If these trivially-MQL5-computable features hold the edge, the live EA needs no frac-diff
    #     (maybe no ONNX -- a session-gated simple model/rule suffices).
    FEATS_PORT = ["side", "ret20", "ret60", "rng", "tvol_z", "hour"]
    def Xp(idx): return np.array([[rows[i][f] for f in FEATS_PORT] for i in idx], dtype=float)
    print("\n(4) MQL5-PORTABLE FEATURES (drop frac-diff fd/mom/volreg/vol) — de-risk ONNX parity:")
    oosPort = []
    for b in range(N):
        te = blk[b]; tr = purge([i for bb in range(N) if bb != b for i in blk[bb]], te, rows, emb)
        if len(tr) < 200: continue
        m = RandomForestClassifier(n_estimators=250, max_depth=5, min_samples_leaf=50,
                                   class_weight="balanced", random_state=7, n_jobs=-1)
        m.fit(Xp(tr), [rows[i]["y"] for i in tr], sample_weight=uw[tr])
        p = m.predict_proba(Xp(te))[:, 1]
        for k, i in enumerate(te):
            if p[k] >= 0.55: oosPort.append(i)
    if oosPort:
        rP = np.array([rows[i]["r"] - rows[i]["costR"] for i in oosPort])   # NET real spread
        byP = defaultdict(list)
        for i in oosPort: byP[rows[i]["symbol"]].append(rows[i]["r"] - rows[i]["costR"])
        nP = sum(1 for v in byP.values() if np.mean(v) > 0)
        print(f"    portable ML gate (NET real spr): trades={len(rP)} avgR={rP.mean():+.3f} "
              f"totR={rP.sum():+.1f} win={sum(1 for x in rP if x>0)/len(rP)*100:.0f}%  breadth={nP}/{len(byP)} sym+")
        print(f"    vs full-feature gate avgR={rMc.mean():+.3f}  ->  "
              + ("PORTABLE HOLDS (frac-diff NOT needed -> simpler MQL5 EA, maybe no ONNX)"
                 if rP.mean() > 0.03 and nP >= max(2, len(byP) // 2)
                 else "portable WEAKER (frac-diff matters -> ONNX needed)"))

    # --- (5) MODEL TYPE on portable features: is a HAND-PORTABLE model enough? (decide ONNX vs hand-code) ---
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.preprocessing import StandardScaler
    print("\n(5) MODEL TYPE on portable features (CPCV NET real spread) — decide ONNX vs hand-coded MQL5:")
    models = {
        "RF(d5)":   lambda: RandomForestClassifier(n_estimators=250, max_depth=5, min_samples_leaf=50,
                                                   class_weight="balanced", random_state=7, n_jobs=-1),
        "Logistic": lambda: LogisticRegression(class_weight="balanced", max_iter=1000, C=1.0),
        "Tree(d3)": lambda: DecisionTreeClassifier(max_depth=3, min_samples_leaf=200,
                                                   class_weight="balanced", random_state=7),
    }
    for name, mk in models.items():
        oo = []
        for b in range(N):
            te = blk[b]; tr = purge([i for bb in range(N) if bb != b for i in blk[bb]], te, rows, emb)
            if len(tr) < 200: continue
            Xtr = Xp(tr); Xte = Xp(te)
            if name == "Logistic":
                sc = StandardScaler().fit(Xtr); Xtr = sc.transform(Xtr); Xte = sc.transform(Xte)
            m = mk(); m.fit(Xtr, [rows[i]["y"] for i in tr], sample_weight=uw[tr])
            p = m.predict_proba(Xte)[:, 1]
            for k, i in enumerate(te):
                if p[k] >= 0.55: oo.append(i)
        if oo:
            rr = np.array([rows[i]["r"] - rows[i]["costR"] for i in oo])   # NET real spread
            by = defaultdict(list)
            for i in oo: by[rows[i]["symbol"]].append(rows[i]["r"] - rows[i]["costR"])
            nb = sum(1 for v in by.values() if np.mean(v) > 0)
            print(f"    {name:<10} trades={len(rr):<5} netAvgR={rr.mean():+.3f} totR={rr.sum():+6.1f} "
                  f"win={sum(1 for x in rr if x>0)/len(rr)*100:.0f}% breadth={nb}/{len(by)}")
    print("    -> if Logistic/Tree ~ RF: hand-code into MQL5 (NO ONNX); if only RF: use skl2onnx.")


if __name__ == "__main__":
    main()
