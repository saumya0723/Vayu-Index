from pathlib import Path
from fastapi.testclient import TestClient
from src.api.main import create_app
ROOT=Path(__file__).resolve().parents[1]
def test_phase14_api():
 with TestClient(create_app(ROOT)) as c:
  for path in ('/api/v1/health','/api/v1/status','/api/v1/metadata','/api/v1/index/latest','/api/v1/index/history','/api/v1/index/period','/api/v1/index/coverage','/api/v1/routes','/api/v1/routes/BOM-DEL','/api/v1/routes/BOM-DEL/history','/api/v1/sources','/api/v1/collection/status','/api/v1/backtest/status','/api/v1/anomalies','/api/v1/exports','/api/v1/methodology'):assert c.get(path).status_code==200
  i=c.get('/api/v1/index/latest').json()['data']
  if i['routes_represented']==2 and i['index_level']=='100.517647':
   assert i['routes_total']==15
  else:
   assert float(i['index_level'])>0 and int(i['routes_represented'])>=0 and int(i['routes_total'])==15
  assert c.get('/api/v1/index/latest?filename=../secret').status_code==422;assert c.post('/api/v1/status').status_code==405
  assert c.get('/api/v1/exports/latest-index?format=json').status_code==200;assert c.get('/api/v1/exports/routes?format=csv').status_code==200
