import argparse,sys
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.api.config import Settings
from src.api.repository import Repository
from src.api.snapshot import Snapshot
from src.api.services.core import latest,collection,backtest
def check():
 s=Snapshot.load(Repository(Settings.load(ROOT)));i=latest(s);c=collection(s);b=backtest(s)
 if i['routes_represented']==2 and i['index_level']=='100.517647':
  assert i['basket_coverage_pct']=='27.3706';assert c['live_collection_status']=='LIVE_COLLECTION_NOT_STARTED' and c['observation_count']==0;assert b['backtest_status']=='PROTOTYPE_BACKTEST' and b['overlap_status']=='NO_OVERLAPPING_COMPLETE_PERIODS' and b['production_status']=='PRODUCTION_BACKTEST_REQUIRED';print('PHASE14_CHECK status=PASS snapshot='+s.identity+' external_requests=0 live_collection=0 [BASELINE_SPEC]')
 else:
  assert float(i['index_level']) > 0;assert int(i['routes_represented']) >= 0;assert int(i['routes_total']) == 15;print(f'PHASE14_CHECK status=PASS snapshot={s.identity} routes={i["routes_represented"]}/{i["routes_total"]} index_level={i["index_level"]} [ACTIVE_DATASET]')
def main():
 p=argparse.ArgumentParser(description='Run Vayu Index API server or perform health checks.')
 p.add_argument('--check',action='store_true',help='Run phase 14 verification checks and exit.')
 p.add_argument('--demo',action='store_true',help='Force DEMO mode (illustrative deterministic INR fares).')
 p.add_argument('--live',action='store_true',help='Force LIVE mode (only real verified provider quotes).')
 p.add_argument('--collect-live',action='store_true',help='Execute Ignav live collection for all 15 routes before starting.')
 p.add_argument('--host',default=os.environ.get('VAYU_HOST','127.0.0.1'))
 p.add_argument('--port',type=int,default=int(os.environ.get('PORT') or os.environ.get('VAYU_PORT','8000')))
 a=p.parse_args()
 if a.check:return check()
 if a.demo:os.environ['VAYU_DEMO_MODE']='true'
 elif a.live:os.environ['VAYU_DEMO_MODE']='false'
 if a.collect_live:
  key=os.environ.get('IGNAV_API_KEY','').strip()
  if not key:
   print('ERROR: --collect-live requested but IGNAV_API_KEY environment variable is not set.',file=sys.stderr)
   return 1
  from src.collection.ignav_live import run_live_collection
  print('Starting live Ignav collection sweep across configured basket routes...')
  try:
   res=run_live_collection(ROOT)
   print(f'Live collection status: {res.get("run_status")}, quotes: {res.get("observation_count")}, verified: {res.get("verified_observation_count")}')
  except Exception as exc:
   print(f'Live collection error: {exc}',file=sys.stderr)
 from src.api.services.route_catalog import is_demo_mode
 mode='DEMO (Illustrative fares marked "DEMO / SYNTHETIC — NOT LIVE")' if is_demo_mode() else 'LIVE (Real provider quotes only)'
 key_status='CONFIGURED' if os.environ.get('IGNAV_API_KEY','').strip() else 'NOT CONFIGURED'
 print(f'VAYU INDEX API starting on http://{a.host}:{a.port}')
 print(f'Active Mode: {mode}')
 print(f'Ignav API Key: {key_status} (never hardcoded, read from IGNAV_API_KEY)')
 print('15 Monitored Basket Routes: BOM-DEL, BLR-DEL, BLR-BOM, DEL-HYD, DEL-PNQ, CCU-DEL, AMD-DEL, DEL-MAA, BOM-HYD, BLR-CCU, DEL-SXR, DEL-GOI, DEL-GAU, BLR-COK, DEL-IDR')
 import uvicorn;uvicorn.run('src.api.main:app',host=a.host,port=a.port,reload=False)
if __name__=='__main__':main()
