from dataclasses import dataclass
from datetime import datetime,timezone
from types import MappingProxyType
import hashlib,json
@dataclass(frozen=True)
class Snapshot:identity:str;loaded_at:str;publication_timestamp:str;tables:object;records:object;root:object
@classmethod
def _load(cls,repository):
 tables=repository.load();token=hashlib.sha256(json.dumps({k:len(v) for k,v in tables.items()},sort_keys=True).encode()).hexdigest()[:24]
 return cls('SNAP14::'+token,datetime.now(timezone.utc).isoformat(),repository.timestamp,tables,MappingProxyType(repository.records),repository.settings.root)
Snapshot.load=_load
