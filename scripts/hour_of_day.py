# Scratch study behind DECISIONS F41-F44. Run from the repo root after `uv run wx candles`:
#   uv run --no-project --with pandas --with numpy python scripts/hour_of_day.py
import pandas as pd, numpy as np
D='data/candles/'
for s in ['USDTTMN','BTCTMN','ETHTMN','SOLTMN','XRPTMN','PEPETMN']:
    df=pd.read_csv(D+f'{s}_1h.csv'); df.index=pd.to_datetime(df.t,unit='s'); c=df.c[~df.index.duplicated()]
    r=c.pct_change()*100
    out=[]
    for days in (30,60,110):
        x=r[r.index>=r.index.max()-pd.Timedelta(days=days)]
        g=x.groupby(x.index.hour)
        # window 13:00->01:00 UTC (12h) return per day
        out.append((days, g.mean().round(3)))
    m=pd.concat({d:v for d,v in out},axis=1)
    win=[h for h in list(range(13,24))+[0]]
    print(s,'sum of mean hourly ret 13-01 UTC:', {d: round(m[d].loc[win].sum(),2) for d in (30,60,110)}, ' 01-13 UTC:',{d: round(m[d].drop(win).sum(),2) for d in (30,60,110)})
    # per-day realized 12h window return distribution 13->01
    st=[t for t in c.index if t.hour==13]
    w=[(c.asof(t+pd.Timedelta(hours=12))/c[t]-1)*100 for t in st if t+pd.Timedelta(hours=12)<=c.index[-1]]
    w=np.array(w[-60:]); print('   last 60 days 13->01 UTC window: mean %+.2f%% up %d%% median %+.2f%%'%(w.mean(),(w>0).mean()*100,np.median(w)))
