#!/usr/bin/env python3
from pathlib import Path
import argparse,sys
from datetime import date
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.collection.collection_engine import run_dry,run_fixture,assert_live_allowed
from src.collection.source_registry import ComplianceBlocked
def main():
 p=argparse.ArgumentParser();m=p.add_mutually_exclusive_group(required=True);m.add_argument("--dry-run",action="store_true");m.add_argument("--fixture",action="store_true");m.add_argument("--live",action="store_true");p.add_argument("--source");p.add_argument("--round",choices=["09:00","14:30","20:15"]);p.add_argument("--collection-date",default="2026-09-14");a=p.parse_args()
 try:
  if a.dry_run: print(run_dry(ROOT,date.fromisoformat(a.collection_date)))
  elif a.fixture:
   if not a.source:p.error("--fixture requires --source")
   print(run_fixture(ROOT,a.source))
  else:
   if not a.source or not a.round:p.error("--live requires --source and --round")
   assert_live_allowed(ROOT,a.source,date.today());raise ComplianceBlocked("live transport intentionally unavailable: no approved adapter implemented")
 except ComplianceBlocked as e: print("COMPLIANCE_BLOCK:",e,file=sys.stderr);return 2
 return 0
if __name__=="__main__":raise SystemExit(main())
