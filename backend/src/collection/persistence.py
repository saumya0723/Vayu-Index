"""Deterministic CSV and JSON persistence utilities."""
from __future__ import annotations
import csv,json,os,tempfile
from pathlib import Path
from typing import Iterable,Mapping,Sequence,Any

def write_csv(path:Path,columns:Sequence[str],rows:Iterable[Mapping[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    ordered=sorted(({key:("" if value is None else value) for key,value in row.items()} for row in rows),key=lambda row:tuple(str(row.get(key,"")) for key in columns))
    temporary=path.with_suffix(path.suffix+".tmp")
    with temporary.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(columns),extrasaction="ignore",lineterminator="\n")
        writer.writeheader(); writer.writerows(ordered)
    os.replace(temporary,path)
def read_csv(path:Path)->list[dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as handle:return list(csv.DictReader(handle))
def write_json(path:Path,value:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True)+"\n",encoding="utf-8",newline="\n")
