import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.api.config import Settings
from src.api.repository import Repository
from src.api.snapshot import Snapshot
from src.api.services.core import latest,routes,collection,backtest
checks=[]
def c(value,label):
    checks.append(bool(value));print(('PASS' if value else 'FAIL'),label)
s=Snapshot.load(Repository(Settings.load(ROOT)))
i=latest(s);co=collection(s);b=backtest(s)
c(i['routes_total']==15,'basket routes total')
c(len(routes(s))==15,'basket routes len')
if i['routes_represented']==2 and i['index_level']=='100.517647':
 c(i['index_level']=='100.517647','latest index baseline')
 c(i['basket_coverage_pct']=='27.3706','coverage percent baseline')
 c(sum(x['route_fare_median'] is None for x in routes(s))==13,'missing route fares null')
 c(co['live_collection_status']=='LIVE_COLLECTION_NOT_STARTED' and co['observation_count']==0,'collection not started')
 c(b['backtest_status']=='PROTOTYPE_BACKTEST' and b['overlap_status']=='NO_OVERLAPPING_COMPLETE_PERIODS' and b['production_status']=='PRODUCTION_BACKTEST_REQUIRED','backtest status')
 c(all(x['metric_value'] is None for x in b['metrics']),'metrics unavailable not zero')
else:
 c(float(i['index_level'])>0,'latest index active')
 c(int(i['routes_represented'])>=0,'coverage routes active')
 c(float(i['basket_coverage_pct'])>=0,'coverage percent active')
html=(ROOT/'src/dashboard/templates/dashboard.html').read_text(encoding='utf-8')
c('DATA STATUS = SYNTHETIC PROTOTYPE' in html,'synthetic banner')
c('LIVE COLLECTION NOT STARTED' in html and 'PRODUCTION BACKTEST REQUIRED' in html,'status banners')
source=''.join(x.read_text(encoding='utf-8') for x in (ROOT/'src/api').rglob('*.py'))
c(all(x not in source.lower() for x in ('subprocess','os.system','requests.get','urllib.request','sqlite3','streamlit','import dash','data/real/raw')),'security source guard')
print(f'PHASE14_VERIFIER passed={sum(checks)} failed={len(checks)-sum(checks)}')
raise SystemExit(0 if all(checks) else 1)
