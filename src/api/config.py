from dataclasses import dataclass
from pathlib import Path
import json
import os
API_VERSION='v1';API_PREFIX='/api/v1';SCHEMA_VERSION='phase14-api-v1';DATA_STATUS='SYNTHETIC_PROTOTYPE';OFFICIAL_STATUS='NOT_OFFICIAL';COLLECTION_STATUS='LIVE_COLLECTION_NOT_STARTED'
@dataclass(frozen=True)
class Settings:
 root:Path;origins:tuple[str,...];manifest:Path;max_export_rows:int
 @classmethod
 def load(cls,root=None):
  root=(root or Path(__file__).resolve().parents[2]).resolve();raw=json.loads((root/'config/phase14_api_config.json').read_text())
  configured_origins=os.environ.get('VAYU_ALLOWED_ORIGINS','').strip()
  origins=tuple(origin.strip() for origin in configured_origins.split(',') if origin.strip()) if configured_origins else tuple(raw['allowed_origins'])
  if not origins:raise ValueError('VAYU_ALLOWED_ORIGINS must include at least one origin when set.')
  return cls(root,origins,(root/'config/phase14_publication_manifest.json').resolve(),int(raw['maximum_export_rows']))
