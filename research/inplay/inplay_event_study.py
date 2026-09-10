#!/usr/bin/env python3
"""Read-only in-play/suspension event study for Betfair stream files.

Detects marketDefinition inPlay transitions and SUSPENDED->OPEN reopens,
then measures conservative executable price moves after a configurable
latency. No database or existing file is modified.
"""
from __future__ import annotations
import argparse, csv, json, math, statistics, sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EPS=1e-12
HORIZONS=(1,2,5,10,30)
LATENCIES=(0,250,500,1000)
MAX_PRICE=100.0
THRESHOLDS=(0.0025,0.005,0.01,0.02,0.05)

def usable(p):
    try: p=float(p)
    except (TypeError,ValueError): return False
    return 1.0 < p <= MAX_PRICE

def merge_abs(book, levels):
    if not isinstance(levels,list): return
    for x in levels:
        if not isinstance(x,list) or len(x)<2: continue
        try: p,s=float(x[0]),float(x[1])
        except (TypeError,ValueError): continue
        if p<=1.0 or s<=0: book.pop(p,None)
        else: book[p]=s

def merge_index(book, idxmap, levels):
    if not isinstance(levels,list): return
    for x in levels:
        if not isinstance(x,list) or len(x)<3: continue
        try: i=int(x[0]); p=float(x[1]); s=float(x[2])
        except (TypeError,ValueError): continue
        old=idxmap.get(i)
        if old is not None and old != p: book.pop(old,None)
        if p<=1.0 or s<=0:
            if old is not None: book.pop(old,None)
            idxmap.pop(i,None)
        else:
            book[p]=s; idxmap[i]=p

def best(book, back):
    ps=[p for p in book if usable(p)]
    if not ps: return None
    return max(ps) if back else min(ps)

def feat(st):
    bp=best(st['atb'],True); lp=best(st['atl'],False)
    return {'back':bp,'lay':lp,'mid':math.log((bp+lp)/2) if bp and lp else None,
            'status':st.get('status','OPEN'),'inplay':bool(st.get('inplay',False)),
            'traded':sum(st['trd'].values())}

def empty(): return {'atb':{},'atl':{},'atb_i':{},'atl_i':{},'trd':{},'status':'OPEN','inplay':False}

def update(st, rc):
    merge_abs(st['atb'],rc.get('atb')); merge_abs(st['atl'],rc.get('atl'))
    merge_index(st['atb'],st['atb_i'],rc.get('batb')); merge_index(st['atl'],st['atl_i'],rc.get('batl'))
    merge_abs(st['trd'],rc.get('trd'))
    if 'tv' in rc:
        try: st['_tv']=float(rc['tv'])
        except (TypeError,ValueError): pass

def snap(states): return {sid:feat(st) for sid,st in states.items()}
def parse_time(s): return datetime.fromisoformat(str(s).replace('Z','+00:00'))
def date_of(s): return parse_time(s).astimezone(timezone.utc).date().isoformat()

def ret_back(entry_back, exit_lay, comm):
    if not entry_back or not exit_lay: return None
    gross=entry_back/exit_lay-1
    return gross-max(gross,0)*comm

def ret_lay(entry_lay, exit_back, comm):
    if not entry_lay or not exit_back: return None
    gross=1-entry_lay/exit_back
    return gross-max(gross,0)*comm

