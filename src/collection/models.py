"""Typed Phase 13 collection records."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Mapping

@dataclass(frozen=True)
class QuerySpec:
    run_id:str; query_id:str; source_id:str; route_id:str; basket_rank:int; basket_scope:str
    origin:str; destination:str; collection_date:str; travel_date:str; apw_target_code:str
    apw_target_days:int; advance_purchase_window:str; target_collection_round:str
    collection_round_id:str; collection_round_anchor:str; passenger_count:int=1
    currency:str="INR"; fare_class_scope:str="ALL_CONFIGURED_ECONOMY_BRANDS"
    def as_row(self)->dict[str,Any]: return asdict(self)

@dataclass(frozen=True)
class RawResponse:
    content:bytes; artifact_type:str; content_type:str; character_encoding:str="utf-8"

@dataclass(frozen=True)
class ParsedObservation:
    source_record_id:str; carrier:str; flight_number:str; departure_time:str
    arrival_time:str; fare_class_raw:str; base_fare:Decimal|None; taxes:Decimal|None
    airport_charges:Decimal|None; convenience_fee:Decimal|None; other_fees:Decimal|None
    source_aggregate_fees:Decimal|None; total_fare:Decimal|None; currency:str
    availability_raw:str; collection_outcome:str

@dataclass(frozen=True)
class CollectionResult:
    status:str; retry_state:str; http_status:str=""; reason:str=""; response:RawResponse|None=None

@dataclass(frozen=True)
class SourceConfig:
    source_id:str; source_name:str; source_type:str; canonical_domain:str
    collection_mode:str; authorization_status:str; allowed_automation:bool
    adapter_status:str; minimum_request_interval_seconds:Decimal
    maximum_requests_per_round:int; retry_count:int; concurrency_limit:int
    terms_review_status:str; terms_review_date:str; terms_review_version:str
    terms_content_hash:str; authorization_evidence_type:str; authorization_expiry:str
    captcha_present:str; bot_protection_present:str; rate_limit_policy:str
    browser_collection_authorized:bool; retention_policy:str
