"""Contract-aware conservative per-source rate limiter."""
from __future__ import annotations
import time
from decimal import Decimal
class RateLimitExceeded(RuntimeError): pass
class SourceRateLimiter:
    def __init__(self,minimum_interval_seconds:Decimal,maximum_requests_per_round:int,clock=time.monotonic,sleeper=time.sleep):
        if minimum_interval_seconds<0 or maximum_requests_per_round<1: raise ValueError("invalid rate policy")
        self.minimum_interval_seconds=minimum_interval_seconds; self.maximum_requests_per_round=maximum_requests_per_round; self.clock=clock; self.sleeper=sleeper; self.last=None; self.count=0
    def acquire(self)->None:
        if self.count>=self.maximum_requests_per_round: raise RateLimitExceeded("maximum requests per round reached")
        now=Decimal(str(self.clock()))
        if self.last is not None:
            wait=self.minimum_interval_seconds-(now-self.last)
            if wait>0: self.sleeper(int(wait) if wait==int(wait) else str(wait))
        self.last=Decimal(str(self.clock())); self.count+=1
