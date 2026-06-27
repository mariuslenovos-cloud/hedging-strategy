"""
spreadgrid_opt.py -- optimize the WTI-Brent spread-grid toward GridStat's profile.
Key change: harvest at a PROFIT TARGET (close basket when green by PT) like GridStat
(=> high win rate, losses only on the floor), and test DEEPER entry z. Sweep
entry-z x harvest-mode to lift win% while keeping PF.

Run: python spreadgrid_opt.py
"""
import sys
import numpy as np, pandas as pd, MetaTrader5 as mt5
try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

TF=mt5.TIMEFRAME_H1; NBARS=8000
BETA_LB=300; Z_LB=150; ZFLOOR=6.0; COST=2*6.0/1e4   # 6bps/leg round trip
LADDER_STEP=1.0   # add a unit every +1 z beyond entry

def logc(sym):
    mt5.symbol_select(sym,True); r=mt5.copy_rates_from_pos(sym,TF,0,NBARS)
    return None if r is None else pd.Series(np.log(pd.DataFrame(r)['close'].to_numpy()),index=pd.DataFrame(r)['time'].to_numpy())

def run(o,b,zin,harvest_mode,PT,zexit):
    n=len(o); units=0; sign=0.0; lvl=0; bpnl=0.0; prev=None; cw=0.0
    realized=[]; worst=0.0; floors=0
    for i in range(BETA_LB,n):
        ow=o[i-BETA_LB:i]; bw=b[i-BETA_LB:i]
        beta=np.cov(ow,bw)[0,1]/np.var(bw) if np.var(bw)>0 else 1.0
        sw=o[i-Z_LB:i]-beta*b[i-Z_LB:i]; mu=sw.mean(); sd=sw.std()
        if sd<=0: continue
        s=o[i]-beta*b[i]; z=(s-mu)/sd
        if units!=0 and prev is not None:
            bpnl+=sign*(s-prev); cw=min(cw,bpnl)
        if units==0:
            if abs(z)>=zin:
                sign=-1.0 if z>0 else 1.0; units=1; lvl=1; bpnl=-COST; cw=bpnl
        else:
            need=zin+lvl*LADDER_STEP
            if abs(z)>=need and lvl<5:
                units+=1; lvl+=1; bpnl-=COST
            close=False
            if harvest_mode=="pt"   and bpnl>=PT: close=True
            if harvest_mode=="zrev" and abs(z)<=zexit: close=True
            if abs(z)>=ZFLOOR: close=True; floors+=1
            if close:
                bpnl-=COST*units; realized.append(bpnl); worst=min(worst,cw)
                units=0; lvl=0; bpnl=0.0; cw=0.0
        prev=s
    r=np.array(realized)
    if len(r)<5: return None
    gp=r[r>0].sum(); gl=-r[r<0].sum()
    return dict(n=len(r),win=(r>0).mean(),pf=(gp/gl if gl>0 else 9.99),net=r.sum(),worst=worst,floors=floors,avg=r.mean())

def main():
    if not mt5.initialize(): print("init fail"); return
    o=logc("OILCash"); b=logc("BRENTCash"); mt5.shutdown()
    df=pd.concat([o,b],axis=1,join='inner').dropna(); o=df.iloc[:,0].to_numpy(); b=df.iloc[:,1].to_numpy()
    print(f"WTI-Brent H1 bars: {len(o)}\n")
    print(f"{'config':<34}{'baskets':>8}{'win%':>7}{'PF':>7}{'net':>9}{'worstMTM':>10}{'floors':>8}")
    print("-"*84)
    # baseline z-revert
    for zin in [1.0,2.0]:
        r=run(o,b,zin,"zrev",None,0.25)
        if r: print(f"{'zrev entry z='+str(zin):<34}{r['n']:>8}{r['win']*100:>6.0f}%{r['pf']:>7.2f}{r['net']:>+9.3f}{r['worst']:>+10.3f}{r['floors']:>8}")
    # profit-target harvest (GridStat analog) x entry depth x PT
    for zin in [1.5,2.0,2.5]:
        for PT in [0.010,0.020,0.035]:
            r=run(o,b,zin,"pt",PT,None)
            if r: print(f"{'PT='+str(PT)+' entry z='+str(zin):<34}{r['n']:>8}{r['win']*100:>6.0f}%{r['pf']:>7.2f}{r['net']:>+9.3f}{r['worst']:>+10.3f}{r['floors']:>8}")
    print("\nGoal: profit-target harvest should lift win% toward GridStat's 75-85% (losses only on floor),")
    print("while keeping PF>1.8. Pick the robust high-win + high-PF cell -> that's the EA config.")

if __name__=="__main__": main()
