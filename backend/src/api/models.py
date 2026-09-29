from typing import Any
from pydantic import BaseModel,ConfigDict,Field
class StrictModel(BaseModel):model_config=ConfigDict(extra='forbid')
class SourceRef(StrictModel):path:str;sha256:str;schema_version:str|None=None
class Meta(StrictModel):api_version:str;response_schema_version:str;pipeline_versions:dict[str,str];publication_timestamp:str;data_status:str;official_status:str;is_real_market_collection:bool;publication_class:str;request_id:str;source_files:list[SourceRef]
class Envelope(StrictModel):meta:Meta;data:Any
class Error(StrictModel):error_code:str;message:str;details:dict[str,Any]=Field(default_factory=dict);request_id:str;api_version:str
