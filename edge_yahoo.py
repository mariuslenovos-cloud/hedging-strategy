#!/usr/bin/env python3
"""
NIGHT BATCH (Yahoo data = fast; MT5 only for real COSTS, already saved). Three
cost-first screens vs GridStat, all from one daily fetch per market:
 (A) GRID-SUITABILITY  -- dailyATR/cost (moves-per-spread) x reversion(VR). GOLD=benchmark.
 (B) TREND-FOLLOWING   -- Donchian 20/10, net of real spread. Judge net/Sharpe/PF.
 (C) OVERNIGHT EDGE    -- indices' close->open vs open->close, net of spread (structural).
"""
import json, time, numpy as np, pandas as pd
import urllib.request

# Yahoo ticker -> (MT5 cost symbol for real spread, label)
MAP = {
 "^NDX":("US100Cash","NAS100"),"^GSPC":("US500Cash","SP500"),"^DJI":("US30Cash","DOW30"),
 "^GDAXI":(None,"DAX40"),"^FTSE":(None,"FTSE100"),"^N225":(None,"NIK225"),"^HSI":(None,"HSI50"),
 "^AXJO":(None,"ASX200"),"^FCHI":(None,"CAC40"),
 "GC=F":("GOLD","GOLD"),"SI=F":("SILVER","SILVER"),"CL=F":("OILCash","WTI"),
 "BZ=F":("BRENTCash","BRENT"),"NG=F":("NGASCash","NATGAS"),"HG=F":(None,"COPPER"),"PL=F":(None,"PLAT"),
 "EURUSD=X":("EURUSD","EURUSD"),"GBPUSD=X":("GBPUSD","GBPUSD"),"USDJPY=X":("USDJPY","USDJPY"),
 "USDCHF=X":("USDCHF","USDCHF"),"USDCAD=X":("USDCAD","USDCAD"),"AUDUSD=X":("AUDUSD","AUDUSD"),
 "NZDUSD=X":("NZDUSD","NZDUSD"),"EURJPY=X":("EURJPY","EURJPY"),"GBPJPY=X":("GBPJPY","GBPJPY"),
 "EURGBP=X":("EURGBP","EURGBP"),"AUDJPY=X":("AUDJPY","AUDJPY"),
 "BTC-USD":("BTCUSD","BTCUSD"),"ETH-USD":("ETHUSD","ETHUSD"),"SOL-USD":(None,"SOLUSD"),
}
IS_INDEX = lambda lab: lab in ("NAS100","SP500","DOW30","DAX40","FTSE100","NIK225","HSI50","ASX200","CAC40")

