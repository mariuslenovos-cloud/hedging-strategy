"""
fxfade_tree.py -- Path A build step 0: extract the FINAL depth-3 tree rules for the
MQL5 rollover-fade EA (NO ONNX). Trains the depth-3 tree on ALL events (6 portable
features), prints the if/else rule tree + per-leaf trade stats, so the fade-enter
leaves (P(win)>=0.55) can be hand-coded into MQL5.

Caches the built events (fxfade_rows.pkl) so model experiments don't re-pull MT5.
Run: python fxfade_tree.py
"""
import os, pickle, sys
import numpy as np
import MetaTrader5 as mt5
from sklearn.tree import DecisionTreeClassifier, export_text
import afml_engine as A

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

CACHE = "fxfade_rows.pkl"
FP = ["side", "ret20", "ret60", "rng", "tvol_z", "hour"]   # MQL5-portable feature set


def get_rows():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            rows = pickle.load(f)
        print(f"loaded {len(rows)} cached events from {CACHE}")
        return rows
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    rows = []
    for s in A.SYMBOLS:
        r = A.get_bars(s, A.NBARS)
        if r is None:
            print(f"  {s}: no data"); continue
        sr = A.build_symbol(s, r); rows += sr
        print(f"  {s}: {len(sr)} events")
    mt5.shutdown()
    rows.sort(key=lambda r: r["t0"])
    with open(CACHE, "wb") as f:
        pickle.dump(rows, f)
    print(f"built + cached {len(rows)} events -> {CACHE}")
    return rows


def main():
    rows = get_rows()
    uw = np.array(A.uniqueness(rows))
    X = np.array([[r[f] for f in FP] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows])
    rR = np.array([r["r"] for r in rows])
    syms = [r["symbol"] for r in rows]

    t = DecisionTreeClassifier(max_depth=3, min_samples_leaf=200,
                               class_weight="balanced", random_state=7)
    t.fit(X, y, sample_weight=uw)
    print("\n=== FINAL depth-3 tree (rules to hand-code in MQL5) ===")
    print(export_text(t, feature_names=FP, show_weights=False))

    # per-leaf trade stats: which leaves are the fade-enter rules (P(win)>=0.55)?
    leaf = t.apply(X)
    proba = t.predict_proba(X)[:, 1]
    print("=== per-leaf stats (the FADE-ENTER leaves have P>=0.55) ===")
    print(f"  {'leaf':>5} {'P(win)':>7} {'n':>6} {'avgR':>7} {'netR@.15':>9} {'win%':>6}  enter?")
    enter_leaves = []
    for lf in sorted(set(leaf)):
        m = leaf == lf
        p = proba[m][0]
        rr = rR[m]
        net = rr.mean() - 0.15
        win = (rr > 0).mean() * 100
        enter = p >= 0.55
        if enter: enter_leaves.append(lf)
        print(f"  {lf:>5} {p:>7.3f} {m.sum():>6} {rr.mean():>+7.3f} {net:>+9.3f} {win:>5.0f}%  {'YES' if enter else '.'}")

    # overall if we trade only the enter-leaves
    em = np.isin(leaf, enter_leaves)
    rr = rR[em]; net = rr - 0.15
    from collections import defaultdict
    by = defaultdict(list)
    for i in np.where(em)[0]: by[syms[i]].append(rR[i] - 0.15)
    nb = sum(1 for v in by.values() if np.mean(v) > 0)
    print(f"\n  TRADE the enter-leaves: n={em.sum()} netAvgR={net.mean():+.3f} "
          f"totR={net.sum():+.1f} win={(rr>0).mean()*100:.0f}% breadth={nb}/{len(by)}")
    # hour distribution of entered trades (confirm rollover concentration)
    hrs = np.array([rows[i]["hour"] for i in np.where(em)[0]], dtype=int)
    from collections import Counter
    hc = Counter(hrs)
    print("  entered-trade hours (UTC): " + "  ".join(f"{h:02d}h:{hc[h]}" for h in sorted(hc)))


if __name__ == "__main__":
    main()
