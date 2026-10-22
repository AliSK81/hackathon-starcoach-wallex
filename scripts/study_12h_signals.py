# Scratch study behind DECISIONS F41-F44. Run from the repo root after `uv run wx candles`:
#   uv run --no-project --with pandas --with numpy python scripts/study_12h_signals.py
import pandas as pd, numpy as np
D='data/candles/'
def load(s,r): df=pd.read_csv(D+f'{s}_{r}.csv'); df.index=pd.to_datetime(df.t,unit='s'); return df
def rsi(c,n=14):
    d=c.diff(); u=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); v=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean(); return 100-100/(1+u/v)
def atr(df,n=14):
    tr=pd.concat([df.h-df.l,(df.h-df.c.shift()).abs(),(df.l-df.c.shift()).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/n,adjust=False).mean()
def adx(df,n=14):
    up=df.h.diff(); dn=-df.l.diff()
    pdm=np.where((up>dn)&(up>0),up,0.); ndm=np.where((dn>up)&(dn>0),dn,0.)
    a=atr(df,n); pdi=100*pd.Series(pdm,df.index).ewm(alpha=1/n,adjust=False).mean()/a; ndi=100*pd.Series(ndm,df.index).ewm(alpha=1/n,adjust=False).mean()/a
    dx=100*(pdi-ndi).abs()/(pdi+ndi); return dx.ewm(alpha=1/n,adjust=False).mean(),pdi,ndi
SP={'BTCTMN':.075,'ETHTMN':.12,'SOLTMN':.27,'XRPTMN':.22,'PEPETMN':.10,'USDTTMN':.014}
M6=['BTCTMN','ETHTMN','SOLTMN','XRPTMN','PEPETMN','USDTTMN']
M12=['PUMPTMN','ARBTMN','BNBTMN','DOGETMN','TRXTMN','STMN','APETMN','SUITMN','LTCTMN','UNITMN','ADATMN','SANDTMN']
usd=load('USDTTMN','1h').c
btc=load('BTCTMN','1h').c
rows=[]
for m in M6+M12:
    df=load(m,'1h'); df=df[~df.index.duplicated()]
    c=df.c; e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean()
    r=rsi(c); a=atr(df); ad,pdi,ndi=adx(df)
    ret24=c.pct_change(24)*100; ret4=c.pct_change(4)*100; ret1=c.pct_change(1)*100
    typ=c.pct_change(24).abs().rolling(720).median()*100
    hi24=df.h.rolling(24).max().shift(1); lo24=df.l.rolling(24).min().shift(1)
    vr=df.v/df.v.rolling(24).mean()
    bb_m=c.rolling(20).mean(); bb_s=c.rolling(20).std(); z=(c-bb_m)/bb_s
    u_tr=(usd.ewm(span=20,adjust=False).mean()>usd.ewm(span=50,adjust=False).mean()).reindex(c.index,method='ffill')
    b24=(btc.pct_change(24)*100).reindex(c.index,method='ffill')
    # forward 12h with a 4-ATR stop on closes (approx), cost
    cost=0.5+SP.get(m,0.3)
    fwd=np.full(len(c),np.nan); cv=c.values; av=(a/c).values
    for i in range(len(c)-12):
        stop=cv[i]*(1-4*av[i]); path=cv[i+1:i+13]; hit=np.where(path<=stop)[0]
        out=(stop if len(hit) else path[-1]); fwd[i]=(out/cv[i]-1)*100-cost
    d=pd.DataFrame(dict(fwd=fwd,trend=(e20>e50).values,adx=ad.values,pdi=pdi.values,ndi=ndi.values,rsi=r.values,ret24=ret24.values,ret4=ret4.values,ret1=ret1.values,typ=typ.values,
        brk=(c>hi24).values,brkdn=(c<lo24).values,vr=vr.values,z=z.values,above200=(c>e200).values,utr=u_tr.values,b24=b24.values,slope=(e20.pct_change(3)*100).values),index=c.index)
    d['m']=m; d['set']='6' if m in M6 else '12'; rows.append(d.iloc[760:])
A=pd.concat(rows).dropna(subset=['fwd','typ'])
half=A.index.min()+(A.index.max()-A.index.min())/2
SIGNALS_FIRST_PASS={
 'every hour':A.fwd==A.fwd,
 'trend 20>50':A.trend,
 'trend & adx>25 & +di>-di':A.trend&(A.adx>25)&(A.pdi>A.ndi),
 'trend & above200 & rsi<65':A.trend&A.above200&(A.rsi<65),
 'trend & pullback z<-1':A.trend&(A.z<-1),
 'trend & pullback rsi<45':A.trend&(A.rsi<45),
 'breakout 24h high':A.brk,
 'breakout & vol>2x':A.brk&(A.vr>2),
 'sharp drop 24h<=-2typ':(A.ret24<=-2*A.typ),
 'rsi<30':A.rsi<30,
 'rsi<25 & z<-2':(A.rsi<25)&(A.z<-2),
 'z<-2.5':A.z<-2.5,
 '4h move > 1.5 typ (momentum)':A.ret4>1.5*A.typ,
 'USDT trend up & coin trend':A.utr&A.trend,
 'USDT trend down & coin trend':(~A.utr.astype(bool))&A.trend,
 'BTC up 24h>2 & coin trend':(A.b24>2)&A.trend,
 'breakdown 24h low':A.brkdn,
}

S={
 'capitulation rsi<25&z<-2':(A.rsi<25)&(A.z<-2),
 'dip z<-2&rsi<30':(A.z<-2)&(A.rsi<30),
 'dip z<-2&rsi<30&utr':(A.z<-2)&(A.rsi<30)&A.utr.astype(bool),
 'dip z<-2&rsi<30&b24>-3':(A.z<-2)&(A.rsi<30)&(A.b24>-3),
 'dip z<-2&above200':(A.z<-2)&A.above200,
 'dip z<-2.5':(A.z<-2.5),
 'sharpdrop&rsi<30':(A.ret24<=-2*A.typ)&(A.rsi<30),
 'trendstrong&utr&b24>0':A.trend&(A.adx>25)&(A.pdi>A.ndi)&A.utr.astype(bool)&(A.b24>0),
 'trendstrong&utr&rsi<70':A.trend&(A.adx>25)&(A.pdi>A.ndi)&A.utr.astype(bool)&(A.rsi<70),
 'trend&utr&b24>2':A.trend&A.utr.astype(bool)&(A.b24>2),
 'brk&vol>2&utr':A.brk&(A.vr>2)&A.utr.astype(bool),
}
print(f"{'signal':34s} {'n':>6s} {'mean':>7s} {'se':>5s} {'win':>4s} {'h1':>7s} {'h2':>7s} {'set6':>7s} {'set12':>7s} {'last30d':>8s}")
last30=A.index.max()-pd.Timedelta(days=30)
for k,mask in {**SIGNALS_FIRST_PASS, **S}.items():
    x=A[mask.fillna(False).astype(bool)]
    if len(x)<20: print(k,len(x)); continue
    f=x.fwd
    print(f"{k:34s} {len(f):6d} {f.mean():+7.2f} {f.std()/np.sqrt(len(f)/12):5.2f} {(f>0).mean()*100:4.0f} {f[x.index<half].mean():+7.2f} {f[x.index>=half].mean():+7.2f} {x[x.set=='6'].fwd.mean():+7.2f} {x[x.set=='12'].fwd.mean():+7.2f} {f[x.index>=last30].mean():+8.2f}")

