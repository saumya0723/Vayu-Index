"""Bounded deterministic retry classification."""
from __future__ import annotations
from dataclasses import dataclass
from . import rules as R
@dataclass(frozen=True)
class RetryDecision:
    state:str; should_retry:bool; wait_seconds:int; reason:str

def classify(http_status:int|None,attempt_ordinal:int,retry_after_seconds:int|None=None,compliance_block:bool=False)->RetryDecision:
    if compliance_block:return RetryDecision("COMPLIANCE_BLOCK",False,0,"source not authorized")
    if http_status is not None and 200<=http_status<300:return RetryDecision("SUCCESS",False,0,"success")
    retryable=http_status in {408,425,500,502,503,504}
    if http_status==429:
        if retry_after_seconds is None:return RetryDecision("PERMANENT_FAILURE",False,0,"429 without approved Retry-After")
        retryable=True
    if retryable and attempt_ordinal<R.DEFAULT_MAX_ATTEMPTS:
        wait=retry_after_seconds if retry_after_seconds is not None else R.DEFAULT_BACKOFF_SECONDS[attempt_ordinal-1]
        return RetryDecision("RETRYABLE",True,wait,"bounded retry")
    return RetryDecision("PERMANENT_FAILURE",False,0,"non-retryable or attempts exhausted")
