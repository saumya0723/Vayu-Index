"""Common adapter contract. Network access is impossible while disabled."""
from __future__ import annotations
from abc import ABC,abstractmethod
from typing import Any
from ..models import CollectionResult,ParsedObservation,QuerySpec,RawResponse
class AdapterDisabled(RuntimeError): pass
class SourceAdapter(ABC):
    source_id=""; adapter_status="AUTHORIZATION_REQUIRED"; parser_version="NOT_IMPLEMENTED"
    def build_query(self,query:QuerySpec)->dict[str,Any]:
        return {"source_id":self.source_id,"origin":query.origin,"destination":query.destination,"travel_date":query.travel_date,"passenger_count":query.passenger_count}
    def collect(self,query:QuerySpec)->CollectionResult:
        raise AdapterDisabled(f"{self.source_id}: NOT_COLLECTED_COMPLIANCE_BLOCK")
    def parse(self,response:RawResponse,query:QuerySpec)->list[ParsedObservation]:
        raise NotImplementedError(f"{self.source_id}: parser NOT_IMPLEMENTED")
    def validate_source_response(self,response:RawResponse)->None:
        if not response.content: raise ValueError("empty source response")
    @property
    def enabled(self)->bool:return self.adapter_status=="ENABLED"
