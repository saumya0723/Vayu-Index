"""Phase 13 dry-run/fixture/live orchestrator; live is fail-closed."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import date
from pathlib import Path
from . import rules as R
from .persistence import write_csv,read_csv
from .query_builder import load_basket,build_query_matrix,query_to_output_row
from .source_registry import load_registry,live_gate,registry_hash,ComplianceBlocked

def _blocked_attempt(query,row):
    request_id=R.stable_id("REQUEST13",{"query_id":query.query_id,"attempt":1,"mode":"DRY_RUN"})
    attempt_id=R.stable_id("ATTEMPT13",{"request_id":request_id,"attempt":1})
    return {"collection_attempt_id":attempt_id,"run_id":query.run_id,"request_id":request_id,"query_id":query.query_id,"attempt_ordinal":1,"source_id":query.source_id,"collection_mode":row["collection_mode"],"authorization_status":row["authorization_status"],"route_id":query.route_id,"origin":query.origin,"destination":query.destination,"travel_date":query.travel_date,"apw_target_code":query.apw_target_code,"advance_purchase_window":query.advance_purchase_window,"collection_round_id":query.collection_round_id,"request_url_redacted":"","request_method":"NOT_ISSUED","request_started_at":"","response_received_at":"","latency_ms":"","http_status":"","response_content_type":"","retry_state":"COMPLIANCE_BLOCK","retry_after_seconds":"","collection_status":"NOT_COLLECTED_COMPLIANCE_BLOCK","status_reason":row["notes"],"raw_artifact_hash":"","raw_artifact_path":"","collector_version":R.COLLECTOR_VERSION,"source_terms_review_version":row["terms_review_version"],"phase13_schema_version":R.PHASE13_SCHEMA_VERSION}

def _pct(n,d): return "0.000000" if not d else f"{(100*n/d):.6f}"
def run_dry(root:Path,collection_date:date,sources:list[str]|None=None)->dict[str,object]:
    registry_path=root/"config/phase13_source_compliance_registry.csv"; registry=load_registry(registry_path)
    selected=sorted(sources or registry)
    basket=load_basket(root/"data/official/dgca/processed/vayu_route_basket_2024_25.csv")
    queries=build_query_matrix(collection_date,basket,selected)
    query_rows=[query_to_output_row(item,registry[item.source_id]) for item in queries]
    attempts=[_blocked_attempt(item,registry[item.source_id]) for item in queries]
    output=root/"outputs"
    write_csv(output/"phase13_query_matrix.csv",R.QUERY_COLUMNS,query_rows)
    write_csv(output/"phase13_collection_attempts.csv",R.ATTEMPT_COLUMNS,attempts)
    for name in ("phase13_raw_artifact_manifest.csv","phase13_real_airfare_observations.csv","phase13_phase2_handoff.csv","phase13_collection_errors.csv"):
        write_csv(output/name,R.OUTPUT_SCHEMAS[name],[])
    compliance=[{key:value for key,value in row.items()}|{"phase13_schema_version":R.PHASE13_SCHEMA_VERSION} for row in registry.values()]
    write_csv(output/"phase13_compliance_registry.csv",R.COMPLIANCE_COLUMNS,compliance)
    by_source=Counter(item.source_id for item in queries)
    source_rows=[]
    for sid in selected:
        planned=by_source[sid]; row=registry[sid]
        source_rows.append({"run_id":queries[0].run_id,"source_id":sid,"source_name":row["source_name"],"collection_mode":row["collection_mode"],"authorization_status":row["authorization_status"],"queries_planned":planned,"attempts_recorded":planned,"successful_attempts":0,"failed_attempts":planned,"compliance_blocks":planned,"retry_count":0,"artifacts_captured":0,"observations_extracted":0,"priced_observations":0,"sold_out_observations":0,"no_result_count":0,"missing_price_count":0,"parse_error_count":0,"source_error_count":0,"source_coverage_pct":_pct(0,planned),"phase13_schema_version":R.PHASE13_SCHEMA_VERSION})
    write_csv(output/"phase13_source_coverage.csv",R.SOURCE_COVERAGE_COLUMNS,source_rows)
    route_rows=[]
    for item in basket:
        subset=[q for q in queries if q.route_id==item["route_id"]]; planned=len(subset)
        route_rows.append({"run_id":queries[0].run_id,"route_id":item["route_id"],"basket_rank":item["basket_rank"],"basket_scope":"IN_BASKET","traffic_weight":item["traffic_weight"],"directed_pairs_planned":2,"sources_planned":len(selected),"apws_planned":5,"rounds_planned":3,"queries_planned":planned,"attempts_recorded":planned,"successful_attempts":0,"sources_successful":0,"apws_successful":0,"rounds_successful":0,"priced_observations":0,"sold_out_observations":0,"compliance_blocks":planned,"route_coverage_pct":_pct(0,planned),"phase13_schema_version":R.PHASE13_SCHEMA_VERSION})
    write_csv(output/"phase13_route_coverage.csv",R.ROUTE_COVERAGE_COLUMNS,route_rows)
    round_rows=[]
    for anchor in R.ROUND_ANCHORS:
        subset=[q for q in queries if q.target_collection_round==anchor]; planned=len(subset)
        round_rows.append({"run_id":queries[0].run_id,"collection_round_id":R.round_id(collection_date,anchor),"collection_round_anchor":f"{collection_date.isoformat()} {anchor}","queries_planned":planned,"attempts_recorded":planned,"successful_attempts":0,"sources_planned":len(selected),"sources_successful":0,"routes_planned":15,"routes_successful":0,"apws_planned":5,"apws_successful":0,"priced_observations":0,"sold_out_observations":0,"compliance_blocks":planned,"parse_errors":0,"round_coverage_pct":_pct(0,planned),"phase13_schema_version":R.PHASE13_SCHEMA_VERSION})
    write_csv(output/"phase13_round_coverage.csv",R.ROUND_COVERAGE_COLUMNS,round_rows)
    run={"run_id":queries[0].run_id,"run_mode":"DRY_RUN","run_revision":1,"planned_collection_date":collection_date.isoformat(),"start_time":"","end_time":"","collector_version":R.COLLECTOR_VERSION,"phase13_schema_version":R.PHASE13_SCHEMA_VERSION,"basket_sha256":R.BASKET_SHA256,"source_registry_sha256":registry_hash(registry_path),"configuration_sha256":R.stable_id("CONFIG13",{"date":collection_date.isoformat(),"sources":selected}),"sources_requested":"|".join(selected),"sources_authorized":"","sources_blocked":"|".join(selected),"routes_requested":15,"directed_pairs_requested":30,"apws_requested":5,"rounds_requested":3,"attempt_count":len(attempts),"success_count":0,"failure_count":len(attempts),"retry_count":0,"compliance_block_count":len(attempts),"artifact_count":0,"observation_count":0,"priced_count":0,"sold_out_count":0,"parse_error_count":0,"source_error_count":0,"run_status":"DRY_RUN_COMPLETE_NO_EXTERNAL_REQUESTS","real_collection_started":"False"}
    write_csv(output/"phase13_collection_run_report.csv",R.RUN_COLUMNS,[run]); return run

def run_fixture(root:Path,source_id:str)->dict[str,object]:
    rows=read_csv(root/"tests/fixtures/collection/fixture_registry.csv")
    approved=[row for row in rows if row.get("source_id")==source_id and row.get("fixture_status")=="APPROVED"]
    if not approved: raise ComplianceBlocked(f"{source_id}: fixture NOT_IMPLEMENTED; approved provenance unavailable")
    raise NotImplementedError("approved fixture parser not yet implemented")
def assert_live_allowed(root:Path,source_id:str,today:date)->None:
    registry=load_registry(root/"config/phase13_source_compliance_registry.csv")
    if source_id not in registry: raise ComplianceBlocked("unknown source")
    live_gate(registry[source_id],today)
