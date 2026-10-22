# Scratch study behind DECISIONS F41-F44. Run from the repo root after `uv run wx candles`:
#   uv run --no-project --with pandas --with numpy python scripts/study_12h_windows.py
# 12-hour window study on saved candles. Costs: TMN maker 0.25%, USDT maker 0.10%, plus half spread each side.
import pandas as pd, numpy as np, sys
D='data/candles/'
def load(s, r='1m'):
    df=pd.read_csv(D+f'{s}_{r}.csv'); df.index=pd.to_datetime(df.t,unit='s'); return df
def bars(s, rule):
    df=load(s); return df.c.resample(rule).last().ffill()
SPREAD={'BTCTMN':.075,'ETHTMN':.12,'SOLTMN':.27,'XRPTMN':.22,'PEPETMN':.10,'USDTTMN':.014}
TM=['BTCTMN','ETHTMN','SOLTMN','XRPTMN','PEPETMN']
US=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','PEPEUSDT']
H=12
def windows(idx, step='6h'):
    starts=pd.date_range(idx[0].ceil('D')+pd.Timedelta(days=4), idx[-1]-pd.Timedelta(hours=H), freq=step)
    return starts
def summary(name, r):
    r=np.array(r); print(f'{name:38s} n={len(r):3d} mean={r.mean():+.2f}% med={np.median(r):+.2f}% up={np.mean(r>0)*100:4.0f}% worst={r.min():+.2f}% best={r.max():+.2f}%')
def trend_ret(close, fast, slow, start, end, rt_cost):
    # hold while ema fast > slow (signal from previous closed bar), flat at end. returns % of 1 unit
    ef=close.ewm(span=fast,adjust=False).mean(); es=close.ewm(span=slow,adjust=False).mean()
    sig=(ef>es).shift(1).fillna(False)
    seg=close[start:end]; s=sig[start:end]
    if len(seg)<2: return 0.0
    rets=seg.pct_change().fillna(0)
    pos=s.astype(float)
    pos.iloc[-1]=0  # flat at end
    g=(1+rets*pos.shift(1).fillna(0)).prod()-1
    trades=(pos.diff().abs().fillna(pos.iloc[0])).sum()/2
    return (g*100 - trades*rt_cost)
c1h={s:bars(s,'1h') for s in TM+['USDTTMN']}
c15={s:bars(s,'15min') for s in TM+['USDTTMN']}
cu1h={s:bars(s,'1h') for s in US}
cu15={s:bars(s,'15min') for s in US}
idx=c1h['BTCTMN'].index
for period,since in [('all 120d',None),('last 30d',idx[-1]-pd.Timedelta(days=30)),('last 10d',idx[-1]-pd.Timedelta(days=10))]:
    st=windows(idx)
    if since is not None: st=st[st>=since]
    print('====',period, len(st),'windows of',H,'h')
    usdt=[(c1h['USDTTMN'].asof(s+pd.Timedelta(hours=H))/c1h['USDTTMN'].asof(s)-1)*100-0.5-0.014 for s in st]
    summary('hold USDT (USDTTMN maker in/out)',usdt)
    bh=[np.mean([(c1h[m].asof(s+pd.Timedelta(hours=H))/c1h[m].asof(s)-1)*100-0.5-SPREAD[m] for m in TM]) for s in st]
    summary('hold 5 coins equal (TMN)',bh)
    for (lab,cc,f,sl) in [('trend 1h 20/50 TMN',c1h,20,50),('trend 15m 20/50 TMN',c15,20,50),('trend 15m 8/21 TMN',c15,8,21),('trend 1h 10/30 TMN',c1h,10,30)]:
        r=[np.mean([trend_ret(cc[m],f,sl,s,s+pd.Timedelta(hours=H),0.5+SPREAD[m]) for m in TM]) for s in st]
        summary(lab,r)
    # USDT route: convert all TMN->USDT at start and back at end (0.5%), trend on coin/USDT at 0.2%+0.3 spread guess
    for (lab,cc,f,sl) in [('USDT route + trend 1h 20/50',cu1h,20,50),('USDT route + trend 15m 20/50',cu15,20,50)]:
        r=[]
        for s in st:
            u=(c1h['USDTTMN'].asof(s+pd.Timedelta(hours=H))/c1h['USDTTMN'].asof(s)-1)*100-0.514
            r.append(u+np.mean([trend_ret(cc[m],f,sl,s,s+pd.Timedelta(hours=H),0.2+0.3) for m in US]))
        summary(lab,r)
    # TMN trend while holding the idle cash as USDT
    r=[]
    for s in st:
        u=(c1h['USDTTMN'].asof(s+pd.Timedelta(hours=H))/c1h['USDTTMN'].asof(s)-1)*100-0.514
        r.append(u+np.mean([trend_ret(cu1h[m],20,50,s,s+pd.Timedelta(hours=H),0.2+0.3) for m in US]))
