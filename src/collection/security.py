"""Security invariants and log redaction for Phase 13."""
from __future__ import annotations
import os,re
FORBIDDEN_IMPLEMENTATION_PATTERNS=("captcha solver","captcha bypass","stealth"+" plugin","proxy"+" rotation","rotate ip","cookie harvest","session theft","fake account","bypass 401","bypass 403","bypass 429","private api reverse engineering")
SECRET_KEY_PATTERN=re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie)",re.I)
def assert_safe_source(text:str)->None:
    lowered=text.lower()
    found=[term for term in FORBIDDEN_IMPLEMENTATION_PATTERNS if term in lowered]
    if found: raise ValueError("forbidden security implementation: "+", ".join(found))
def redact_mapping(values:dict[str,object])->dict[str,object]:
    return {key:("[REDACTED]" if SECRET_KEY_PATTERN.search(key) else value) for key,value in values.items()}
def environment_secret(name:str)->str:
    if not SECRET_KEY_PATTERN.search(name): raise ValueError("not a recognized secret key name")
    value=os.environ.get(name)
    if not value: raise RuntimeError(f"required environment secret {name} is unavailable")
    return value
    