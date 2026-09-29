from datetime import date
from decimal import Decimal
from pathlib import Path
import hashlib,csv
import pytest
from src.collection import rules as R
from src.collection.query_builder import load_basket,build_query_matrix
from src.collection.retry_policy import classify
from src.collection.source_registry import load_registry,live_gate,ComplianceBlocked
from src.collection.provenance import persist_raw_artifact
ROOT=Path(__file__).resolve().parents[1]
def test_apw_exact_calendar_arithmetic():
 assert [R.travel_date(date(2026,1,31),d).isoformat() for _,d,_ in R.APW_TARGETS]==['2026-02-01','2026-02-07','2026-02-15','2026-03-02','2026-03-17']
def test_basket_and_both_directions_and_deterministic_ids():
 b=load_basket(ROOT/'data/official/dgca/processed/vayu_route_basket_2024_25.csv');a=build_query_matrix(date(2026,9,14),b,R.SOURCE_IDS);z=build_query_matrix(date(2026,9,14),list(reversed(b)),reversed(R.SOURCE_IDS));assert len(a)==4950;assert [x.query_id for x in a]==[x.query_id for x in z];assert {'BOM-DEL','DEL-BOM'}<={x.origin+'-'+x.destination for x in a}
def test_decimal_and_unknown_fare():
 assert R.parse_money('0.1')+R.parse_money('0.2')==Decimal('0.3');assert R.normalize_fare_class('Mystery',{})==('Mystery','UNKNOWN_FARE_CLASS',False)
def test_fee_projection_only_disclosed():
 assert R.derive_legacy_fees('',[Decimal('1'),Decimal('2')])==('3.00','SUM_OF_DISCLOSED_COMPONENTS');assert R.derive_legacy_fees('',[])==('','NOT_DERIVED_UNDISCLOSED_COMPONENTS')
def test_retry_bounded_and_429():
 assert classify(503,1).wait_seconds==30;assert classify(503,3).state=='PERMANENT_FAILURE';assert classify(429,1).state=='PERMANENT_FAILURE';assert classify(429,1,17).wait_seconds==17
def test_registry_all_live_blocked():
 reg=load_registry(ROOT/'config/phase13_source_compliance_registry.csv');assert len(reg)==11
 for row in reg.values():
  with pytest.raises(ComplianceBlocked):live_gate(row,date(2026,9,13))
def test_artifact_content_addressed_exclusive(tmp_path):
 a=persist_raw_artifact(tmp_path,'indigo',b'abc','json');b=persist_raw_artifact(tmp_path,'indigo',b'abc','json');assert a[0]==hashlib.sha256(b'abc').hexdigest();assert b[2]=='ALREADY_PRESENT_IDENTICAL'
def test_phase2_prefix_exact(): assert R.OBSERVATION_COLUMNS[:19]==R.PHASE2_COLUMNS
def test_no_forbidden_code():
 text='\n'.join(p.read_text(encoding='utf-8').lower() for p in (ROOT/'src/collection').rglob('*.py'))
 for token in ('selenium','playwright','requests.get','httpx','random.uuid','uuid4','proxy rotation','stealth plugin'):assert token not in text
