#!/usr/bin/env python3
from pathlib import Path
import csv,hashlib,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.collection import rules as R
def main():
 passed=failed=0
 def check(ok,label):
  nonlocal passed,failed
  passed+=bool(ok);failed+=not bool(ok)
  if not ok:print("FAIL",label)
 check(hashlib.sha256((ROOT/"data/official/dgca/processed/vayu_route_basket_2024_25.csv").read_bytes()).hexdigest()==R.BASKET_SHA256,"basket hash")
 for name,cols in R.OUTPUT_SCHEMAS.items():
  p=ROOT/"outputs"/name;check(p.exists(),name+" exists")
  if p.exists():check(next(csv.reader(p.open(encoding="utf-8")))==list(cols),name+" schema")
 q=list(csv.DictReader((ROOT/"outputs/phase13_query_matrix.csv").open(encoding="utf-8")));check(len(q)==4950,"query count");check(len({x["query_id"] for x in q})==4950,"query ids")
 check(all(x["planned_collection_status"]=="NOT_COLLECTED_COMPLIANCE_BLOCK" for x in q),"all sources blocked")
 check(not list((ROOT/"data/real/raw").rglob("*.*")),"no raw live artifacts")
 print(f"PHASE13_VERIFIER passed={passed} failed={failed}");return 1 if failed else 0
if __name__=="__main__":raise SystemExit(main())
