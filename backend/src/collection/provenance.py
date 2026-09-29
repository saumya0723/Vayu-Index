"""Content-addressed immutable raw-artifact persistence."""
from __future__ import annotations
import hashlib
from pathlib import Path
from . import rules as R

def sha256_bytes(content:bytes)->str: return hashlib.sha256(content).hexdigest()
def artifact_relative_path(source_id:str,digest:str,extension:str)->str:
    safe=extension.lower().lstrip(".") or "bin"
    return f"data/real/raw/{source_id}/{digest[:2]}/{digest}.{safe}"
def persist_raw_artifact(root:Path,source_id:str,content:bytes,extension:str)->tuple[str,str,str]:
    digest=sha256_bytes(content); relative=artifact_relative_path(source_id,digest,extension); target=root/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open("xb") as handle: handle.write(content)
        status="CREATED"
    except FileExistsError:
        if target.read_bytes()!=content: raise RuntimeError("content-address collision")
        status="ALREADY_PRESENT_IDENTICAL"
    return digest,relative,status

def artifact_manifest_row(*,digest:str,path:str,artifact_type:str,content:bytes,content_type:str,source_id:str,request_id:str,query_id:str,run_id:str,captured_at:str,retention_policy:str,parser_version:str)->dict[str,object]:
    return {"raw_artifact_hash":digest,"raw_artifact_path":path,"artifact_type":artifact_type,"byte_count":len(content),"content_type":content_type,"character_encoding":"utf-8","source_id":source_id,"request_id":request_id,"query_id":query_id,"run_id":run_id,"captured_at":captured_at,"storage_status":"IMMUTABLE_CONTENT_ADDRESSED","immutable":"True","sensitive_data_redacted":"True","retention_policy":retention_policy,"collector_version":R.COLLECTOR_VERSION,"parser_version":parser_version,"phase13_schema_version":R.PHASE13_SCHEMA_VERSION}
