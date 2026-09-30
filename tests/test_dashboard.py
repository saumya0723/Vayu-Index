from pathlib import Path
from fastapi.testclient import TestClient
from src.api.main import create_app
ROOT=Path(__file__).resolve().parents[1]
def test_dashboard():
 with TestClient(create_app(ROOT)) as c:r=c.get('/dashboard')
 assert r.status_code==200
 for x in ('DATA STATUS = SYNTHETIC PROTOTYPE','LIVE COLLECTION NOT STARTED','PRODUCTION BACKTEST REQUIRED','Executive overview','Index history','Routes','Collection monitor','Anomaly monitor','Backtest','Methodology/provenance'):assert x in r.text
 js=(ROOT/'src/dashboard/static/dashboard.js').read_text();assert 'fetch(p+x)' in js and '.csv' not in js and 'Not available' in js
