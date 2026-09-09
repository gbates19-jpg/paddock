"""Read-only pre-off quote-markout audit. Never imports the Paddock runtime."""
import argparse, csv, hashlib, json, math, statistics, random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

OFFSETS=(300,180,120,60,30,15)
HORIZONS=(5,15,30,60)
COMMISSION=.02

def net(g): return g-max(g,0)*COMMISSION

def hedge(side, entry, exit):
    """Return per initial stake, and per initial liability for LAY."""
    g=entry/exit-1 if side=='BACK' else 1-entry/exit
    return net(g), net(g)/(entry-1) if side=='LAY' else net(g)

def merge(book, levels):
    for p,s in levels:
        if not math.isfinite(p) or not math.isfinite(s): raise ValueError('nonfinite ladder')
        if s<=0: book.pop(p,None)
        elif p>1: book[p]=s

def replay(path, staleness=5000):
    states={}; status=None; inplay=False; schedule=None; targets=[]; snaps={}; last=None
    counts=Counter(); digest=hashlib.sha256(); removed=0; revisions=0
    def snapshot(t):
        if last is None or t<last or t-last>staleness:
            counts['missing_or_stale_snapshot']+=1; return
        snaps[t]={'ts':last,'status':status,'inplay':inplay,'removed':removed,
                  'runners':{k:{**v,'atb':v['atb'].copy(),'atl':v['atl'].copy()} for k,v in states.items()}}
    with path.open('rb') as f:
      for raw in f:
        digest.update(raw); counts['lines']+=1
        o=json.loads(raw); pt=o.get('pt')
        if not isinstance(pt,int): raise ValueError('missing/noninteger timestamp')
        if last is not None and pt<last: raise ValueError('out of order timestamp')
        while targets and targets[0]<pt: snapshot(targets.pop(0))
        for mc in o.get('mc',[]):
          if mc.get('id')!=path.name: raise ValueError('market identity mismatch')
          if mc.get('img'): states={};counts['images']+=1
          d=mc.get('marketDefinition',{})
          if d:
            status=d.get('status',status); inplay=d.get('inPlay',inplay)
            if d.get('marketTime'):
              mt=int(datetime.fromisoformat(d['marketTime'].replace('Z','+00:00')).timestamp()*1000)
              if schedule is None:
                schedule=mt; targets=sorted({mt-off*1000+h*1000 for off in OFFSETS for h in (0,*HORIZONS)})
                # Never fill a target that predates the first definition.
                while targets and targets[0]<pt: targets.pop(0);counts['target_before_definition']+=1
              elif mt!=schedule: revisions+=1
            for r in d.get('runners',[]):
              st=states.setdefault(r['id'],{'atb':{},'atl':{},'status':None})
              if r.get('status')=='REMOVED' and st['status']!='REMOVED': removed+=1
              st['status']=r.get('status',st['status'])
          for rc in mc.get('rc',[]):
            if 'batb' in rc or 'batl' in rc: raise ValueError('unsupported indexed book: quarantine')
            st=states.setdefault(rc['id'],{'atb':{},'atl':{},'status':None})
            for side in ('atb','atl'): merge(st[side],rc.get(side,[]))
        last=pt
    # Equality at EOF is observable; no carry forward beyond end of stream.
    while targets and targets[0]<=last: snapshot(targets.pop(0))
    counts['targets_beyond_eof']+=len(targets)
    if revisions: counts['schedule_revision_market']+=1
    rows=[]
    if schedule is None: return rows,dict(counts),digest.hexdigest()
    def quote(s,sid):
      if not s or s['status']!='OPEN' or s['inplay']: return None
      r=s['runners'].get(sid)
      if not r or r['status']!='ACTIVE' or not r['atb'] or not r['atl']: return None
      b=max(r['atb']);l=min(r['atl'])
      if not 1<b<=l<=100: return None
      return b,l,r['atb'][b],r['atl'][l]
    for off in OFFSETS:
      t=schedule-off*1000; a=snaps.get(t)
      if not a: continue
      for sid in a['runners']:
        q=quote(a,sid)
        if not q: counts['invalid_entry']+=1;continue
        for h in HORIZONS:
          u=t+h*1000;z=snaps.get(u);v=quote(z,sid)
          if not v: counts['invalid_exit']+=1;continue
          if z['removed']!=a['removed']: counts['withdrawal_interval']+=1;continue
          if revisions: counts['excluded_schedule_revision_rows']+=1;continue
          for side in ('BACK','LAY'):
            e,x=(q[0],v[1]) if side=='BACK' else (q[1],v[0])
            # Require displayed capacity for a unit entry and its full equal-profit hedge.
            es,xs=(q[2],v[3]) if side=='BACK' else (q[3],v[2])
            if es<1 or xs<e/x: counts['insufficient_displayed_depth']+=1;continue
            stake,capital=hedge(side,e,x)
            rows.append(dict(market_id=path.name,runner_id=sid,date=datetime.fromtimestamp(schedule/1000,timezone.utc).date().isoformat(),offset=off,horizon=h,side=side,decision_ts=t,entry_source_ts=a['ts'],exit_target_ts=u,exit_source_ts=z['ts'],entry=e,exit=x,stake_return=stake,capital_return=capital))
    return rows,dict(counts),digest.hexdigest()

