"""Locked Phase 13 collection constants and pure deterministic helpers."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
import hashlib, json
from typing import Any, Mapping, Sequence

getcontext().prec = 28
PHASE13_SCHEMA_VERSION = "phase13-v1"
COLLECTOR_VERSION = "phase13-collector-v1"
TIMEZONE = "Asia/Kolkata"
TIMEZONE_SOURCE = "DECLARED_COLLECTION_CONFIGURATION"
BASKET_SHA256 = "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181"
ROUND_ANCHORS = ("09:00", "14:30", "20:15")
ROUND_TOLERANCE_MINUTES = 30
APW_TARGETS = (("T+1",1,"T1(0-2)"),("T+7",7,"T7(5-9)"),("T+15",15,"T15(12-18)"),("T+30",30,"T30(25-35)"),("T+45",45,"T45(40-50)"))
FARE_CLASSES = ("Economy Saver","Economy Standard","Economy Flexi")
SOURCE_IDS = ("indigo","air_india","air_india_express","akasa_air","spicejet","makemytrip","yatra","easemytrip","cleartrip","ixigo","goibibo")
DEFAULT_MIN_INTERVAL_SECONDS = Decimal("5")
DEFAULT_CONCURRENCY = 1
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = (30,120)
TERMS_MAX_AGE_DAYS = 30
ALLOWED_LIVE_MODES = {"AUTHORIZED_API","AUTHORIZED_WEB_COLLECTION","PERMITTED_PUBLIC_ENDPOINT"}
AUTH_EVIDENCE = {"API_CONTRACT","WRITTEN_PERMISSION","PARTNER_ONBOARDING","EXPLICITLY_PERMITTED_PUBLIC_ENDPOINT"}
COLLECTION_OUTCOMES = {"PRICED","SOLD_OUT","NO_RESULT","MISSING_PRICE","BLOCKED","SOURCE_ERROR","PARSE_ERROR","COMPLIANCE_BLOCK"}
RETRY_STATES = {"SUCCESS","RETRYABLE","PERMANENT_FAILURE","COMPLIANCE_BLOCK"}
PHASE2_COLUMNS = ("observation_id","capture_signature","economic_signature","origin","destination","carrier","flight_number","travel_date","departure_time","collection_timestamp","advance_purchase_days","advance_purchase_window","fare_class","base_fare","taxes","fees","total_fare","source","availability_status")
OBSERVATION_EXTENSION_COLUMNS = ("phase13_schema_version","source_id","source_name","source_type","source_url","query_id","request_id","run_id","collection_attempt_id","route_id","basket_rank","basket_scope","observed_directed_pair","arrival_time","arrival_date","collection_round_id","collection_round_anchor","round_alignment","collection_timestamp_exact","collection_timezone","timezone_source","collection_timestamp_utc","apw_target_days","apw_target_code","passenger_count","fare_class_raw","fare_class_normalization_status","base_fare_raw","taxes_raw","airport_charges","airport_charges_raw","convenience_fee","convenience_fee_raw","other_fees","other_fees_raw","fees_derivation_status","total_fare_raw","currency","currency_status","availability_raw","collection_outcome","decomposition_status","raw_artifact_hash","raw_artifact_path","raw_artifact_type","response_content_type","parser_version","collector_version","source_terms_review_version","source_response_record_id","phase2_handoff_eligible","phase2_handoff_exclusion_reason")
OBSERVATION_COLUMNS = PHASE2_COLUMNS + OBSERVATION_EXTENSION_COLUMNS
QUERY_COLUMNS = ("run_id","query_id","source_id","route_id","basket_rank","basket_scope","origin","destination","observed_directed_pair","collection_date","travel_date","apw_target_code","apw_target_days","advance_purchase_window","target_collection_round","collection_round_id","collection_round_anchor","fare_class_scope","passenger_count","currency","query_parameters_canonical_json","compliance_status","planned_collection_status","adapter_status","phase13_schema_version")
ATTEMPT_COLUMNS = ("collection_attempt_id","run_id","request_id","query_id","attempt_ordinal","source_id","collection_mode","authorization_status","route_id","origin","destination","travel_date","apw_target_code","advance_purchase_window","collection_round_id","request_url_redacted","request_method","request_started_at","response_received_at","latency_ms","http_status","response_content_type","retry_state","retry_after_seconds","collection_status","status_reason","raw_artifact_hash","raw_artifact_path","collector_version","source_terms_review_version","phase13_schema_version")
ARTIFACT_COLUMNS = ("raw_artifact_hash","raw_artifact_path","artifact_type","byte_count","content_type","character_encoding","source_id","request_id","query_id","run_id","captured_at","storage_status","immutable","sensitive_data_redacted","retention_policy","collector_version","parser_version","phase13_schema_version")
SOURCE_COVERAGE_COLUMNS = ("run_id","source_id","source_name","collection_mode","authorization_status","queries_planned","attempts_recorded","successful_attempts","failed_attempts","compliance_blocks","retry_count","artifacts_captured","observations_extracted","priced_observations","sold_out_observations","no_result_count","missing_price_count","parse_error_count","source_error_count","source_coverage_pct","phase13_schema_version")
ROUTE_COVERAGE_COLUMNS = ("run_id","route_id","basket_rank","basket_scope","traffic_weight","directed_pairs_planned","sources_planned","apws_planned","rounds_planned","queries_planned","attempts_recorded","successful_attempts","sources_successful","apws_successful","rounds_successful","priced_observations","sold_out_observations","compliance_blocks","route_coverage_pct","phase13_schema_version")
ROUND_COVERAGE_COLUMNS = ("run_id","collection_round_id","collection_round_anchor","queries_planned","attempts_recorded","successful_attempts","sources_planned","sources_successful","routes_planned","routes_successful","apws_planned","apws_successful","priced_observations","sold_out_observations","compliance_blocks","parse_errors","round_coverage_pct","phase13_schema_version")
ERROR_COLUMNS = ("error_id","run_id","request_id","query_id","source_id","route_id","collection_round_id","error_stage","error_code","retry_state","http_status","exception_class","sanitized_message","raw_artifact_hash","occurred_at","terminal","secret_redaction_applied","collector_version","parser_version","phase13_schema_version")
COMPLIANCE_COLUMNS = ("source_id","source_name","source_type","canonical_domain","collection_mode","authorization_status","authorization_evidence_type","authorization_reference","authorization_expiry","robots_status","terms_review_status","terms_review_date","terms_review_version","terms_content_hash","next_review_date","rate_limit_policy","minimum_request_interval_seconds","maximum_requests_per_round","retry_count","backoff_policy","concurrency_limit","captcha_present","bot_protection_present","allowed_automation","browser_collection_authorized","provenance_url","adapter_status","retention_policy","notes","phase13_schema_version")
RUN_COLUMNS = ("run_id","run_mode","run_revision","planned_collection_date","start_time","end_time","collector_version","phase13_schema_version","basket_sha256","source_registry_sha256","configuration_sha256","sources_requested","sources_authorized","sources_blocked","routes_requested","directed_pairs_requested","apws_requested","rounds_requested","attempt_count","success_count","failure_count","retry_count","compliance_block_count","artifact_count","observation_count","priced_count","sold_out_count","parse_error_count","source_error_count","run_status","real_collection_started")
OUTPUT_SCHEMAS={"phase13_query_matrix.csv":QUERY_COLUMNS,"phase13_collection_attempts.csv":ATTEMPT_COLUMNS,"phase13_raw_artifact_manifest.csv":ARTIFACT_COLUMNS,"phase13_real_airfare_observations.csv":OBSERVATION_COLUMNS,"phase13_phase2_handoff.csv":PHASE2_COLUMNS,"phase13_source_coverage.csv":SOURCE_COVERAGE_COLUMNS,"phase13_route_coverage.csv":ROUTE_COVERAGE_COLUMNS,"phase13_round_coverage.csv":ROUND_COVERAGE_COLUMNS,"phase13_collection_errors.csv":ERROR_COLUMNS,"phase13_compliance_registry.csv":COMPLIANCE_COLUMNS,"phase13_collection_run_report.csv":RUN_COLUMNS}

def canonical_json(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True)
def stable_id(namespace: str, value: Any, length: int=32) -> str:
    return namespace+"::"+hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]
def parse_date(value: str) -> date:
    return datetime.strptime(value,"%Y-%m-%d").date()
def travel_date(collection_date: date, days: int) -> date:
    return collection_date+timedelta(days=days)
def round_id(collection_date: date, anchor: str) -> str:
    if anchor not in ROUND_ANCHORS: raise ValueError("unknown round anchor")
    return f"ROUND::{collection_date.isoformat()}T{anchor}"
def parse_money(value: Any) -> Decimal|None:
    text="" if value is None else str(value).strip()
    if not text: return None
    try: return Decimal(text)
    except (InvalidOperation,ValueError): return None
def money(value: Decimal|None) -> str:
    return "" if value is None else format(value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),"f")
def derive_legacy_fees(source_aggregate: Any, components: Sequence[Any]) -> tuple[str,str]:
    aggregate=parse_money(source_aggregate)
    if aggregate is not None: return money(aggregate),"SOURCE_AGGREGATE"
    parsed=[parse_money(item) for item in components]
    if components and all(item is not None for item in parsed): return money(sum((item for item in parsed if item is not None),Decimal("0"))),"SUM_OF_DISCLOSED_COMPONENTS"
    return "","NOT_DERIVED_UNDISCLOSED_COMPONENTS"
def normalize_fare_class(raw: str, mappings: Mapping[str,str]) -> tuple[str,str,bool]:
    key=str(raw).strip()
    mapped=mappings.get(key)
    if mapped in FARE_CLASSES: return mapped,"MAPPED",True
    return key,"UNKNOWN_FARE_CLASS",False