def parse_market(path, comm, latency):
    """Parse events with entry available only after reaction latency.

    Each event's entry is the first observed OPEN quote at or after
    event_ts + latency.  Horizons are measured from that entry target, not
    from the pre-event snapshot.  Actual source timestamps are retained;
    missing/stale quotes are excluded rather than backfilled.
    """
    states={}; names={}; pending=[]; rows=[]; market_id=path.name; market_date=''; last_def=None; event_seq=0
    history=deque()
    with path.open(encoding='utf-8') as fh:
      for line in fh:
        try:o=json.loads(line)
        except json.JSONDecodeError: continue
        pt=o.get('pt')
        if not isinstance(pt,(int,float)): continue
        pt=int(pt)
        defs=[]
        for mc in o.get('mc',[]) or []:
            if not isinstance(mc,dict): continue
            if isinstance(mc.get('marketDefinition'),dict): defs.append(mc['marketDefinition'])
            if mc.get('id'): market_id=str(mc['id'])
        for d in defs:
            if not market_date and d.get('marketTime'): market_date=date_of(d['marketTime'])
            if not states:
                for r in d.get('runners',[]) or []:
                    try:sid=int(r['id'])
                    except (KeyError,TypeError,ValueError): continue
                    states[sid]=empty(); names[sid]=str(r.get('name',sid)); states[sid]['status']=r.get('status','OPEN')
            old=last_def
            old_ip=bool(old.get('inPlay')) if old else False
            new_ip=bool(d.get('inPlay',old_ip))
            old_status=str(old.get('status','OPEN')) if old else str(d.get('status','OPEN'))
            new_status=str(d.get('status',old_status))
            if old and not old_ip and new_ip:
                event_seq+=1; pending.append({'event_id':event_seq,'event_type':'inplay_transition','event_ts':pt,'date':market_date,'prior10':next((ss for ts,ss in reversed(history) if ts<=pt-10000),{})})
            if old and old_status=='SUSPENDED' and new_status=='OPEN':
                event_seq+=1; pending.append({'event_id':event_seq,'event_type':'reopen','event_ts':pt,'date':market_date,'prior10':next((ss for ts,ss in reversed(history) if ts<=pt-10000),{})})
            for r in d.get('runners',[]) or []:
                try:sid=int(r['id'])
                except (KeyError,TypeError,ValueError): continue
                states.setdefault(sid,empty()); names[sid]=str(r.get('name',sid))
                if r.get('status') is not None: states[sid]['status']=r['status']
            last_def=d
            for st in states.values(): st['inplay']=new_ip; st['status']=new_status
        for mc in o.get('mc',[]) or []:
            if not isinstance(mc,dict): continue
            for rc in mc.get('rc',[]) or []:
                try:sid=int(rc['id'])
                except (KeyError,TypeError,ValueError): continue
                states.setdefault(sid,empty()); update(states[sid],rc)
        if not states: continue
        current=snap(states); history.append((pt,current))
        while history and history[0][0]<pt-120000: history.popleft()
        for e in pending:
            if 'entry' not in e and pt>=e['event_ts']+latency:
                e['entry']=(pt,current)
            if 'entry' not in e: continue
            if 'labels' not in e: e['labels']={}
            entry_ts=e['entry'][0]
            for h in HORIZONS:
                target=entry_ts+h*1000
                if h not in e['labels'] and pt>=target: e['labels'][h]=(pt,current)
            if len(e['labels'])!=len(HORIZONS): continue
            base=current=e['entry'][1]; prior=e.get('prior10') or {}
            for sid,b in base.items():
                if b.get('mid') is None: continue
                p=prior.get(sid,{})
                pre=(b['mid']-p.get('mid')) if p.get('mid') is not None else None
                row={'market_id':market_id,'date':e['date'],'event_id':e['event_id'],'event_type':e['event_type'],'event_ts':e['event_ts'],'entry_actual_ts':e['entry'][0],'entry_latency_gap_ms':e['entry'][0]-(e['event_ts']+latency),'runner_id':sid,'runner_name':names.get(sid,str(sid)),'pre_move_10s':pre,'base_back':b.get('back'),'base_lay':b.get('lay')}
                for h in HORIZONS:
                    actual,ss=e['labels'][h]; q=ss.get(sid,{})
                    row[f'h{h}_actual_ts']=actual; row[f'h{h}_latency_gap_ms']=actual-(e['entry'][0]+h*1000)
                    row[f'h{h}_back']=q.get('back'); row[f'h{h}_lay']=q.get('lay'); row[f'h{h}_move']=(q['mid']-b['mid']) if q.get('mid') is not None else None
                    # Betfair's atb/atl names describe the action available
                    # to the incoming bettor: BACK consumes atb, LAY consumes
                    # atl.  Keep the same side mapping in the independent
                    # in-play study as in the pre-off study.
                    row[f'h{h}_back_ret']=ret_back(b.get('back'),q.get('lay'),comm); row[f'h{h}_lay_ret']=ret_lay(b.get('lay'),q.get('back'),comm)
                rows.append(row)
            e['done']=True
        pending[:]=[e for e in pending if not e.get('done')]
    yield from rows

def discover(root): return sorted(p for p in root.rglob('1.*') if p.is_file() and p.name[2:].isdigit())

def cluster_stats(rows, key, subset):
    by={}
    for r in subset: by.setdefault(r['date'],[]).append(r[key])
    vals=[sum(x)/len(x) for x in by.values() if x]
    return {'date_clusters':len(vals),'mean_date_cluster':sum(vals)/len(vals) if vals else None,'median_date_cluster':statistics.median(vals) if vals else None,'min_date_cluster':min(vals) if vals else None,'max_date_cluster':max(vals) if vals else None}