def summary(rows):
    result={};rng=random.Random(20260909)
    for side in ('BACK','LAY'):
      for h in HORIZONS:
        rr=[r for r in rows if r['side']==side and r['horizon']==h];days=defaultdict(list)
        for r in rr: days[r['date']].append(r['stake_return'])
        vals=[r['stake_return'] for r in rr];clusters=[sum(v)/len(v) for v in days.values()]
        boot=sorted(statistics.mean(rng.choices(clusters,k=len(clusters))) for _ in range(2000)) if clusters else []
        result[f'{side}_{h}s']={'n':len(vals),'row_mean':statistics.mean(vals) if vals else None,'median':statistics.median(vals) if vals else None,'days':len(days),'equal_day_mean':statistics.mean(clusters) if clusters else None,'day_bootstrap_95': [boot[50],boot[1949]] if boot else None,'capital_mean':statistics.mean(r['capital_return'] for r in rr) if rr else None}
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('repo',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--limit',type=int);a=ap.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    # Exact requested population from the existing in-play report, not arbitrary filesystem order.
    prior=Path(__file__).with_name('input-markets.json')
    files=[a.repo/p for p in json.loads(prior.read_text())['files']]
    if a.limit: files=files[:a.limit]
    allrows=[];inventory=[];failures=[];counters=Counter()
    for i,p in enumerate(files,1):
      before=p.stat()
      try:
        rows,c,sha=replay(p)
        after=p.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError('source changed during read')
        inventory.append({'path':str(p),'sha256':sha,'bytes':after.st_size});allrows.extend(rows);counters.update(c)
      except Exception as e: failures.append({'path':str(p),'error':str(e)})
      if i%50==0 or i==len(files):print(f'{i}/{len(files)} markets, {len(allrows)} markouts, {len(failures)} quarantined',flush=True)
    with (a.output/'rows.csv').open('w') as f:
      w=csv.DictWriter(f,fieldnames=list(allrows[0]) if allrows else ['market_id']);w.writeheader();w.writerows(allrows)
    report={'kind':'diagnostic quote markouts, NOT simulated fills or strategy results','source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'config':{'commission':COMMISSION,'offsets':OFFSETS,'horizons':HORIZONS,'max_stream_age_ms':5000,'unit_entry_stake':1,'max_price':100,'schedule':'first observed, revised markets excluded','latency':'zero; no fill claim'},'requested':len(files),'markets_with_rows':len({r['market_id'] for r in allrows}),'rows':len(allrows),'counts':dict(counters),'failures':failures,'summary':summary(allrows),'inventory':inventory}
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
if __name__=='__main__':main()
