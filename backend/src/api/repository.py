import csv,hashlib,json,os
from types import MappingProxyType
from .catalog import PUBLICATIONS
from .errors import APIError
from .security import contained
class Repository:
 def __init__(self,settings):
  self.settings=settings;raw=json.loads(contained(settings.root,settings.manifest.relative_to(settings.root).as_posix()).read_text());self.timestamp=raw['publication_timestamp'];self.records={x['id']:x for x in raw['publications']}
  if set(self.records)!=set(PUBLICATIONS):raise APIError(503,'SCHEMA_INCOMPATIBLE','Manifest and publication catalog differ.')
 def load(self):
  skip_hash=os.environ.get('VAYU_SKIP_HASH_CHECK','').strip().lower() in ('1','true','yes')
  tables={}
  for key,spec in PUBLICATIONS.items():
   record=self.records[key];path=contained(self.settings.root,spec.path)
   content=path.read_bytes()
   if not skip_hash:
    raw_hash=hashlib.sha256(content).hexdigest()
    lf_hash=hashlib.sha256(content.replace(b'\r\n',b'\n')).hexdigest()
    if raw_hash!=record['sha256'] and lf_hash!=record['sha256']:
     raise APIError(503,'HASH_MISMATCH',f'A published analytical file failed integrity validation: {spec.path}')
   with path.open(encoding='utf-8-sig',newline='') as f:reader=csv.DictReader(f);header=list(reader.fieldnames or []);rows=list(reader)
   if header!=record['columns']:raise APIError(503,'SCHEMA_INCOMPATIBLE',f'A published analytical file has an incompatible schema: {spec.path}')
   column=record.get('schema_column')
   if column and any(r.get(column)!=spec.schema for r in rows):raise APIError(503,'SCHEMA_INCOMPATIBLE',f'A published analytical file has an incompatible schema version: {spec.path}')
   tables[key]=tuple(MappingProxyType(dict(r)) for r in rows)
  return MappingProxyType(tables)

