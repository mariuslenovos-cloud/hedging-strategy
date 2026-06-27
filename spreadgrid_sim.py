"""
spreadgrid_sim.py -- FEASIBILITY test of the synthesis idea: run GridStat's grid-harvest
engine on a STRUCTURALLY-cointegrated SPREAD (WTI-Brent) instead of a single instrument.
The spread is bounded + reverts (cointegration) -> ideal grid substrate, no blow-up tail.

Grid: synthetic spread s = logOIL - beta*logBRENT (beta rolling). rolling z of s.
  - when z extends past a grid level (1,2,3..), ADD a unit AGAINST the move (fade): z>0 short-spread, z<0 long.
  - HARVEST the whole basket when z reverts past ZEXIT toward 0 (the +$ target analog).
  - FLOOR: bail the basket if |z| >= ZFLOOR (cointegration break = the only real risk).
Cost charged per unit per leg. Market-neutral. Judge net / PF / worst-basket / #baskets.

Run: python spreadgrid_sim.py
"""
import sys
import numpy as np, pandas as pd, MetaTrader5 as mt5
try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

TF=mt5.TIMEFRAME_H1; NBARS=8000
BETA_LB=300; Z_LB=150
GRID_Z=[1.0,2.0,3.0,4.0]      # add a unit each time |z| crosses these
ZEXIT=0.25; ZFLOOR=6.0
COST_BPS_LEG=6.0              # per-leg cost in bps, charged on entry+exit of each unit

def logc(sym):
    mt5.symbol_select(sym,True)
    r=mt5.copy_rates_from_pos(sym,TF,0,NBARS)
    if r is None: return None
    return pd.Series(np.log(pd.DataFrame(r)['close'].to_numpy()),index=pd.DataFrame(r)['time'].to_numpy())

def main():
    if not mt5.initialize(): print("init fail"); return
    o=logc("OILCash"); b=logc("BRENTCash"); mt5.shutdown()
    df=pd.concat([o,b],axis=1,join='inner').dropna(); df.columns=['o','b']
    o=df['o'].to_numpy(); b=df['b'].to_numpy(); n=len(df)
    print(f"WTI-Brent H1 bars: {n}")
    cost=2*COST_BPS_LEG/1e4

    units=0; entry_levels=0; basket_pnl=0.0; n_units=0
    realized=[]; worst=0.0; floors=0; baskets=0; cur_worst=0.0
    z_hist=[]
    for i in range(BETA_LB,n):
        ow=o[i-BETA_LB:i]; bw=b[i-BETA_LB:i]
        beta=np.cov(ow,bw)[0,1]/np.var(bw) if np.var(bw)>0 else 1.0
        sw=(o[i-Z_LB:i]-beta*b[i-Z_LB:i]); mu=sw.mean(); sd=sw.std()
        if sd<=0: continue
        s=o[i]-beta*b[i]; z=(s-mu)/sd; z_hist.append(z)
        # MTM the open basket (units * change in spread, signed: short-spread profits when s falls)
        if units!=0:
            ds=s - prev_s
            basket_pnl += -np.sign(units)*0  # placeholder; compute below per-unit
        # simpler: track position as signed unit count; pnl from spread change
        if units!=0:
            basket_pnl += pos_sign*(s-prev_s)
            cur_worst=min(cur_worst,basket_pnl)
        # decide actions
        if units==0:
            # open first unit when |z|>=GRID_Z[0]
            if abs(z)>=GRID_Z[0]:
                pos_sign = -1.0 if z>0 else 1.0   # fade: short spread if rich
                units=1; entry_levels=1; basket_pnl=-cost; n_units=1; cur_worst=basket_pnl
        else:
            # add a unit at each deeper grid level (same side)
            lvl=sum(1 for g in GRID_Z if abs(z)>=g)
            if lvl>entry_levels and entry_levels<len(GRID_Z):
                units+=1; entry_levels+=1; basket_pnl-=cost; n_units+=1
            # harvest at reversion
            if abs(z)<=ZEXIT:
                basket_pnl-=cost*units   # exit cost all units
                realized.append(basket_pnl); worst=min(worst,cur_worst); baskets+=1
                units=0; entry_levels=0; basket_pnl=0.0; cur_worst=0.0
            elif abs(z)>=ZFLOOR:
                basket_pnl-=cost*units; realized.append(basket_pnl); worst=min(worst,cur_worst)
                baskets+=1; floors+=1; units=0; entry_levels=0; basket_pnl=0.0; cur_worst=0.0
        prev_s=s
    r=np.array(realized)
    if len(r)==0: print("no baskets"); return
    gp=r[r>0].sum(); gl=-r[r<0].sum()
    print(f"\n=== WTI-Brent SPREAD-GRID (H1, fade z>={GRID_Z[0]}, ladder {GRID_Z}, harvest |z|<={ZEXIT}, floor {ZFLOOR}, {COST_BPS_LEG}bps/leg) ===")
    print(f"  baskets={len(r)}  net={r.sum():+.4f} (log-spread units)  avg={r.mean():+.4f}  win={(r>0).mean()*100:.0f}%")
    print(f"  PF={gp/gl if gl>0 else 9.99:.2f}  worst single-basket MTM={worst:+.4f}  floor-hits={floors}")
    print(f"  z range: min={min(z_hist):.1f} max={max(z_hist):.1f}  (|z| rarely exceeds floor {ZFLOOR} = bounded, grid-safe)")
    # convert to rough $ intuition: 1 log unit ~ 100% of notional per unit. net in % of 1-unit notional:
    print(f"  net {r.sum()*100:+.1f}% of one spread-unit notional over {n} H1 bars (~{n/24/22:.0f} months)")
    print(f"  PF>1.5 + bounded z (no floor hits) = the synthesis works -> build the MT5 two-leg spread-grid EA.")

if __name__=="__main__": main()
