# Scratch study behind DECISIONS F41-F44. Run from the repo root after `uv run wx candles`:
#   uv run --no-project --with pandas --with numpy python scripts/check_tmn_usdt_gaps.py
import pandas as pd, numpy as np
D='data/candles/'
def load(s): df=pd.read_csv(D+f'{s}_1m.csv'); df.index=pd.to_datetime(df.t,unit='s'); return df
u=load('USDTTMN')
for b in ['BTC','ETH','SOL','XRP','PEPE','DOGE']:
    t=load(b+'TMN'); us=load(b+'USDT')
    j=pd.concat([t.c.rename('t'),t.v.rename('tv'),us.c.rename('u'),us.v.rename('uv'),u.c.rename('x'),u.v.rename('xv')],axis=1).dropna()
    j=j[(j.tv>0)&(j.uv>0)]  # both coin books traded this minute
    dev=(j.t/(j.u*j.x)-1)*100
    last=dev[dev.index>=dev.index.max()-pd.Timedelta(days=14)]
    print(f"{b:5s} minutes={len(dev):6d} med={dev.median():+.2f}% |dev|>0.8%: {np.mean(dev.abs()>0.8)*100:5.1f}%  >1.2%: {np.mean(dev.abs()>1.2)*100:5.1f}%  last14d med={last.median():+.2f} |dev|>0.8%={np.mean(last.abs()>0.8)*100:4.1f}% n14={len(last)}")
