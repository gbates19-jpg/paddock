import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from proof import hedge,replay,merge
class ProofTests(unittest.TestCase):
 def test_back_hedge_both_settlements(self):
  for b,l in [(3,2),(2,3),(2,2.02)]:
   lay=b/l;win=(b-1)-lay*(l-1);lose=-1+lay
   self.assertAlmostEqual(win,lose)
   self.assertAlmostEqual(hedge('BACK',b,l)[0],win-max(win,0)*.02)
 def test_lay_hedge_both_settlements(self):
  for l,b in [(2,3),(3,2),(2.02,2)]:
   back=l/b;win=-(l-1)+back*(b-1);lose=1-back
   self.assertAlmostEqual(win,lose)
   self.assertAlmostEqual(hedge('LAY',l,b)[0],win-max(win,0)*.02)
   self.assertAlmostEqual(hedge('LAY',l,b)[1],hedge('LAY',l,b)[0]/(l-1))
 def test_flat_spread_costs_both_sides(self):
  self.assertLess(hedge('BACK',2,2.02)[0],0);self.assertLess(hedge('LAY',2.02,2)[0],0)
 def fixture(self,change=None):
  off=1500000000000;t=off-300000
  d={'marketTime':datetime.fromtimestamp(off/1000,timezone.utc).isoformat(),'status':'OPEN','inPlay':False,'runners':[{'id':1,'status':'ACTIVE'}]}
  events=[{'pt':t-1000,'mc':[{'id':'1.1','marketDefinition':d,'rc':[{'id':1,'atb':[[2,100]],'atl':[[2.02,100]]}]}]}, {'pt':t+1000,'mc':[{'id':'1.1','rc':[{'id':1,'atb':[[2,0],[3,100]],'atl':[[2.02,0],[3.05,100]]}]}]}, {'pt':t+5000,'mc':[{'id':'1.1','rc':[]}]}]
  if change:change(events)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'1.1';p.write_text('\n'.join(json.dumps(x) for x in events));return replay(p),t
 def test_asof_and_exact_eof(self):
  (rows,c,_),t=self.fixture();r=next(r for r in rows if r['side']=='BACK')
  self.assertEqual(r['entry'],2);self.assertEqual(r['entry_source_ts'],t-1000);self.assertEqual(r['exit_source_ts'],t+5000)
  self.assertTrue(all(r['entry_source_ts']<=r['decision_ts'] and r['exit_source_ts']<=r['exit_target_ts'] for r in rows))
 def test_suspension(self):
  (rows,_,_),_=self.fixture(lambda e:e[1]['mc'][0].update(marketDefinition={'status':'SUSPENDED'}));self.assertEqual(rows,[])
 def test_inplay(self):
  (rows,_,_),_=self.fixture(lambda e:e[1]['mc'][0].update(marketDefinition={'inPlay':True}));self.assertEqual(rows,[])
 def test_removed(self):
  (rows,_,_),_=self.fixture(lambda e:e[1]['mc'][0].update(marketDefinition={'runners':[{'id':1,'status':'REMOVED'}]}));self.assertEqual(rows,[])
 def test_no_eof_backfill(self):
  (rows,_,_),_=self.fixture(lambda e:e.pop());self.assertEqual(rows,[])
 def test_out_of_order_quarantines(self):
  with self.assertRaises(ValueError):self.fixture(lambda e:e[2].update(pt=e[0]['pt']-1))
 def test_image_clears_old_book(self):
  (rows,_,_),_=self.fixture(lambda e:e[1]['mc'][0].update(img=True,rc=[]));self.assertEqual(rows,[])
 def test_stale_entry(self):
  (rows,_,_),_=self.fixture(lambda e:e[0].update(pt=e[0]['pt']-10000));self.assertEqual(rows,[])
 def test_schedule_revision_quarantine(self):
  (rows,c,_),_=self.fixture(lambda e:e[1]['mc'][0].update(marketDefinition={'marketTime':'2020-01-01T00:00:00Z'}));self.assertEqual(rows,[]);self.assertEqual(c['schedule_revision_market'],1)
 def test_depth_capacity(self):
  (rows,_,_),_=self.fixture(lambda e:e[0]['mc'][0]['rc'][0].update(atb=[[2,.1]],atl=[[2.02,.1]]));self.assertEqual(rows,[])
 def test_ladder_deletion(self):
  b={2:5};merge(b,[[2,0],[3,10]]);self.assertEqual(b,{3:10})
if __name__=='__main__':unittest.main()