def summarize(rows, files, comm, latency):
    dates=sorted({r['date'] for r in rows}); cut=max(1,int(len(dates)*0.7)); train=set(dates[:cut]); test=set(dates[cut:])
    out={'study':'paddock_inplay_suspension_event_study','report_version':'v3-atb-atl','read_only':True,'commission_rate':comm,'latency_ms':latency,'betfair_field_semantics':{'atb':'Available To Back; BACK entry consumes atb','atl':'Available To Lay; LAY entry consumes atl','source':'https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687396/Exchange+Stream+API'},'payoff_sanity':{'unchanged_book':{'atb':2.0,'atl':2.02},'back_then_lay':'2.00/2.02 - 1 < 0','lay_then_back':'1 - 2.02/2.00 < 0'},'max_executable_price':MAX_PRICE,'files_requested':len(files),'markets_with_events':len({r['market_id'] for r in rows}),'row_count':len(rows),'dates':dates,'calibration_dates':sorted(train),'heldout_dates':sorted(test),'horizons_sec':list(HORIZONS),'event_types':{t:sum(r['event_type']==t for r in rows) for t in sorted({r['event_type'] for r in rows})}}
    results=[]
    # Calibrate threshold and direction separately for continuation/reversal, then freeze on held-out.
    for direction in ('continuation','reversal'):
      for h in HORIZONS:
       key=f'h{h}_'+('back_ret' if direction=='continuation' else 'lay_ret')
       # direction depends on pre-move sign; select corresponding return.
       def v(r):
         if r.get('pre_move_10s') is None: return None
         x=r.get(f'h{h}_back_ret') if ((r['pre_move_10s']>0)==(direction=='continuation')) else r.get(f'h{h}_lay_ret')
         return x
       best=None
       for th in THRESHOLDS:
        tr=[r for r in rows if r['date'] in train and r.get('pre_move_10s') is not None and abs(r['pre_move_10s'])>=th and v(r) is not None]
        score=sum(v(r) for r in tr)/len(tr) if tr else -999
        cand=(score,len(tr),th)
        if best is None or cand>best: best=cand
       th=best[2] if best else THRESHOLDS[0]
       for split,ds in [('calibration',train),('heldout',test)]:
        sub=[r for r in rows if r['date'] in ds and r.get('pre_move_10s') is not None and abs(r['pre_move_10s'])>=th and v(r) is not None]
        vals=[v(r) for r in sub]
        rec={'direction':direction,'horizon_sec':h,'split':split,'threshold_abs_pre_move':th,'rows':len(vals),'mean_return':sum(vals)/len(vals) if vals else None}
        rec.update(cluster_stats(rows, '__tmp__', [])) if False else None
        datevals={d:[v(r) for r in sub if r['date']==d] for d in ds}; datevals={d:x for d,x in datevals.items() if x}
        cl=[sum(x)/len(x) for x in datevals.values()]; rec.update({'date_clusters':len(cl),'mean_date_cluster':sum(cl)/len(cl) if cl else None,'median_date_cluster':statistics.median(cl) if cl else None,'min_date_cluster':min(cl) if cl else None,'max_date_cluster':max(cl) if cl else None,'clears_zero_and_costs':(sum(cl)/len(cl)>0.0 if cl else False)})
        results.append(rec)
    out['calibration_heldout_results']=results
    return out

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--data-root',type=Path,default=Path(__file__).parents[2]/'data'/'pro'); ap.add_argument('--out-dir',type=Path,default=Path(__file__).parent/'output'); ap.add_argument('--limit',type=int); ap.add_argument('--commission',type=float,default=.02); ap.add_argument('--latency-ms',type=int,default=1000)
 a=ap.parse_args(); files=discover(a.data_root); files=files[:a.limit] if a.limit else files
 if not files: print('No files found',file=sys.stderr); return 2
 rows=[]; failures=[]
 for i,p in enumerate(files,1):
  try: rows.extend(parse_market(p,a.commission,a.latency_ms))
  except Exception as e: failures.append({'file':str(p),'error':repr(e)})
  if i==1 or i%100==0 or i==len(files): print(f'processed {i}/{len(files)} files; rows={len(rows)} failures={len(failures)}',file=sys.stderr)
 a.out_dir.mkdir(parents=True,exist_ok=True); csvp=a.out_dir/'inplay_event_rows.csv'; jsonp=a.out_dir/'inplay_event_report.json'
 fields=sorted({k for r in rows for k in r});
 with csvp.open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 report=summarize(rows,files,a.commission,a.latency_ms); report['failures']=failures; report['csv']=str(csvp); report['files']=[str(p) for p in files]; jsonp.write_text(json.dumps(report,indent=2,sort_keys=True),encoding='utf-8')
 print(json.dumps({'report':str(jsonp),'csv':str(csvp),'files':len(files),'rows':len(rows),'failures':len(failures)})); return 0
if __name__=='__main__': raise SystemExit(main())