def fetch(tk, rng="5y"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval=1d"
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r: j=json.load(r)
        res=j["chart"]["result"][0]; q=res["indicators"]["quote"][0]
        df=pd.DataFrame({"o":q["open"],"h":q["high"],"l":q["low"],"c":q["close"]}).dropna()
        return df if len(df)>300 else None
    except Exception as e:
        print(f"  {tk}: FETCH FAIL {str(e)[:40]}",flush=True); return None

def vr(r,q):
    r=np.asarray(r,float); n=len(r)
    if n<q*3: return np.nan
    mu=r.mean(); v1=((r-mu)**2).sum()/(n-1)
    rq=np.convolve(r,np.ones(q),"valid"); vq=((rq-q*mu)**2).sum()/(len(rq)-1)
    return vq/(q*v1) if v1>0 else np.nan

def donchian(h,l,c,cost,N=20,Nx=10):
    n=len(c);pos=0;ep=0;pnl=[];hold=[];ei=0
    hh=pd.Series(h).rolling(N).max().shift(1).values;ll=pd.Series(l).rolling(N).min().shift(1).values
    xh=pd.Series(h).rolling(Nx).max().shift(1).values;xl=pd.Series(l).rolling(Nx).min().shift(1).values
    for i in range(N,n):
        if pos==0:
            if c[i]>hh[i]:pos=1;ep=c[i];ei=i
            elif c[i]<ll[i]:pos=-1;ep=c[i];ei=i
        elif pos==1 and c[i]<xl[i]:pnl.append((c[i]-ep)/ep-cost);hold.append(i-ei);pos=0
        elif pos==-1 and c[i]>xh[i]:pnl.append((ep-c[i])/ep-cost);hold.append(i-ei);pos=0
    if len(pnl)<8:return None
    a=np.array(pnl);eq=np.cumsum(a);dd=eq-np.maximum.accumulate(eq)
    return dict(tr=len(a),win=(a>0).mean(),net=a.sum(),pf=(a[a>0].sum()/-a[a<0].sum()) if (a<0).any() else 9.9,
                sh=a.mean()/a.std()*np.sqrt(len(a)) if a.std()>0 else 0,dd=-dd.min(),hold=np.mean(hold))

def main():
    costs=pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    grid=[];trend=[];night=[]
    for tk,(cs,lab) in MAP.items():
        df=fetch(tk)
        if df is None: continue
        o,h,l,c=df["o"].values,df["h"].values,df["l"].values,df["c"].values
        cb=costs.get(cs,2.0)                       # real MT5 spread bps if mapped, else ~2bps index assumption
        atr=pd.Series(np.maximum(h-l,np.abs(pd.Series(c).diff()))).rolling(20).mean().iloc[-250:].mean()
        atr_bps=atr/c[-1]*1e4; mps=atr_bps/cb if cb>0 else 0
        ret=np.diff(np.log(c)); v=vr(ret,5)
        grid.append((lab,round(cb,2),int(atr_bps),round(mps,1),round(v,2)))
        bt=donchian(h,l,c,cb/1e4)
        if bt: trend.append((lab,round(cb,2),bt["tr"],round(bt["win"],2),round(bt["net"]*100,1),
                             round(bt["pf"],2),round(bt["sh"],2),round(bt["dd"]*100,1),int(bt["hold"])))
        if IS_INDEX(lab):
            on=(o[1:]-c[:-1])/c[:-1]; idr=(c[1:]-o[1:])/o[1:]; onnet=on-cb/1e4
            sh=onnet=onnet if False else on-cb/1e4
            shp=onnet.mean()/onnet.std()*np.sqrt(252) if onnet.std()>0 else 0
            night.append((lab,round(cb,2),round(on.sum()*100,1),round(idr.sum()*100,1),
                          round((on>0).mean()*100),round(onnet.sum()*100,1),round(shp,2)))
        print(f"  {lab}: {len(df)} bars done",flush=True)
    print("\n"+"="*74);print("(A) GRID-SUITABILITY (dailyATR/cost x reversion; GOLD=benchmark)");print("="*74)
    print(pd.DataFrame(grid,columns=["mkt","cost_bps","atr_bps","moves_per_spread","VR5"]).sort_values("moves_per_spread",ascending=False).to_string(index=False))
    print("\n"+"="*74);print("(B) TREND-FOLLOWING net of spread (Donchian 20/10) -- judge Sharpe/PF/net not win%");print("="*74)
    print(pd.DataFrame(trend,columns=["mkt","cost","trades","win","net%","PF","Sharpe","maxDD%","hold_d"]).sort_values("Sharpe",ascending=False).to_string(index=False))
    print("\n"+"="*74);print("(C) OVERNIGHT INDEX EDGE: ON=close->open hold, ID=open->close, net of spread");print("="*74)
    print(pd.DataFrame(night,columns=["idx","cost","ON_tot%","ID_tot%","ON_win%","ON_net%","ON_Sharpe"]).sort_values("ON_Sharpe",ascending=False).to_string(index=False))
    pd.DataFrame(trend,columns=["mkt","cost","trades","win","net%","PF","Sharpe","maxDD%","hold_d"]).to_csv("_trend_screen.csv",index=False)
    print("\ndone.",flush=True)

if __name__=="__main__": main()
