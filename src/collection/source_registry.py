"""Fail-closed source-compliance registry loading and live authorization gate."""
from __future__ import annotations
import csv,hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from . import rules as R
from .models import SourceConfig
class ComplianceBlocked(RuntimeError): pass

def load_registry(path:Path)->dict[str,dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as handle: rows=list(csv.DictReader(handle))
    result={row["source_id"]:row for row in rows}
    if tuple(sorted(result))!=tuple(sorted(R.SOURCE_IDS)): raise ValueError("registry must contain exactly eleven required sources")
    return result

def registry_hash(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def live_gate(row:dict[str,str],today:date)->None:
    failures=[]
    if row["collection_mode"] not in R.ALLOWED_LIVE_MODES: failures.append("collection mode not live-authorized")
    if row["authorization_status"]!="APPROVED": failures.append("authorization not approved")
    if row["authorization_evidence_type"] not in R.AUTH_EVIDENCE: failures.append("authorization evidence missing")
    if row["allowed_automation"]!="True" or row["adapter_status"]!="ENABLED": failures.append("adapter disabled")
    if row["terms_review_status"]!="APPROVED": failures.append("terms not approved")
    if not row["terms_review_date"]: failures.append("terms review date missing")
    else:
        reviewed=date.fromisoformat(row["terms_review_date"])
        if (today-reviewed).days>R.TERMS_MAX_AGE_DAYS or today<reviewed: failures.append("terms review inactive")
    if row["authorization_expiry"] and date.fromisoformat(row["authorization_expiry"])<today: failures.append("authorization expired")
    if not row["terms_content_hash"]: failures.append("terms hash missing")
    if row["captcha_present"] not in {"NO","NOT_APPLICABLE"}: failures.append("captcha present or unknown")
    if row["bot_protection_present"] not in {"NO","NOT_APPLICABLE"}: failures.append("bot protection present or unknown")
    if row["rate_limit_policy"] in {"","UNKNOWN"}: failures.append("rate limit unknown")
    if not row["maximum_requests_per_round"]: failures.append("maximum requests per round missing")
    if row["source_health_check"]!="PASSED": failures.append("source health check not passed")
    if row["dry_run_schedule_feasibility"]!="PASSED": failures.append("dry-run feasibility not passed")
    if failures: raise ComplianceBlocked("; ".join(failures))
