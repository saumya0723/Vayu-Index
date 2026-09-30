"""Deterministic query-matrix generation from the locked Phase 5 basket."""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from . import rules as R
from .models import QuerySpec

def load_basket(path: Path) -> list[dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as handle:
        rows=list(csv.DictReader(handle))
    if len(rows)!=15 or [int(item["basket_rank"]) for item in rows]!=list(range(1,16)):
        raise ValueError("locked basket integrity failure")
    return rows

def build_query_matrix(collection_date: date, basket: list[dict[str,str]], source_ids: Iterable[str], anchors: Iterable[str]=R.ROUND_ANCHORS) -> list[QuerySpec]:
    preliminary=[]
    for source_id in sorted(source_ids):
        if source_id not in R.SOURCE_IDS: raise ValueError("unknown source")
        for item in sorted(basket,key=lambda value:int(value["basket_rank"])):
            route_id=item["route_id"]
            first,second=route_id.split("-")
            for origin,destination in ((first,second),(second,first)):
                for apw_code,days,window in R.APW_TARGETS:
                    target=R.travel_date(collection_date,days)
                    for anchor in anchors:
                        parameters={"origin":origin,"destination":destination,"travel_date":target.isoformat(),"passenger_count":1,"cabin":"ECONOMY","fare_class_scope":"ALL_CONFIGURED_ECONOMY_BRANDS"}
                        identity={"source_id":source_id,"route_id":route_id,"origin":origin,"destination":destination,"travel_date":target.isoformat(),"apw_target_code":apw_code,"collection_round_id":R.round_id(collection_date,anchor),"parameters":parameters}
                        preliminary.append(QuerySpec(run_id="",query_id=R.stable_id("QUERY13",identity),source_id=source_id,route_id=route_id,basket_rank=int(item["basket_rank"]),basket_scope="IN_BASKET",origin=origin,destination=destination,collection_date=collection_date.isoformat(),travel_date=target.isoformat(),apw_target_code=apw_code,apw_target_days=days,advance_purchase_window=window,target_collection_round=anchor,collection_round_id=R.round_id(collection_date,anchor),collection_round_anchor=f"{collection_date.isoformat()} {anchor}"))
    keys=[item.query_id for item in preliminary]
    if len(keys)!=len(set(keys)): raise ValueError("duplicate query id")
    config={"collection_date":collection_date.isoformat(),"basket_sha256":R.BASKET_SHA256,"source_ids":sorted(source_ids),"rounds":list(anchors),"apws":[x[0] for x in R.APW_TARGETS],"directions":"BOTH"}
    run_id=R.stable_id("RUN13-DRY",config)
    result=[QuerySpec(**{**item.as_row(),"run_id":run_id}) for item in preliminary]
    return sorted(result,key=lambda item:(item.source_id,item.basket_rank,item.origin,item.destination,item.apw_target_days,item.target_collection_round))

def query_to_output_row(item: QuerySpec, registry_row: dict[str,str]) -> dict[str,object]:
    parameters={"origin":item.origin,"destination":item.destination,"travel_date":item.travel_date,"passenger_count":item.passenger_count,"cabin":"ECONOMY","fare_class_scope":item.fare_class_scope}
    return {**item.as_row(),"observed_directed_pair":item.origin+"-"+item.destination,"query_parameters_canonical_json":R.canonical_json(parameters),"compliance_status":"COMPLIANCE_BLOCK" if registry_row["allowed_automation"]!="True" else "AUTHORIZED","planned_collection_status":"NOT_COLLECTED_COMPLIANCE_BLOCK" if registry_row["allowed_automation"]!="True" else "PLANNED_AUTHORIZED","adapter_status":registry_row["adapter_status"],"phase13_schema_version":R.PHASE13_SCHEMA_VERSION}
